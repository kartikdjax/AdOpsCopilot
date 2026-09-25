"""Read-only MCP catalogue and end-user guidance."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from src.api.auth import get_current_user

router = APIRouter(prefix="/mcp", tags=["MCP guidance"])

# One line per tool, in end-user terms: when the copilot reaches for it.
GUIDANCE = {
    # Shared by both modes
    "list_available_metrics": "Lists the metrics a mode can report on, with their formulas.",
    "get_metric_definition": "Explains exactly how one metric is calculated, e.g. what fill rate means in Revive vs Exchange.",
    "list_entities": "Finds zones, banners, campaigns, advertisers, websites or managers by name, so questions can name them.",
    "get_data_freshness": "Checks how current the data is. In Revive it also reports the version, plugins and whether maintenance is running.",
    "calculate_kpi": "One number for a period: impressions, fill rate, revenue, margin, eCPM and more.",
    "compare_periods": "This period against the one before it, e.g. last 7 days vs the previous 7.",
    "rank_entities": "Best or worst performers by any metric, with a minimum volume so tiny numbers don't mislead.",
    "analyze_trend": "How a metric moves over time, by hour, day, week or month.",
    "detect_anomalies": "Flags unusual days for a metric.",
    "explain_metric_change": "Breaks down why a metric changed and which child entities drove it.",
    "search_knowledge_base": "Finds internal playbooks and policies, such as what to check before changing a campaign's priority.",
    # Revive
    "generate_revive_report": "A full picture of one zone, banner, campaign, advertiser, website or manager in one step.",
    "get_banner_zone_mapping": "Where banners actually delivered: which zones a banner ran in, or which banners ran in a zone.",
    "inspect_revive_object": "Settings of one object and what it's linked to: dates, pacing, caps, sizes, targeting, access.",
    "run_revive_check": "Health checks across the ad server: expiring or behind-pace campaigns, unlinked zones, size mismatches, inactive users.",
    "get_revive_audit_log": "Who changed what and when, shown as before and after values.",
    # Exchange
    "generate_exchange_report": "A full picture of one supply partner, ad unit, demand partner or DSP campaign.",
    "get_realtime_exchange_health": "Live QPS, bid rate, timeouts and latency from the last few minutes.",
    "get_supply_demand_cross_analysis": "How a metric varies across supply and demand partners together.",
}

@router.get("/tools")
async def tools(request: Request, user=Depends(get_current_user)):
    client = request.app.state.app_state.get("mcp_client")
    if client is None:
        return {"tools": [], "message": "MCP client is still starting"}
    result = await client.list_tools()
    from src.semantic.tool_domains import TOOL_DOMAIN
    items = []
    for tool in result.tools:
        domain = TOOL_DOMAIN.get(tool.name, "shared")
        items.append({"name": tool.name, "domain": domain, "description": tool.description or "", "guidance": GUIDANCE.get(tool.name, "The copilot may use this tool when its description matches your question.")})
    return {"tools": items}
