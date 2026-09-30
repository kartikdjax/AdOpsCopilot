"""The Copilot's own MCP server keeps exactly the tools and input schemas
recorded in fixtures/copilot_mcp_tools.json. Live because importing the
server connects to ClickHouse.

A change that means to alter the tools regenerates the file in its own diff:

    python -m tests.live.test_copilot_mcp_tools_unchanged --record
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp import Client

FIXTURE = Path(__file__).parent / "fixtures" / "copilot_mcp_tools.json"
RECORD_COMMAND = "python -m tests.live.test_copilot_mcp_tools_unchanged --record"


async def _current_tools() -> dict[str, dict]:
    from src.mcp_server import mcp

    async with Client(mcp) as client:
        tools = (await client.list_tools()).tools
    return {t.name: t.input_schema for t in sorted(tools, key=lambda t: t.name)}


async def test_copilot_tools_unchanged():
    recorded = json.loads(FIXTURE.read_text())
    try:
        current = await _current_tools()
    except Exception as e:  # noqa: BLE001 - importing the server needs ClickHouse
        pytest.skip(f"Copilot MCP server can't start here: {type(e).__name__}: {str(e)[:120]}")
    hint = f"The Copilot MCP server's tools changed. If intended, regenerate with: {RECORD_COMMAND}"
    assert sorted(current) == sorted(recorded), hint
    assert len(current) == 19, hint
    for name, schema in recorded.items():
        assert current[name] == schema, f"{name}: {hint}"


if __name__ == "__main__" and "--record" in sys.argv:
    FIXTURE.write_text(json.dumps(asyncio.run(_current_tools()), indent=2, sort_keys=True) + "\n")
    print(f"Recorded {FIXTURE}")
