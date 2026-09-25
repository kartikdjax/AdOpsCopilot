"""
The 10 core tools - always loaded regardless of which domain mode
(Revive / Exchange) is active. Every function here works identically for
both domains because it goes through the metric registry and query
builder rather than hardcoding either schema.

Kept as plain functions (business logic), separate from the MCP tool
decorators - same "business logic vs transport" separation used in
Phase 2/3, so these are testable without an MCP server or even ClickHouse
running (the pure-logic pieces; the DB-backed ones need AnalyticsClient).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.analytics.anomaly_detection import detect_anomalies as _detect_anomalies_algo
from src.analytics.trend_analysis import analyze_trend as _analyze_trend_algo
from src.semantic.analytics_client import AnalyticsClient
from src.semantic.core_models import (
    AnomalyItem, AnomalyReport, Contributor, EntityListItem, EntityListResult, FreshnessInfo,
    KpiResult, MetricChangeExplanation, MetricDefinition, MetricInfo, PeriodComparison,
    RankedEntityItem, RankingResult, TrendSummary,
)
from src.semantic import revive_admin
from src.semantic.metric_registry import EXCHANGE, REVIVE, get_metric, list_metrics

if TYPE_CHECKING:
    from src.rag.vector_store import KnowledgeBaseStore

# Hierarchy used by explain_metric_change's drill-down. Zone and banner
# (Revive), ad_unit and dsp_campaign (Exchange) have no further child in
# our schema, so they get an overall comparison with no breakdown. A Revive
# manager owns two trees (client -> campaign -> banner, and website ->
# zone); its drill-down goes to clients, since advertisers drive revenue.
_CHILD_ENTITY: dict[tuple[str, str], str] = {
    (REVIVE, "manager"): "client",
    (REVIVE, "client"): "campaign",
    (REVIVE, "campaign"): "banner",
    (REVIVE, "affiliate"): "zone",
    (EXCHANGE, "supply_partner"): "ad_unit",
    (EXCHANGE, "demand_partner"): "dsp_campaign",
}
_DEFAULT_BREAKDOWN = {REVIVE: "campaign", EXCHANGE: "demand_partner"}


def _classify_direction(pct_change: float | None, stable_threshold_pct: float = 8.0) -> str:
    if pct_change is None:
        return "unknown"
    if abs(pct_change) < stable_threshold_pct:
        return "stable"
    return "increasing" if pct_change > 0 else "decreasing"


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


# ---------------------------------------------------------------------
# 1-2: Discovery
# ---------------------------------------------------------------------
def list_available_metrics(domain: str) -> list[MetricInfo]:
    return [MetricInfo(name=m.name, domain=m.domain, kind=m.kind, unit=m.unit,
                        description=m.description)
            for m in list_metrics(domain)]


def get_metric_definition(domain: str, metric: str) -> MetricDefinition:
    m = get_metric(domain, metric)
    return MetricDefinition(name=m.name, domain=m.domain, formula=m.formula_text,
                             unit=m.unit, description=m.description)


def list_entities(client: AnalyticsClient, domain: str, entity_type: str, search: str | None = None,
                   parent_type: str | None = None, parent_id: int | None = None,
                   limit: int = 50) -> EntityListResult:
    """Resolves names to IDs - e.g. so 'zone Zone_3_healthy' in a question
    becomes the zoneid the other tools need. Genuinely generic across both
    domains (query_builder.build_entity_list_query already handles the
    per-domain label table), so this is one tool, not one per domain.

    Capped at `limit` so a real install with thousands of banners can't
    flood the context; one extra row is fetched to tell whether the cap
    cut anything off."""
    df = client.entity_list(domain, entity_type, search, parent_type, parent_id, limit + 1)
    entities = [EntityListItem(entity_id=int(row["entity_id"]), name=str(row["name"]))
                for _, row in df.iterrows()]
    return EntityListResult(domain=domain, entity_type=entity_type, entities=entities[:limit],
                            truncated=len(entities) > limit)


# ---------------------------------------------------------------------
# 3: Governance
# ---------------------------------------------------------------------
def get_data_freshness(client: AnalyticsClient, domain: str) -> FreshnessInfo:
    result = client.data_freshness(domain)
    system = revive_admin.get_system_status(client).model_dump() if domain == REVIVE else None
    return FreshnessInfo(domain=domain, **result, system=system)


# ---------------------------------------------------------------------
# 4-6: KPI computation
# ---------------------------------------------------------------------
def calculate_kpi(client: AnalyticsClient, domain: str, metric: str, days: int = 30,
                   entity_type: str | None = None, entity_id: int | None = None) -> KpiResult:
    m = get_metric(domain, metric)
    result = client.aggregate(domain, [metric], days, entity_type, entity_id)
    return KpiResult(domain=domain, metric=metric, entity_type=entity_type, entity_id=entity_id,
                      days=days, value=result.get(metric), unit=m.unit)


def compare_periods(client: AnalyticsClient, domain: str, metric: str, days: int = 14,
                     entity_type: str | None = None, entity_id: int | None = None) -> PeriodComparison:
    """Compares the last `days` to the `days` before that - two equal,
    non-overlapping windows, not a smoothed trend (see analyze_trend for that)."""
    current = client.period_aggregate(domain, [metric], start_days_ago=days, end_days_ago=0,
                                       entity_type=entity_type, entity_id=entity_id)
    previous = client.period_aggregate(domain, [metric], start_days_ago=days * 2, end_days_ago=days,
                                        entity_type=entity_type, entity_id=entity_id)
    current_val, previous_val = current.get(metric), previous.get(metric)
    pct = _pct_change(current_val, previous_val)
    return PeriodComparison(domain=domain, metric=metric, entity_type=entity_type, entity_id=entity_id,
                             current_value=current_val, previous_value=previous_val,
                             pct_change=pct, direction=_classify_direction(pct))


def rank_entities(client: AnalyticsClient, domain: str, metric: str, entity_type: str, days: int = 30,
                   limit: int = 10, ascending: bool = False,
                   min_volume_metric: str | None = None) -> RankingResult:
    """Also serves identify_underperformers: pass ascending=True to see
    the worst performers first instead of the best."""
    df = client.ranking(domain, metric, entity_type, days, limit, ascending, min_volume_metric)
    # Resolve names in one extra lookup rather than joining in SQL, since
    # ranking queries are already grouped by ID and label duplication in
    # a GROUP BY would be wasteful for large entity counts.
    names_df = client.entity_list(domain, entity_type)
    id_to_name = dict(zip(names_df["entity_id"], names_df["name"]))

    results = [
        RankedEntityItem(
            entity_id=int(row["entity_id"]), name=id_to_name.get(int(row["entity_id"]), "unknown"),
            value=row.get("value"), volume=row.get("volume") if min_volume_metric else None,
        )
        for _, row in df.iterrows()
    ]
    return RankingResult(domain=domain, metric=metric, entity_type=entity_type, days=days, results=results)


# ---------------------------------------------------------------------
# 7-8: Trend & anomaly intelligence (Phase 2's algorithms, made generic)
# ---------------------------------------------------------------------
def analyze_trend(client: AnalyticsClient, domain: str, metric: str, days: int = 30,
                   entity_type: str | None = None, entity_id: int | None = None) -> TrendSummary:
    df = client.timeseries(domain, metric, days, entity_type, entity_id, grain="day")
    if len(df) < 4:
        raise ValueError(f"Not enough data ({len(df)} days) for a meaningful trend over {days}-day window")

    # Reuse Phase 2's tested algorithm - rename columns to match its
    # expected shape rather than duplicating the split-half + slope logic.
    renamed = df.rename(columns={"period": "event_date", "value": "metric_value"})
    result = _analyze_trend_algo(renamed, "metric_value")

    return TrendSummary(domain=domain, metric=metric, entity_type=entity_type, entity_id=entity_id,
                         direction=result.direction, pct_change=result.pct_change,
                         first_half_avg=result.first_half_avg, second_half_avg=result.second_half_avg)


def detect_anomalies(client: AnalyticsClient, domain: str, metric: str, days: int = 30,
                      entity_type: str | None = None, entity_id: int | None = None,
                      sensitivity: str = "normal") -> AnomalyReport:
    """sensitivity="normal" (z>=3.0) is the recommended default - z=2.0
    ("high") produces meaningful false-positive noise, verified empirically
    in Phase 2's evaluation."""
    z_threshold = 2.0 if sensitivity == "high" else 3.0
    df = client.timeseries(domain, metric, days, entity_type, entity_id, grain="day")
    if len(df) < 10:
        raise ValueError(f"Not enough data ({len(df)} days) for reliable anomaly detection")

    renamed = df.rename(columns={"period": "event_date", "value": "metric_value"})
    anomalies = _detect_anomalies_algo(renamed, "metric_value", window=7, z_threshold=z_threshold)

    return AnomalyReport(
        domain=domain, metric=metric, entity_type=entity_type, entity_id=entity_id,
        sensitivity=sensitivity, anomalies_found=len(anomalies),
        anomalies=[AnomalyItem(date=str(a.date.date()) if hasattr(a.date, "date") else str(a.date),
                                actual=a.actual_value, expected=a.expected_value,
                                z_score=a.z_score, severity=a.severity)
                   for a in anomalies],
    )


