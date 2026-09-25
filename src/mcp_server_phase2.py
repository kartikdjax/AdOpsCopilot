"""
Phase 2: MCP server exposing the analytics functions as tools.

Run: python -m src.mcp_server
Test: npx @modelcontextprotocol/inspector python -m src.mcp_server

NOTE: this version queries a real ClickHouse instance via
ClickHouseAnalytics (Phase 1's schema). Requires ClickHouse running
(docker compose up -d) and data loaded (load_to_clickhouse.py).
"""
from __future__ import annotations

import logging

import clickhouse_connect
import pandas as pd
from mcp.server.mcpserver import MCPServer  # v2: was `from mcp.server.fastmcp import FastMCP`

from src.analytics.anomaly_detection import detect_anomalies
from src.analytics.trend_analysis import analyze_trend
from src.config import get_settings

logging.basicConfig(level=get_settings().log_level)
logger = logging.getLogger(__name__)

mcp = MCPServer("ai-analytics-copilot")  # v2: was FastMCP("ai-analytics-copilot")
_settings = get_settings()
_client = clickhouse_connect.get_client(
    host=_settings.clickhouse_host, port=_settings.clickhouse_port,
    database=_settings.clickhouse_database,
    username=_settings.clickhouse_username, password=_settings.clickhouse_password,
)


def _query_daily_stats(campaign_id: int, days: int) -> pd.DataFrame:
    """Queries ClickHouse's pre-aggregated daily_campaign_stats materialized
    view - fast even over months of history, since raw events are never
    rescanned for this (see Phase 1 schema comments)."""
    query = """
        SELECT
            event_date,
            sumMerge(impressions) AS impressions,
            sumMerge(clicks) AS clicks,
            sumMerge(conversions) AS conversions,
            sumMerge(spend) AS spend
        FROM adtech.daily_campaign_stats
        WHERE campaign_id = {campaign_id:UInt32}
          AND event_date >= today() - {days:UInt32}
        GROUP BY event_date
        ORDER BY event_date
    """
    df = _client.query_df(query, parameters={"campaign_id": campaign_id, "days": days})
    df["ctr_pct"] = (df["clicks"] / df["impressions"].replace(0, pd.NA) * 100).fillna(0).round(3)
    df["cvr_pct"] = (df["conversions"] / df["clicks"].replace(0, pd.NA) * 100).fillna(0).round(3)
    df["event_date"] = pd.to_datetime(df["event_date"])
    return df


@mcp.tool()
def list_campaigns() -> list[dict]:
    """List all campaigns with their IDs and names, so the user (or the
    LLM orchestrator) can resolve a campaign name mentioned in a question
    to the campaign_id these other tools need."""
    query = "SELECT campaign_id, campaign_name, status, daily_budget FROM adtech.campaigns"
    df = _client.query_df(query)
    return df.to_dict(orient="records")


@mcp.tool()
def get_kpi_summary(campaign_id: int, days: int = 30) -> dict:
    """Get aggregated KPI totals for a campaign over the last N days:
    impressions, clicks, conversions, spend, CTR, CVR, average CPC.

    Args:
        campaign_id: the campaign to summarize.
        days: how many days of history to include.
    """
    daily = _query_daily_stats(campaign_id, days)
    if daily.empty:
        return {"error": f"No data found for campaign_id={campaign_id} in the last {days} days"}

    total_impressions = int(daily["impressions"].sum())
    total_clicks = int(daily["clicks"].sum())
    total_conversions = int(daily["conversions"].sum())
    total_spend = float(daily["spend"].sum())

    return {
        "campaign_id": campaign_id,
        "period_days": days,
        "impressions": total_impressions,
        "clicks": total_clicks,
        "conversions": total_conversions,
        "spend": round(total_spend, 2),
        "ctr_pct": round(total_clicks / total_impressions * 100, 3) if total_impressions else 0,
        "cvr_pct": round(total_conversions / total_clicks * 100, 3) if total_clicks else 0,
        "avg_cpc": round(total_spend / total_clicks, 4) if total_clicks else 0,
    }


@mcp.tool()
def analyze_campaign_trend(campaign_id: int, metric: str = "ctr_pct", days: int = 30) -> dict:
    """Analyze whether a metric is trending up, down, or stable over time
    for a campaign, comparing the first half vs second half of the period.

    Args:
        campaign_id: the campaign to analyze.
        metric: one of "ctr_pct", "cvr_pct", "spend", "impressions", "clicks".
        days: how many days of history to analyze.
    """
    daily = _query_daily_stats(campaign_id, days)
    if len(daily) < 4:
        return {"error": f"Not enough data ({len(daily)} days) for a meaningful trend over {days}-day window"}

    result = analyze_trend(daily, metric)
    return {
        "campaign_id": campaign_id, "metric": result.metric, "direction": result.direction,
        "pct_change": result.pct_change, "first_half_avg": result.first_half_avg,
        "second_half_avg": result.second_half_avg,
    }


@mcp.tool()
def detect_campaign_anomalies(campaign_id: int, metric: str = "ctr_pct",
                               days: int = 30, sensitivity: str = "normal") -> dict:
    """Detect days where a metric deviated unusually from its recent
    trailing baseline - e.g. a sudden CTR crash or spend spike.

    Args:
        campaign_id: the campaign to check.
        metric: one of "ctr_pct", "cvr_pct", "spend", "impressions", "clicks".
        days: how many days of history to check.
        sensitivity: "high" (z>=2.0, catches minor blips too) or
            "normal" (z>=3.0, only flags genuinely unusual days - the
            recommended default, since z=2.0 produces meaningful false
            positive noise on real-world data, verified empirically).
    """
    z_threshold = 2.0 if sensitivity == "high" else 3.0
    daily = _query_daily_stats(campaign_id, days)
    if len(daily) < 10:
        return {"error": f"Not enough data ({len(daily)} days) for reliable anomaly detection"}

    anomalies = detect_anomalies(daily, metric, window=7, z_threshold=z_threshold)
    return {
        "campaign_id": campaign_id, "metric": metric, "sensitivity": sensitivity,
        "anomalies_found": len(anomalies),
        "anomalies": [
            {"date": str(a.date.date()), "actual": a.actual_value, "expected": a.expected_value,
             "z_score": a.z_score, "severity": a.severity}
            for a in anomalies
        ],
    }


@mcp.tool()
def generate_campaign_report(campaign_id: int, days: int = 30) -> dict:
    """Generate a full structured report for a campaign: KPI summary, CTR
    trend, and any detected anomalies - the raw material for a narrative
    summary an LLM can turn into a written report.

    Args:
        campaign_id: the campaign to report on.
        days: how many days of history to cover.
    """
    kpi = get_kpi_summary(campaign_id, days)
    if "error" in kpi:
        return kpi

    trend = analyze_campaign_trend(campaign_id, "ctr_pct", days)
    anomalies = detect_campaign_anomalies(campaign_id, "ctr_pct", days, sensitivity="normal")

    return {"campaign_id": campaign_id, "period_days": days,
            "kpi_summary": kpi, "ctr_trend": trend, "anomalies": anomalies}


if __name__ == "__main__":
    mcp.run()