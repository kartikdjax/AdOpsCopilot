"""
Golden test set for the orchestrator - an INTEGRATION test (hits real
Groq API + real ClickHouse + real knowledge base), not a pure unit test.

Purpose: catch silent regressions when you tweak the system prompt,
swap models, or add new tools. "Did it call the right tool?" is exactly
the kind of thing that breaks quietly - a wrong answer LOOKS plausible
even when the tool choice was wrong, so without an explicit check like
this you'd only notice by accident.

Requires: GROQ_API_KEY set, ClickHouse running with data loaded,
knowledge base seeded (python -m src.rag.load_seed_documents).

Run: python -m tests.test_orchestrator_scenarios
"""
from __future__ import annotations

import asyncio

from mcp import Client

from src.config import get_settings
from src.mcp_server import mcp
from src.orchestrator import answer_question
from src.provider_factory import build_provider


SCENARIOS = [
    {
        "name": "list all campaigns",
        "question": "What campaigns do we have?",
        "expect_tools_any_of": ["list_campaigns"],
        "expect_keywords_any_of": ["campaign"],
    },
    {
        "name": "single campaign KPI lookup",
        "question": "How is campaign 1 performing over the last 30 days?",
        "expect_tools_any_of": ["get_kpi_summary", "generate_campaign_report"],
        "expect_keywords_any_of": ["ctr", "click", "impression"],
    },
    {
        "name": "pure policy question (RAG only, no data tools needed)",
        "question": "Why do we cap lookalike audience expansion at 5%?",
        "expect_tools_any_of": ["search_knowledge_base"],
        "expect_keywords_any_of": ["5%", "expansion", "seed"],
    },
    {
        "name": "combined data + policy question (the real test of Phase 4)",
        "question": "Why did CTR change on campaign 3, and what should I check first?",
        "expect_tools_any_of": ["detect_campaign_anomalies", "generate_campaign_report",
                                 "analyze_campaign_trend"],
        "expect_tools_also_any_of": ["search_knowledge_base"],
        "expect_keywords_any_of": ["creative", "tracking", "pixel", "check"],
    },
]


async def run_scenario(scenario: dict, mcp_client: Client, provider) -> bool:
    print("=" * 70)
    print(f"SCENARIO: {scenario['name']}")
    print(f"Question: {scenario['question']}")
    print("=" * 70)

    result = await answer_question(scenario["question"], mcp_client, provider)
    tools_used = set(result["tool_calls_made"])
    answer_lower = result["answer"].lower()

    checks_passed = []
    checks_failed = []

    if any(t in tools_used for t in scenario["expect_tools_any_of"]):
        checks_passed.append(f"used expected data tool ({tools_used & set(scenario['expect_tools_any_of'])})")
    else:
        checks_failed.append(f"expected one of {scenario['expect_tools_any_of']}, got {tools_used}")

    if "expect_tools_also_any_of" in scenario:
        if any(t in tools_used for t in scenario["expect_tools_also_any_of"]):
            checks_passed.append(f"ALSO used expected second tool category "
                                  f"({tools_used & set(scenario['expect_tools_also_any_of'])})")
        else:
            checks_failed.append(f"expected ALSO one of {scenario['expect_tools_also_any_of']}, "
                                  f"got only {tools_used}")

    if any(kw.lower() in answer_lower for kw in scenario["expect_keywords_any_of"]):
        checks_passed.append("answer contains an expected keyword")
    else:
        checks_failed.append(f"none of {scenario['expect_keywords_any_of']} found in answer")

    print(f"Tools used: {tools_used}")
    print(f"Answer (first 200 chars): {result['answer'][:200]}...")
    for c in checks_passed:
        print(f"  PASS: {c}")
    for c in checks_failed:
        print(f"  FAIL: {c}")
    print()

    return len(checks_failed) == 0


async def main() -> None:
    settings = get_settings()
    provider = build_provider(settings)

    results = []
    async with Client(mcp) as mcp_client:
        for scenario in SCENARIOS:
            passed = await run_scenario(scenario, mcp_client, provider)
            results.append((scenario["name"], passed))

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for name, passed in results:
        print(f"  {'PASS' if passed else 'FAIL'}: {name}")

    total_passed = sum(1 for _, p in results if p)
    print(f"\n{total_passed}/{len(results)} scenarios passed")


if __name__ == "__main__":
    asyncio.run(main())
