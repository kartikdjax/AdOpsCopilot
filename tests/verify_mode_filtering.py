"""Verifies orchestrator's mode filtering against the real TOOL_DOMAIN map."""
from __future__ import annotations

import asyncio
import json
import sys

sys.path.insert(0, ".")

from src.semantic.tool_domains import TOOL_DOMAIN
from src.orchestrator import _get_mcp_tool_defs


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


async def main() -> None:
    client = FakeMcpClient()

    print("=" * 70)
    print("TEST 1: no mode -> all 16 tools exposed")
    print("=" * 70)
    all_tools = await _get_mcp_tool_defs(client, mode=None)
    print(f"{len(all_tools)} tools")
    assert len(all_tools) == 19
    print("PASS\n")

    print("=" * 70)
    print("TEST 2: revive mode -> 11 core + 5 revive = 16 tools, ZERO exchange tools")
    print("=" * 70)
    revive_tools = await _get_mcp_tool_defs(client, mode="revive")
    names = {t["name"] for t in revive_tools}
    print(f"{len(revive_tools)} tools: {sorted(names)}")
    assert len(revive_tools) == 16
    assert "generate_exchange_report" not in names
    assert "get_realtime_exchange_health" not in names
    assert "get_supply_demand_cross_analysis" not in names
    assert "generate_revive_report" in names
    assert "get_banner_zone_mapping" in names
    assert "calculate_kpi" in names  # a core tool, must still be present
    print("PASS: exchange-only tools correctly excluded\n")

    print("=" * 70)
    print("TEST 3: exchange mode -> 11 core + 3 exchange = 14 tools, ZERO revive tools")
    print("=" * 70)
    exchange_tools = await _get_mcp_tool_defs(client, mode="exchange")
    names = {t["name"] for t in exchange_tools}
    print(f"{len(exchange_tools)} tools: {sorted(names)}")
    assert len(exchange_tools) == 14
    assert "generate_revive_report" not in names
    assert "get_banner_zone_mapping" not in names
    assert "generate_exchange_report" in names
    assert "get_realtime_exchange_health" in names
    assert "get_supply_demand_cross_analysis" in names
    print("PASS: revive-only tools correctly excluded\n")

    print("=" * 70)
    print("TEST 4: measured token-size reduction from mode scoping")
    print("=" * 70)
    def approx_tokens(tools):
        return len(json.dumps(tools)) // 4

    print(f"No mode (all 16):    ~{approx_tokens(all_tools):,} tokens")
    print(f"Revive mode (16):    ~{approx_tokens(revive_tools):,} tokens")
    print(f"Exchange mode (14):  ~{approx_tokens(exchange_tools):,} tokens")
    reduction = (1 - approx_tokens(revive_tools) / approx_tokens(all_tools)) * 100
    print(f"Revive mode saves ~{reduction:.0f}% of tool-schema tokens vs exposing everything")
    assert approx_tokens(revive_tools) < approx_tokens(all_tools)
    print("PASS\n")

    print("=" * 70)
    print("ALL MODE-FILTERING CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
