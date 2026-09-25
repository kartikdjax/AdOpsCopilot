"""
Phase 2+3 MCP server - now with typed outputs (src/mcp_models.py) instead
of bare dicts, and errors raised as exceptions (which mcp v2 surfaces as
a proper tool error, isError=True) instead of returning an ambiguous
{"error": ...} dict shaped like a partial success.

Run: python -m src.mcp_server
Test: python -m tests.test_mcp_client
"""
from __future__ import annotations

import logging

import clickhouse_connect
import pandas as pd
from mcp.server.mcpserver import MCPServer

from src.analytics.anomaly_detection import detect_anomalies
from src.analytics.trend_analysis import analyze_trend
from src.config import get_settings
from src.mcp_models import (
    AnomalyItem, AnomalyReport, CampaignInfo, CampaignReport,
    IngestResult, KnowledgeChunk, KnowledgeSearchResult, KPISummary, TrendSummary,
)
from src.rag.chunking import recursive_chunk
from src.rag.vector_store import KnowledgeBaseStore

logging.basicConfig(level=get_settings().log_level)
logger = logging.getLogger(__name__)

mcp = MCPServer("ai-analytics-copilot")
_settings = get_settings()
_client = clickhouse_connect.get_client(
    host=_settings.clickhouse_host, port=_settings.clickhouse_port,
    database=_settings.clickhouse_database,
    username=_settings.clickhouse_username, password=_settings.clickhouse_password,
)
_kb = KnowledgeBaseStore(_settings)


def _query_daily_stats(campaign_id: int, days: int) -> pd.DataFrame:
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
def list_campaigns() -> list[CampaignInfo]:
    """List all campaigns with their IDs and names, so the user (or the
    LLM orchestrator) can resolve a campaign name mentioned in a question
    to the campaign_id these other tools need."""
    query = "SELECT campaign_id, campaign_name, status, daily_budget FROM adtech.campaigns"
    df = _client.query_df(query)
    return [CampaignInfo(**row) for row in df.to_dict(orient="records")]


@mcp.tool()
def get_kpi_summary(campaign_id: int, days: int = 30) -> KPISummary:
    """Get aggregated KPI totals for a campaign over the last N days:
    impressions, clicks, conversions, spend, CTR, CVR, average CPC.

    Args:
        campaign_id: the campaign to summarize.
        days: how many days of history to include.
    """
    daily = _query_daily_stats(campaign_id, days)
    if daily.empty:
        raise ValueError(f"No data found for campaign_id={campaign_id} in the last {days} days")

    total_impressions = int(daily["impressions"].sum())
    total_clicks = int(daily["clicks"].sum())
    total_conversions = int(daily["conversions"].sum())
    total_spend = float(daily["spend"].sum())

    return KPISummary(
        campaign_id=campaign_id,
        period_days=days,
        impressions=total_impressions,
        clicks=total_clicks,
        conversions=total_conversions,
        spend=round(total_spend, 2),
        ctr_pct=round(total_clicks / total_impressions * 100, 3) if total_impressions else 0,
        cvr_pct=round(total_conversions / total_clicks * 100, 3) if total_clicks else 0,
        avg_cpc=round(total_spend / total_clicks, 4) if total_clicks else 0,
    )


@mcp.tool()
def analyze_campaign_trend(campaign_id: int, metric: str = "ctr_pct", days: int = 30) -> TrendSummary:
    """Analyze whether a metric is trending up, down, or stable over time
    for a campaign, comparing the first half vs second half of the period.

    Args:
        campaign_id: the campaign to analyze.
        metric: one of "ctr_pct", "cvr_pct", "spend", "impressions", "clicks".
        days: how many days of history to analyze.
    """
    daily = _query_daily_stats(campaign_id, days)
    if len(daily) < 4:
        raise ValueError(f"Not enough data ({len(daily)} days) for a meaningful trend over {days}-day window")

    result = analyze_trend(daily, metric)
    return TrendSummary(
        campaign_id=campaign_id, metric=result.metric, direction=result.direction,
        pct_change=result.pct_change, first_half_avg=result.first_half_avg,
        second_half_avg=result.second_half_avg,
    )