# ---------------------------------------------------------------------
# 9: Diagnosis - the highest-value tool
# ---------------------------------------------------------------------
def explain_metric_change(client: AnalyticsClient, domain: str, metric: str, days: int = 14,
                           entity_type: str | None = None, entity_id: int | None = None,
                           top_n: int = 5) -> MetricChangeExplanation:
    """Compares the current half of `days` to the previous half, and - if
    a child dimension exists for the given entity_type (or a sensible
    domain default when none is given) - breaks the change down to find
    which specific children moved the most, ranked by absolute change in
    value rather than percentage (a 200% swing on 2 units is noise; a 10%
    swing on 2 million units is the real story - the same volume-awareness
    principle from the reporting_standards.md knowledge base doc)."""
    half = max(1, days // 2)
    current = client.period_aggregate(domain, [metric], start_days_ago=half, end_days_ago=0,
                                       entity_type=entity_type, entity_id=entity_id)
    previous = client.period_aggregate(domain, [metric], start_days_ago=half * 2, end_days_ago=half,
                                        entity_type=entity_type, entity_id=entity_id)
    current_val, previous_val = current.get(metric), previous.get(metric)
    pct = _pct_change(current_val, previous_val)
    direction = _classify_direction(pct)

    child_type = (_CHILD_ENTITY.get((domain, entity_type)) if entity_type
                  else _DEFAULT_BREAKDOWN.get(domain))

    contributors: list[Contributor] = []
    note = ("No further breakdown available for this entity type - this is the most granular "
            "level in the current schema.")
    if child_type:
        current_children = client.child_breakdown(domain, metric, child_type, half, 0,
                                                    entity_type, entity_id)
        previous_children = client.child_breakdown(domain, metric, child_type, half * 2, half,
                                                     entity_type, entity_id)
        merged = current_children.merge(
            previous_children, on="entity_id", how="outer", suffixes=("_cur", "_prev")
        )
        merged["name"] = merged["name_cur"].fillna(merged.get("name_prev"))
        merged["value_cur"] = merged["value_cur"].fillna(0)
        merged["value_prev"] = merged["value_prev"].fillna(0)
        merged["delta"] = merged["value_cur"] - merged["value_prev"]
        merged["abs_delta"] = merged["delta"].abs()
        top = merged.sort_values("abs_delta", ascending=False).head(top_n)

        contributors = [
            Contributor(
                entity_id=int(row["entity_id"]), name=str(row["name"]),
                current_value=float(row["value_cur"]), previous_value=float(row["value_prev"]),
                pct_change=_pct_change(row["value_cur"], row["value_prev"]),
                delta=round(float(row["delta"]), 4),
            )
            for _, row in top.iterrows()
        ]
        note = (f"Breakdown by {child_type}, ranked by absolute change (not percentage) - "
                f"a large percentage swing on tiny volume is not meaningful. Verify the "
                f"underlying volume with calculate_kpi before treating a small contributor "
                f"as the real driver.")

    return MetricChangeExplanation(
        domain=domain, metric=metric, entity_type=entity_type, entity_id=entity_id,
        current_value=current_val, previous_value=previous_val, pct_change=pct, direction=direction,
        breakdown_dimension=child_type, top_contributors=contributors, note=note,
    )


# ---------------------------------------------------------------------
# 10: RAG (reused as-is from Phase 3 - included here for a single import point)
# ---------------------------------------------------------------------
def search_knowledge_base(kb: "KnowledgeBaseStore", query: str, top_k: int = 3) -> dict:
    # Lazy import: chromadb + sentence-transformers are a heavy dependency
    # that the other 9 (pure-analytics) tools have no reason to pay for on
    # every import of this module. The type hint stays valid for IDEs via
    # TYPE_CHECKING below without forcing the import at module load time.
    chunks = kb.query(query, n_results=top_k)
    return {
        "found": bool(chunks),
        "results": [{"source": c.source, "similarity": round(c.similarity, 3), "text": c.text}
                    for c in chunks],
    }
