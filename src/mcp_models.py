"""
Typed output models for MCP tools.

Bare `-> dict` return types don't give the MCP schema generator enough
information to build a proper output schema, which can leave
`structured_content` empty even when the tool actually succeeded. Real
Pydantic models fix this AND give callers (the Phase 4 orchestrator, or
any MCP client) a documented, validated contract instead of a loose bag
of keys - the same "validate at the boundary" principle from Week 1,
now applied to tool outputs instead of just inputs.
"""
from __future__ import annotations

from pydantic import BaseModel


class CampaignInfo(BaseModel):
    campaign_id: int
    campaign_name: str
    status: str
    daily_budget: float


class KPISummary(BaseModel):
    campaign_id: int
    period_days: int
    impressions: int
    clicks: int
    conversions: int
    spend: float
    ctr_pct: float
    cvr_pct: float
    avg_cpc: float


class TrendSummary(BaseModel):
    campaign_id: int
    metric: str
    direction: str
    pct_change: float
    first_half_avg: float
    second_half_avg: float


class AnomalyItem(BaseModel):
    date: str
    actual: float
    expected: float
    z_score: float
    severity: str


class AnomalyReport(BaseModel):
    campaign_id: int
    metric: str
    sensitivity: str
    anomalies_found: int
    anomalies: list[AnomalyItem]


class CampaignReport(BaseModel):
    campaign_id: int
    period_days: int
    kpi_summary: KPISummary
    ctr_trend: TrendSummary
    anomalies: AnomalyReport


class KnowledgeChunk(BaseModel):
    source: str
    similarity: float
    text: str


class KnowledgeSearchResult(BaseModel):
    found: bool
    results: list[KnowledgeChunk]


class IngestResult(BaseModel):
    documents_ingested: int
    chunks_created: int
