"""The project's .mcp.json entry for Claude Code starts a working catalogue."""
from __future__ import annotations

import json
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

REPO_ROOT = Path(__file__).resolve().parents[2]


async def test_mcp_json_entry_starts_the_catalogue():
    entry = json.loads((REPO_ROOT / ".mcp.json").read_text())["mcpServers"]["copilot-metric-catalogue"]
    assert entry["args"] == ["-m", "src.mcp_catalogue.server"]
    # Launch exactly what Claude Code would: the configured command, from the project root.
    params = StdioServerParameters(command=str(REPO_ROOT / entry["command"]), args=entry["args"], cwd=str(REPO_ROOT))
    async with Client(params) as client:
        result = await client.call_tool("list_domains", {})
    assert not result.is_error