@mcp.tool()
def detect_campaign_anomalies(campaign_id: int, metric: str = "ctr_pct",
                               days: int = 30, sensitivity: str = "normal") -> AnomalyReport:
    """Detect days where a metric deviated unusually from its recent
    trailing baseline - e.g. a sudden CTR crash or spend spike.

    Args:
        campaign_id: the campaign to check.
        metric: one of "ctr_pct", "cvr_pct", "spend", "impressions", "clicks".
        days: how many days of history to check.
        sensitivity: "high" (z>=2.0) or "normal" (z>=3.0, recommended
            default - see Phase 2 notes on false-positive rates at z=2.0).
    """
    z_threshold = 2.0 if sensitivity == "high" else 3.0
    daily = _query_daily_stats(campaign_id, days)
    if len(daily) < 10:
        raise ValueError(f"Not enough data ({len(daily)} days) for reliable anomaly detection")

    anomalies = detect_anomalies(daily, metric, window=7, z_threshold=z_threshold)
    return AnomalyReport(
        campaign_id=campaign_id, metric=metric, sensitivity=sensitivity,
        anomalies_found=len(anomalies),
        anomalies=[
            AnomalyItem(date=str(a.date.date()), actual=a.actual_value,
                        expected=a.expected_value, z_score=a.z_score, severity=a.severity)
            for a in anomalies
        ],
    )


@mcp.tool()
def generate_campaign_report(campaign_id: int, days: int = 30) -> CampaignReport:
    """Generate a full structured report for a campaign: KPI summary, CTR
    trend, and any detected anomalies - the raw material for a narrative
    summary an LLM can turn into a written report.

    Args:
        campaign_id: the campaign to report on.
        days: how many days of history to cover.
    """
    kpi = get_kpi_summary(campaign_id, days)
    trend = analyze_campaign_trend(campaign_id, "ctr_pct", days)
    anomalies = detect_campaign_anomalies(campaign_id, "ctr_pct", days, sensitivity="normal")

    return CampaignReport(campaign_id=campaign_id, period_days=days,
                           kpi_summary=kpi, ctr_trend=trend, anomalies=anomalies)


@mcp.tool()
def search_knowledge_base(query: str, top_k: int = 3) -> KnowledgeSearchResult:
    """Search internal policies, playbooks, and reporting standards for
    context relevant to a question - e.g. 'why do we cap lookalike
    expansion?' or 'what should I check before escalating a CTR drop?'.
    Use this ALONGSIDE the numeric tools when a question needs both data
    and institutional knowledge to answer well.

    Args:
        query: the natural-language question or topic to search for.
        top_k: how many relevant document chunks to return.
    """
    chunks = _kb.query(query, n_results=top_k)
    return KnowledgeSearchResult(
        found=bool(chunks),
        results=[KnowledgeChunk(source=c.source, similarity=round(c.similarity, 3), text=c.text)
                 for c in chunks],
    )


@mcp.tool()
def ingest_knowledge_docs(documents: list[dict], max_chunk_size: int = 500) -> IngestResult:
    """Add new policy/playbook/reporting documents to the knowledge base
    so they become searchable via search_knowledge_base.

    Args:
        documents: list of {"source": str, "text": str} dicts.
        max_chunk_size: max characters per chunk.
    """
    chunk_ids, chunk_texts, chunk_sources = [], [], []
    for doc_index, doc in enumerate(documents):
        for chunk in recursive_chunk(doc["text"], max_chunk_size=max_chunk_size):
            chunk_ids.append(f"{doc['source']}_{doc_index}_{chunk.chunk_index}")
            chunk_texts.append(chunk.text)
            chunk_sources.append(doc["source"])
    _kb.add(ids=chunk_ids, documents=chunk_texts, sources=chunk_sources)
    return IngestResult(documents_ingested=len(documents), chunks_created=len(chunk_ids))


if __name__ == "__main__":
    mcp.run()