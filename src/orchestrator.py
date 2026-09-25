"""
Phase 4/7: the agent orchestrator - provider-agnostic, mode-scoped, and
with HISTORY COMPACTION to fix a real production bug: conversation
history was growing every turn by the FULL tool-call trace (every
tool_use + tool_result message), so a 5-turn conversation could balloon
past an 8000-token free-tier limit even when the current question was
trivial. Every subsequent call then failed with 413, regardless of model.

Fix: once a turn reaches a final answer, only {user question, final
answer text} is kept in the history returned to the caller - the full
tool-call trace is used internally for THIS turn's reasoning but is not
carried forward. This bounds history growth to roughly (question +
answer) per turn instead of (question + N tool calls + N tool results)
per turn, which is the actual fix, not just a bigger fallback list.
"""
from __future__ import annotations

import asyncio
import json
import logging

from mcp import Client

from src.llm_providers.base import LLMProvider, ToolResultItem
from src.semantic.access import Scope

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are the AI Analytics Copilot for an AdTech platform. You have "
    "tools to query campaign performance data (KPIs, trends, anomalies) "
    "and to search internal policies and playbooks. "
    "Always use tools to get real data or policy context rather than "
    "guessing or relying on general knowledge - this is a data analytics "
    "assistant, and unverified numbers or policy claims are not "
    "acceptable. If a question needs both data and policy context (e.g. "
    "explaining an anomaly), use both kinds of tools before answering. "
    "IMPORTANT: when you need several tools that DON'T depend on each "
    "other's results, request them TOGETHER in the same turn rather than "
    "one at a time across several turns - this is faster and you have a "
    "limited number of tool-use turns before you must give a final answer. "
    "This applies just as much to the SAME tool called with different "
    "arguments as it does to different tools: if a question needs one tool "
    "called once per entity (e.g. a per-banner or per-campaign lookup "
    "across a list you already have), issue ALL of those calls in one "
    "turn, not one entity per turn - you have a hard cap on tool-use turns, "
    "and calling a repeated per-entity tool one at a time will exhaust it "
    "before you finish. If a tool needs exactly one ID and you must cover "
    "a full list on both sides of a relationship (e.g. every banner's "
    "zone, or vice versa), call it once per entity on whichever side has "
    "FEWER entities, not the side with more. "
    "If you already know an entity_id from the question or from an earlier "
    "answer in this conversation, do not call a list/lookup tool again to "
    "re-verify it. Metric names come ONLY from list_available_metrics or "
    "get_metric_definition - never assume a metric name from another "
    "tool's output field names, since field names and metric names are "
    "not always identical. "
    "Cite which entity_id or knowledge base source your answer is based "
    "on. If tools return no relevant data, say so explicitly instead of "
    "inventing an answer."
)

MAX_TOOL_ITERATIONS = 8
MAX_CONCURRENT_TOOL_CALLS = 3
MAX_HISTORY_TURNS = 10       # compacted (Q, A) pairs kept - even compacted history is capped
MAX_TOOL_RESULT_CHARS = 3000  # ~750 tokens/result - caps IN-TURN growth, see _execute_tool_call


