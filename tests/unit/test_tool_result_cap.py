"""The in-turn tool-result size cap (separate from _compact_history's
between-turn trimming)."""
from __future__ import annotations

import asyncio

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


async def _run(structured_content):
    client = FakeMcpClient(FakeToolResult(structured_content=structured_content))
    return await _execute_tool_call(client, FakeToolCall("1", "list_entities", {}), asyncio.Semaphore(3))


async def test_small_result_passes_unchanged():
    result = await _run({"campaign_id": 1, "win_rate": 24.5})
    assert "TRUNCATED" not in result.content


async def test_large_result_is_truncated_with_guidance():
    big = {"entities": [{"entity_id": i, "name": f"AdUnit_{i}" * 5} for i in range(500)]}
    result = await _run(big)
    assert "TRUNCATED" in result.content
    assert len(result.content) < MAX_TOOL_RESULT_CHARS + 300
    assert "narrow the request" in result.content
