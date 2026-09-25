"""
Which conversation mode each MCP tool belongs to. None = core (always loaded).
Kept dependency-free - see the module docstring history for why.
"""
from __future__ import annotations

TOOL_DOMAIN: dict[str, str | None] = {
    "list_available_metrics": None,
    "get_metric_definition": None,
    "list_entities": None,
    "get_data_freshness": None,
    "calculate_kpi": None,
    "compare_periods": None,
    "rank_entities": None,
    "analyze_trend": None,
    "detect_anomalies": None,
    "explain_metric_change": None,
    "search_knowledge_base": None,
    "generate_revive_report": "revive",
    "get_banner_zone_mapping": "revive",
    "inspect_revive_object": "revive",
    "run_revive_check": "revive",
    "get_revive_audit_log": "revive",
    "generate_exchange_report": "exchange",
    "get_realtime_exchange_health": "exchange",
    "get_supply_demand_cross_analysis": "exchange",
}
