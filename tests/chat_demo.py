"""
Interactive CLI - now mode-aware. Pick 'revive' or 'exchange' at start;
that mode's tools (plus the shared core 11) are the only ones exposed to
the LLM for the whole session.

Requires GROQ_API_KEY in .env, both ClickHouse domains loaded, and the
knowledge base seeded.

Run: python -m tests.chat_demo
"""
from __future__ import annotations

import asyncio

from mcp import Client

from src.config import get_settings
from src.llm_providers.groq_provider import AllModelsFailedError
from src.mcp_server_v2 import mcp
from src.orchestrator import answer_question
from src.semantic.access import ADMIN
from src.provider_factory import build_provider

EXAMPLE_QUESTIONS = {
    "revive": [
        "What zones do we have?",
        "How is zone 3001 performing over the last 30 days?",
        "Why did fill rate change on zone 3001, and what should I check first?",
    ],
    "exchange": [
        "What supply partners do we have?",
        "What's the real-time health of the exchange right now?",
        "Why did win rate change for supply partner 5000, and what should I check first?",
    ],
}


async def main() -> None:
    settings = get_settings()
    try:
        provider = build_provider(settings)
    except ValueError as e:
        print(f"Configuration error: {e}")
        return

    mode = ""
    while mode not in ("revive", "exchange"):
        mode = input("Mode ('revive' or 'exchange'): ").strip().lower()

    history: list[dict] = []
    print(f"\nAI Analytics Copilot - mode: {mode} - type a question, 'mode' to switch "
          f"domains, or 'quit' to exit.")
    for q in EXAMPLE_QUESTIONS[mode]:
        print(f"  e.g. {q}")
    print()

    async with Client(mcp) as mcp_client:
        while True:
            question = input("You: ").strip()
            if question.lower() in {"quit", "exit"}:
                break

            if question.lower() in {"mode", "switch", "switch mode"}:
                new_mode = ""
                while new_mode not in ("revive", "exchange"):
                    new_mode = input("Switch to ('revive' or 'exchange'): ").strip().lower()
                if new_mode == mode:
                    print(f"Already in {mode} mode.\n")
                    continue
                mode = new_mode
                # Reset history on switch - same reasoning as api/main.py
                # keying sessions by (session_id, mode): tool-call results
                # from the old domain would be stale, out-of-scope context
                # in the new one, not just unused history.
                history = []
                print(f"Switched to {mode} mode. Conversation history reset.")
                for q in EXAMPLE_QUESTIONS[mode]:
                    print(f"  e.g. {q}")
                print()
                continue

            if not question:
                continue

            try:
                # Local developer REPL: full admin access to Revive.
                result = await answer_question(question, mcp_client, provider,
                                                conversation_history=history, mode=mode, scope=ADMIN)
            except AllModelsFailedError as e:
                print(f"\n[LLM request failed]: {e}\n")
                continue
            except Exception as e:  # noqa: BLE001 - last-resort guard so one bad turn doesn't kill the REPL
                print(f"\n[Unexpected error]: {type(e).__name__}: {e}")
                print("The conversation history was NOT updated for this turn - try rephrasing.\n")
                continue

            history = result["messages"]
            if result["tool_calls_made"]:
                print(f"  [used tools: {', '.join(result['tool_calls_made'])}]")
            print(f"Copilot: {result['answer']}\n")


if __name__ == "__main__":
    asyncio.run(main())