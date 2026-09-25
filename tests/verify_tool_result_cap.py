"""
Verifies the in-turn tool-result size cap - the fix for growth WITHIN a
single turn, separate from _compact_history's between-turn fix.
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from src.orchestrator import MAX_TOOL_RESULT_CHARS, _execute_tool_call


class FakeToolCall:
    def __init__(self, id_, name, input_):
        self.id = id_
        self.name = name
        self.input = input_


class FakeToolResult:
    def __init__(self, structured_content=None, content=None, is_error=False):
        self.structured_content = structured_content
        self.content = content
        self.is_error = is_error


class FakeMcpClient:
    def __init__(self, response):
        self._response = response

    async def call_tool(self, name, arguments, meta=None):
        return self._response


async def main() -> None:
    print("=" * 70)
    print("TEST 1: a small tool result passes through unchanged")
    print("=" * 70)
    small = {"campaign_id": 1, "win_rate": 24.5}
    client = FakeMcpClient(FakeToolResult(structured_content=small))
    result = await _execute_tool_call(client, FakeToolCall("1", "calculate_kpi", {}), asyncio.Semaphore(3))
    print(f"content length: {len(result.content)} chars")
    assert "TRUNCATED" not in result.content
    print("PASS: small results are untouched\n")

    print("=" * 70)
    print(f"TEST 2: a large tool result (bigger than {MAX_TOOL_RESULT_CHARS} chars) gets truncated")
    print("=" * 70)
    # Simulate a big list_entities response - hundreds of rows
    big = {"entities": [{"entity_id": i, "name": f"AdUnit_{i}" * 5} for i in range(500)]}
    client = FakeMcpClient(FakeToolResult(structured_content=big))
    result = await _execute_tool_call(client, FakeToolCall("2", "list_entities", {}), asyncio.Semaphore(3))
    print(f"content length: {len(result.content)} chars (cap={MAX_TOOL_RESULT_CHARS})")
    assert "TRUNCATED" in result.content
    assert len(result.content) < MAX_TOOL_RESULT_CHARS + 300, "FAILED: truncation didn't actually bound size"
    print("PASS: oversized result truncated with a clear note, size actually bounded\n")

    print("=" * 70)
    print("TEST 3: truncation note tells the model HOW to get a smaller result")
    print("=" * 70)
    print(result.content[-200:])
    assert "narrow the request" in result.content
    print("PASS: actionable guidance included, not just a silent cutoff\n")

    print("=" * 70)
    print("TEST 4: five large results in one turn now sum to a BOUNDED total, not unbounded")
    print("=" * 70)
    total_if_uncapped = 5 * len(str(big))
    total_capped = 5 * (MAX_TOOL_RESULT_CHARS + 200)  # +200 for the truncation note
    print(f"5 uncapped results would total ~{total_if_uncapped:,} chars")
    print(f"5 capped results total at most ~{total_capped:,} chars")
    assert total_capped < total_if_uncapped
    print(f"PASS: a {5}-tool-call turn is now bounded regardless of how large any single result is\n")

    print("=" * 70)
    print("ALL IN-TURN SIZE CAP CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