async def _get_mcp_tool_defs(client: Client, mode: str | None = None) -> list[dict]:
    """Fetches all tool definitions from the MCP server, then filters to
    the active mode if one is given - see src/semantic/tool_domains.py."""
    result = await client.list_tools()
    tools = [
        {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
        for t in result.tools
    ]
    if mode is None:
        return tools

    try:
        from src.semantic.tool_domains import TOOL_DOMAIN
    except ImportError:
        logger.warning("TOOL_DOMAIN map not found - mode filtering disabled, all tools exposed")
        return tools

    filtered = [t for t in tools if TOOL_DOMAIN.get(t["name"]) in (None, mode)]
    logger.info("Mode=%s: exposing %d/%d tools", mode, len(filtered), len(tools))
    return filtered


async def _execute_tool_call(mcp_client: Client, tool_call, semaphore: asyncio.Semaphore,
                             scope: Scope | None = None) -> ToolResultItem:
    """Runs one MCP tool call. Never raises - a failure becomes an error
    result the LLM can see and react to, not a crashed conversation.

    Also caps result size at MAX_TOOL_RESULT_CHARS. This is DIFFERENT from
    history compaction: compaction only trims BETWEEN turns, after a final
    answer exists. A single turn that chains several tool calls (common -
    generate_exchange_report + rank_entities + explain_metric_change in
    one question) accumulates every raw result INSIDE that one turn's
    working message list BEFORE compaction ever gets a chance to run - so
    a turn with a few large results (a big list_entities table, a full
    generate_exchange_report payload) can alone exceed an 8000-token
    request limit on the very first LLM call of a multi-tool turn. Capping
    each individual result is the fix for that half of the problem;
    compaction is the fix for the other half (growth across turns).

    `scope` travels as MCP request metadata, beside - never inside - the
    LLM-written arguments, so the model can't widen its own access."""
    async with semaphore:
        try:
            result = await mcp_client.call_tool(tool_call.name, tool_call.input,
                                                meta=scope.to_meta() if scope else None)
            if result.is_error:
                return ToolResultItem(tool_call.id, tool_call.name, f"Tool error: {result.content}", True)
            content = (json.dumps(result.structured_content)
                       if result.structured_content is not None else str(result.content))
            if len(content) > MAX_TOOL_RESULT_CHARS:
                original_len = len(content)
                content = (
                    content[:MAX_TOOL_RESULT_CHARS]
                    + f"... [TRUNCATED: {original_len} chars total, showing first "
                      f"{MAX_TOOL_RESULT_CHARS}. If you need the rest, narrow the request - "
                      f"e.g. fewer days, a smaller limit, or a more specific entity_id.]"
                )
                logger.info("Truncated %s result: %d -> %d chars", tool_call.name,
                            original_len, MAX_TOOL_RESULT_CHARS)
            return ToolResultItem(tool_call.id, tool_call.name, content, False)
        except Exception as exc:  # noqa: BLE001 - any tool failure must not crash the conversation
            logger.exception("Tool call failed: %s", tool_call.name)
            return ToolResultItem(tool_call.id, tool_call.name, f"Tool execution failed: {exc}", True)


def _compact_history(prior_compacted_history: list[dict], question: str, final_text: str) -> list[dict]:
    """Builds the history to CARRY FORWARD to the next turn: prior compacted
    turns plus this turn's {question, answer} only - NOT the tool-call
    trace that produced the answer. Plain {role, content} text messages are
    valid input for both Anthropic- and OpenAI-style APIs, so this needs no
    provider-specific handling, unlike the raw in-turn trace does.

    Also enforces MAX_HISTORY_TURNS so even compacted history can't grow
    unbounded over a very long conversation - oldest turns drop first.
    """
    compacted = list(prior_compacted_history) + [
        {"role": "user", "content": question},
        {"role": "assistant", "content": final_text},
    ]
    # Each turn is 2 messages (user + assistant); trim from the front in
    # pairs so we never cut a turn in half.
    max_messages = MAX_HISTORY_TURNS * 2
    if len(compacted) > max_messages:
        compacted = compacted[-max_messages:]
    return compacted


async def answer_question(
    question: str,
    mcp_client: Client,
    provider: LLMProvider,
    conversation_history: list[dict] | None = None,
    mode: str | None = None,
    scope: Scope | None = None,
) -> dict:
    """Runs the full tool-use loop for one user question.

    Args:
        conversation_history: COMPACTED history from prior turns (as
            returned by a previous call's "messages" key) - not the raw
            tool-call trace.
        mode: "revive", "exchange", or None (all tools).
        scope: whose data the tools may read (see src/semantic/access.py).
            Without one, Revive tools refuse to run.

    Returns {"answer": str, "tool_calls_made": list[str], "messages": list[dict]}.
    `messages` is already compacted and safe to pass straight back in as
    conversation_history on the next call.
    """
    mcp_tools = await _get_mcp_tool_defs(mcp_client, mode)
    tools = provider.convert_mcp_tools(mcp_tools)

    system_prompt = SYSTEM_PROMPT
    if mode == "revive":
        system_prompt += (
            "\n\nActive mode: REVIVE (ad server). Every data tool call must use "
            "domain='revive'. Entity types available: zone, banner, campaign, client, "
            "affiliate (a website/publisher), manager (owns advertisers and websites). "
            "Money metrics: revenue, cost, margin, margin_pct, ecpm. "
            "For setup questions (dates, pacing, links, sizes, targeting, users, access) "
            "use inspect_revive_object or run_revive_check, not the metric tools. "
            "When explaining why a metric changed, also check get_revive_audit_log "
            "for that entity - a settings change on the same day is often the cause. "
            "You have no visibility into exchange/RTB data in this mode."
        )
    elif mode == "exchange":
        system_prompt += (
            "\n\nActive mode: EXCHANGE (RTB/programmatic). Every data tool call must "
            "use domain='exchange'. Entity types available: supply_partner, ad_unit, "
            "demand_partner, dsp_campaign. You have no visibility into Revive ad-server "
            "data in this mode."
        )

    if scope is not None and scope.role == "manager" and mode == "revive":
        system_prompt += (
            "\n\nAccess: this user is a Revive MANAGER. Every tool result is already limited to "
            "their own advertisers, websites, campaigns, zones and users - nothing platform-wide. "
            "Describe totals as theirs (e.g. 'across your accounts'), never as platform totals. "
            "If a requested object isn't found, it may belong to another manager: say it isn't "
            "available to them, without guessing about it."
        )

    prior_compacted_history = list(conversation_history or [])
    # `messages` is the FULL working trace for THIS turn only - prior
    # compacted history, plus every tool_use/tool_result this turn
    # generates. It is used for reasoning during the loop below, but is
    # NEVER returned as-is; see _compact_history().
    messages = list(prior_compacted_history)
    messages.append({"role": "user", "content": question})

    tool_calls_made: list[str] = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TOOL_CALLS)
    asked_for_text = False

    for iteration in range(MAX_TOOL_ITERATIONS):
        turn = await provider.get_turn(messages, tools, system_prompt)
        messages.append(turn.assistant_message)

        if turn.is_final:
            final_text = turn.text or ""
            if not final_text.strip() and not asked_for_text:
                # Some models occasionally end a turn with no text after their
                # tool calls. Ask once for the answer instead of showing a blank one.
                asked_for_text = True
                messages.append({"role": "user", "content": (
                    "Please give your final answer to my question in plain text, "
                    "based on the tool results above.")})
                continue
            if not final_text.strip():
                final_text = ("I gathered the data but couldn't put an answer together. "
                              "Please try asking again, or narrow the question.")
            compacted = _compact_history(prior_compacted_history, question, final_text)
            return {"answer": final_text, "tool_calls_made": tool_calls_made, "messages": compacted}

        tool_calls_made.extend(tc.name for tc in turn.tool_calls)
        logger.info("Iteration %d: calling tools %s", iteration, [tc.name for tc in turn.tool_calls])

        results = await asyncio.gather(
            *[_execute_tool_call(mcp_client, tc, semaphore, scope) for tc in turn.tool_calls]
        )
        messages.extend(provider.build_tool_result_messages(list(results)))

    logger.warning("Hit MAX_TOOL_ITERATIONS=%d without a final answer", MAX_TOOL_ITERATIONS)
    fallback_text = ("I wasn't able to reach a final answer within the allowed number of tool "
                      "calls. Try narrowing the question (e.g. a specific entity_id).")
    compacted = _compact_history(prior_compacted_history, question, fallback_text)
    return {"answer": fallback_text, "tool_calls_made": tool_calls_made, "messages": compacted}
