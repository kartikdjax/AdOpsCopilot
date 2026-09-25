"""Typed output models for the core toolset - same rationale as Phase 2's
mcp_models.py: bare dicts don't give MCP's schema generator enough to
build a proper output schema, and typed models are a documented contract."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class MetricInfo(BaseModel):
    name: str
    domain: str
    kind: str
    unit: str
    description: str


class MetricDefinition(BaseModel):
    name: str
    domain: str
    formula: str
    unit: str
    description: str


class FreshnessInfo(BaseModel):
    domain: str
    last_event: str | None
    lag_minutes: float | None
    status: str
    # revive only: version, plugins and maintenance health (revive_admin.SystemStatus)
    system: dict[str, Any] | None = None


class KpiResult(BaseModel):
    domain: str
    metric: str
    entity_type: str | None
    entity_id: int | None
    days: int
    value: float | None
    unit: str


class PeriodComparison(BaseModel):
    domain: str
    metric: str
    entity_type: str | None
    entity_id: int | None
    current_value: float | None
    previous_value: float | None
    pct_change: float | None
    direction: str


class RankedEntityItem(BaseModel):
    entity_id: int
    name: str
    value: float | None
    volume: float | None = None


class RankingResult(BaseModel):
    domain: str
    metric: str
    entity_type: str
    days: int
    results: list[RankedEntityItem]


class TrendSummary(BaseModel):
    domain: str
    metric: str
    entity_type: str | None
    entity_id: int | None
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
    domain: str
    metric: str
    entity_type: str | None
    entity_id: int | None
    sensitivity: str
    anomalies_found: int
    anomalies: list[AnomalyItem]


class EntityListItem(BaseModel):
    entity_id: int
    name: str


class EntityListResult(BaseModel):
    domain: str
    entity_type: str
    entities: list[EntityListItem]
    truncated: bool = False  # True when more matches exist than `limit` returned


class Contributor(BaseModel):
    entity_id: int
    name: str
    current_value: float | None
    previous_value: float | None
    pct_change: float | None
    delta: float


class MetricChangeExplanation(BaseModel):
    domain: str
    metric: str
    entity_type: str | None
    entity_id: int | None
    current_value: float | None
    previous_value: float | None
    pct_change: float | None
    direction: str
    breakdown_dimension: str | None
    top_contributors: list[Contributor]
    note: str
