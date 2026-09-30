"""The orchestrator exposes only core tools plus the current mode's tools,
checked against the real TOOL_DOMAIN map."""
from __future__ import annotations

import json

from src.orchestrator import _get_mcp_tool_defs
from src.semantic.tool_domains import TOOL_DOMAIN

REVIVE_ONLY = {"generate_revive_report", "get_banner_zone_mapping", "inspect_revive_object",
               "run_revive_check", "get_revive_audit_log"}
EXCHANGE_ONLY = {"generate_exchange_report", "get_realtime_exchange_health", "get_supply_demand_cross_analysis"}


class FakeToolInfo:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"Fake description for {name}, long enough to matter for token counting purposes here."
        self.input_schema = {"type": "object", "properties": {"domain": {"type": "string"},
                                                                "metric": {"type": "string"},
                                                                "days": {"type": "integer"}}}


class FakeListToolsResult:
    def __init__(self, names):
        self.tools = [FakeToolInfo(n) for n in names]


class FakeMcpClient:
    async def list_tools(self):
        return FakeListToolsResult(list(TOOL_DOMAIN.keys()))


async def _names(mode):
    return {t["name"] for t in await _get_mcp_tool_defs(FakeMcpClient(), mode=mode)}


async def test_no_mode_exposes_every_tool():
    assert len(await _names(None)) == 19


async def test_revive_mode_is_core_plus_revive():
    names = await _names("revive")
    assert len(names) == 16
    assert REVIVE_ONLY <= names and not (EXCHANGE_ONLY & names)
    assert "calculate_kpi" in names


async def test_exchange_mode_is_core_plus_exchange():
    names = await _names("exchange")
    assert len(names) == 14
    assert EXCHANGE_ONLY <= names and not (REVIVE_ONLY & names)


async def test_mode_scoping_shrinks_tool_schema():
    client = FakeMcpClient()
    everything = await _get_mcp_tool_defs(client, mode=None)
    revive = await _get_mcp_tool_defs(client, mode="revive")
    assert len(json.dumps(revive)) < len(json.dumps(everything))
