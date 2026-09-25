"""
Domain-specific report tools. Each bundles several core-tool calls into
ONE MCP tool invocation - Phase 4 already proved the orchestrator CAN
chain calculate_kpi + analyze_trend + detect_anomalies + search_knowledge_base
itself, but every separate tool call costs a full LLM round-trip, and we've
already hit iteration limits and 429s doing exactly that. Bundling the
common "give me the full picture" case into one call is a direct fix for
that measured cost problem, not a hypothetical one.

These are the ONLY genuinely domain-specific tools left after moving
list_entities into core - everything else that used to be a per-domain
"get_X_performance" tool is now just calculate_kpi/analyze_trend/etc.
with a different `domain` argument.
"""
from __future__ import annotations

from pydantic import BaseModel

from src.semantic.analytics_client import AnalyticsClient
from src.semantic.core_models import AnomalyReport, KpiResult, TrendSummary
from src.semantic.core_tools import analyze_trend, calculate_kpi, detect_anomalies
from src.semantic.metric_registry import EXCHANGE, REVIVE

# The primary metric each report's trend/anomaly section focuses on -
# the one number that best summarizes "is this entity healthy".
_PRIMARY_METRIC = {REVIVE: "fill_rate", EXCHANGE: "win_rate"}
_REPORT_METRICS = {
    REVIVE: ["requests", "impressions", "fill_rate", "ctr", "cvr", "revenue", "margin", "ecpm"],
    EXCHANGE: ["bid_requests", "bids", "wins", "win_rate", "timeout_rate", "ecpm", "avg_latency_ms"],
}


class DomainReport(BaseModel):
    domain: str
    entity_type: str
    entity_id: int
    days: int
    kpis: list[KpiResult]
    primary_metric: str
    trend: TrendSummary | None
    anomalies: AnomalyReport | None
    note: str


def _build_report(client: AnalyticsClient, domain: str, entity_type: str, entity_id: int,
                   days: int) -> DomainReport:
    kpis = [
        calculate_kpi(client, domain, metric, days, entity_type, entity_id)
        for metric in _REPORT_METRICS[domain]
    ]

    primary = _PRIMARY_METRIC[domain]
    trend, anomalies, note_parts = None, None, []

    try:
        trend = analyze_trend(client, domain, primary, days, entity_type, entity_id)
    except ValueError as e:
        note_parts.append(f"Trend unavailable: {e}")

    try:
        anomalies = detect_anomalies(client, domain, primary, days, entity_type, entity_id)
    except ValueError as e:
        note_parts.append(f"Anomaly detection unavailable: {e}")

    note = ("For deeper investigation of any single metric, use analyze_trend, "
            "detect_anomalies, or explain_metric_change directly. "
            + " ".join(note_parts)).strip()

    return DomainReport(domain=domain, entity_type=entity_type, entity_id=entity_id, days=days,
                         kpis=kpis, primary_metric=primary, trend=trend, anomalies=anomalies, note=note)


def generate_revive_report(client: AnalyticsClient, entity_type: str, entity_id: int,
                            days: int = 30) -> DomainReport:
    """Full picture for any Revive entity (zone, banner, campaign, client,
    affiliate, manager) in one call:
    requests, impressions, fill rate, CTR, CVR, revenue, margin and eCPM,
    plus fill-rate trend and anomalies. Use this instead of calling calculate_kpi several
    times when the question is broad ('how is this zone doing overall?')."""
    return _build_report(client, REVIVE, entity_type, entity_id, days)


def generate_exchange_report(client: AnalyticsClient, entity_type: str, entity_id: int,
                              days: int = 30) -> DomainReport:
    """Full picture for an Exchange entity (supply_partner, ad_unit,
    demand_partner, or dsp_campaign) in one call: bid funnel, win rate,
    timeout rate, eCPM, latency, plus win-rate trend and anomalies."""
    return _build_report(client, EXCHANGE, entity_type, entity_id, days)
