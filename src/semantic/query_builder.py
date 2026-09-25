"""
Entity registry + query builder - EXCHANGE domain only, ClickHouse dialect.

Turns (metric, entity_type, entity_id, date_range, grain) into governed
ClickHouse SQL. Every exchange tool goes through here - no tool writes its
own SQL, and there is deliberately no execute_sql tool, so the LLM can
never emit arbitrary queries against production data.

The Revive domain has its own MySQL-dialect equivalent of this module -
see mysql_query_builder.py - since it now queries a real local Revive
Adserver MySQL database instead of ClickHouse.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.semantic.metric_registry import EXCHANGE, MetricDef, get_metric


@dataclass(frozen=True, slots=True)
class EntityDef:
    name: str
    domain: str
    filter_column: str        # column to filter on, fully qualified after joins
    group_column: str          # column to GROUP BY when ranking/breaking down
    label_column: str          # human-readable name, for list_* tools
    label_table: str           # dimension table holding the label
    label_id_column: str
    joins: tuple[str, ...] = ()  # extra JOIN clauses needed to reach this entity


# ---------------------------------------------------------------------------
# Exchange entities. All four IDs live directly on ax_hourly_stats - no joins.
# ---------------------------------------------------------------------------
_EXCHANGE_ENTITIES = [
    EntityDef(name="supply_partner", domain=EXCHANGE, filter_column="f.supply_partner_id",
              group_column="f.supply_partner_id", label_column="partner_name",
              label_table="adexchange.ax_supply_partners", label_id_column="supply_partner_id"),
    EntityDef(name="ad_unit", domain=EXCHANGE, filter_column="f.ad_unit_id",
              group_column="f.ad_unit_id", label_column="ad_unit_name",
              label_table="adexchange.ax_ad_units", label_id_column="ad_unit_id"),
    EntityDef(name="demand_partner", domain=EXCHANGE, filter_column="f.demand_partner_id",
              group_column="f.demand_partner_id", label_column="partner_name",
              label_table="adexchange.ax_demand_partners", label_id_column="demand_partner_id"),
    EntityDef(name="dsp_campaign", domain=EXCHANGE, filter_column="f.campaign_id",
              group_column="f.campaign_id", label_column="campaign_name",
              label_table="adexchange.ax_dsp_campaigns", label_id_column="campaign_id"),
]

ENTITIES: dict[str, EntityDef] = {f"{e.domain}.{e.name}": e for e in _EXCHANGE_ENTITIES}

FACT_TABLES = {
    EXCHANGE: ("adexchange.ax_hourly_stats", "hour"),
}

GRAINS = {"hour": "toStartOfHour", "day": "toDate", "week": "toStartOfWeek", "month": "toStartOfMonth"}


def get_entity(domain: str, name: str) -> EntityDef:
    entity = ENTITIES.get(f"{domain}.{name}")
    if entity is None:
        available = sorted(e.name for e in ENTITIES.values() if e.domain == domain)
        raise ValueError(
            f"Unknown entity type {name!r} for domain {domain!r}. Available: {', '.join(available)}"
        )
    return entity


def list_entity_types(domain: str) -> list[str]:
    return sorted(e.name for e in ENTITIES.values() if e.domain == domain)


def _resolve_joins(entity: EntityDef | None, metric_domain: str) -> str:
    if entity is None or not entity.joins:
        return ""
    return " " + " ".join(entity.joins)


def build_timeseries_query(
    domain: str, metric_name: str, days: int,
    entity_type: str | None = None, grain: str = "day",
) -> tuple[str, dict]:
    """One metric over time, optionally scoped to a single entity.

    Returns (sql, params). Parameters are bound by clickhouse-connect rather
    than string-formatted, so entity_id can never carry injected SQL.
    """
    metric = get_metric(domain, metric_name)
    if grain not in GRAINS:
        raise ValueError(f"Unknown grain {grain!r}. Available: {', '.join(GRAINS)}")

    fact_table, time_col = FACT_TABLES[domain]
    entity = get_entity(domain, entity_type) if entity_type else None
    joins = _resolve_joins(entity, domain)

    where = [f"f.{time_col} >= now() - INTERVAL {{days:UInt32}} DAY"]
    params: dict = {"days": days}
    if entity is not None:
        where.append(f"{entity.filter_column} = {{entity_id:UInt32}}")

    sql = (
        f"SELECT {GRAINS[grain]}(f.{time_col}) AS period, "
        f"{metric.sql_expression()} AS value "
        f"FROM {fact_table} f{joins} "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY period ORDER BY period"
    )
    return sql, params


def build_aggregate_query(
    domain: str, metric_names: list[str], days: int,
    entity_type: str | None = None, offset_days: int = 0,
) -> tuple[str, dict]:
    """Several metrics as single totals over a window.

    offset_days shifts the whole window back in time - offset_days=0 is
    "the last `days` days"; offset_days=7 with days=7 is "the 7 days
    before that" - this is what compare_periods uses to get two
    non-overlapping windows without two different code paths.
    """
    metrics = [get_metric(domain, n) for n in metric_names]
    fact_table, time_col = FACT_TABLES[domain]
    entity = get_entity(domain, entity_type) if entity_type else None
    joins = _resolve_joins(entity, domain)

    where = [f"f.{time_col} >= now() - INTERVAL {{start_days:UInt32}} DAY",
             f"f.{time_col} < now() - INTERVAL {{end_days:UInt32}} DAY"]
    params: dict = {"start_days": days + offset_days, "end_days": offset_days}
    if entity is not None:
        where.append(f"{entity.filter_column} = {{entity_id:UInt32}}")

    selects = ", ".join(f"{m.sql_expression()} AS {m.name}" for m in metrics)
    sql = f"SELECT {selects} FROM {fact_table} f{joins} WHERE {' AND '.join(where)}"
    return sql, params


def build_ranking_query(
    domain: str, metric_name: str, entity_type: str, days: int,
    limit: int = 10, ascending: bool = False, min_volume_metric: str | None = None,
) -> tuple[str, dict]:
    """Rank entities by a metric - powers rank_entities and
    identify_underperformers from one implementation.

    min_volume_metric guards against the classic ranking trap: an entity
    with 3 impressions and 1 click shows a 33% CTR and tops the list.
    Passing e.g. "impressions" adds that volume to the output so the caller
    (and the LLM) can see whether a rank is statistically meaningful.
    """
    metric = get_metric(domain, metric_name)
    entity = get_entity(domain, entity_type)
    fact_table, time_col = FACT_TABLES[domain]
    joins = _resolve_joins(entity, domain)

    selects = [f"{entity.group_column} AS entity_id", f"{metric.sql_expression()} AS value"]
    if min_volume_metric:
        volume = get_metric(domain, min_volume_metric)
        selects.append(f"{volume.sql_expression()} AS volume")

    sql = (
        f"SELECT {', '.join(selects)} "
        f"FROM {fact_table} f{joins} "
        f"WHERE f.{time_col} >= now() - INTERVAL {{days:UInt32}} DAY "
        f"GROUP BY entity_id "
        f"HAVING value IS NOT NULL "
        f"ORDER BY value {'ASC' if ascending else 'DESC'} "
        f"LIMIT {{limit:UInt32}}"
    )
    return sql, {"days": days, "limit": limit}


def build_entity_list_query(domain: str, entity_type: str) -> str:
    """Names and IDs for an entity type, so the LLM can resolve a name
    mentioned in a question to the ID the other tools need."""
    entity = get_entity(domain, entity_type)
    return (
        f"SELECT {entity.label_id_column} AS entity_id, {entity.label_column} AS name "
        f"FROM {entity.label_table} ORDER BY entity_id"
    )


def build_period_aggregate_query(
    domain: str, metric_names: list[str], start_days_ago: int, end_days_ago: int,
    entity_type: str | None = None,
) -> tuple[str, dict]:
    """Aggregate metrics over a specific past window: [now - start_days_ago,
    now - end_days_ago). Used to compute "this period vs the one before it"
    without re-querying from "now" each time - compare_periods and
    explain_metric_change both need two DIFFERENT non-overlapping windows,
    which build_aggregate_query (always trailing from now) can't express.
    """
    if start_days_ago <= end_days_ago:
        raise ValueError(f"start_days_ago ({start_days_ago}) must be > end_days_ago ({end_days_ago})")

    metrics = [get_metric(domain, n) for n in metric_names]
    fact_table, time_col = FACT_TABLES[domain]
    entity = get_entity(domain, entity_type) if entity_type else None
    joins = _resolve_joins(entity, domain)

    where = [
        f"f.{time_col} >= now() - INTERVAL {{start_days:UInt32}} DAY",
        f"f.{time_col} < now() - INTERVAL {{end_days:UInt32}} DAY",
    ]
    params: dict = {"start_days": start_days_ago, "end_days": end_days_ago}
    if entity is not None:
        where.append(f"{entity.filter_column} = {{entity_id:UInt32}}")

    selects = ", ".join(f"{m.sql_expression()} AS {m.name}" for m in metrics)
    sql = f"SELECT {selects} FROM {fact_table} f{joins} WHERE {' AND '.join(where)}"
    return sql, params


def build_child_breakdown_query(
    domain: str, metric_name: str, child_entity_type: str,
    start_days_ago: int, end_days_ago: int,
    parent_entity_type: str | None = None, limit: int = 8,
) -> tuple[str, dict]:
    """Metric broken down by a child entity (e.g. campaigns within a
    client), for one time window, optionally scoped to a parent entity.
    Powers explain_metric_change's drill-down: which specific children
    moved the most, not just "the total changed X%".

    Joins from BOTH the parent (for filtering) and the child (for the
    GROUP BY / label) are combined and de-duplicated, since e.g. filtering
    by client and grouping by campaign in Revive both need the banner join.
    """
    metric = get_metric(domain, metric_name)
    child = get_entity(domain, child_entity_type)
    parent = get_entity(domain, parent_entity_type) if parent_entity_type else None
    fact_table, time_col = FACT_TABLES[domain]

    # De-duplicate while preserving order - a join clause needed by both
    # parent and child must only be written once.
    all_joins = list(dict.fromkeys((parent.joins if parent else ()) + child.joins))

    # If the child's label table is ALREADY present (e.g. filtering by
    # client already joins rv_campaigns for the parent filter, and the
    # child breakdown is also campaigns), reuse that join instead of
    # joining the same table a second time under a different alias -
    # a real duplicate-join bug caught by verify_semantic_layer.py.
    label_already_joined = any(child.label_table in j for j in all_joins)
    join_sql = "" if not all_joins else " " + " ".join(all_joins)
    if not label_already_joined:
        join_sql += f" LEFT JOIN {child.label_table} lbl ON lbl.{child.label_id_column} = {child.group_column}"

    where = [
        f"f.{time_col} >= now() - INTERVAL {{start_days:UInt32}} DAY",
        f"f.{time_col} < now() - INTERVAL {{end_days:UInt32}} DAY",
    ]
    params: dict = {"start_days": start_days_ago, "end_days": end_days_ago, "limit": limit}
    if parent is not None:
        where.append(f"{parent.filter_column} = {{entity_id:UInt32}}")

    sql = (
        f"SELECT {child.group_column} AS entity_id, "
        f"any({child.label_column}) AS name, "
        f"{metric.sql_expression()} AS value "
        f"FROM {fact_table} f{join_sql} "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY entity_id "
        f"ORDER BY entity_id "
        f"LIMIT {{limit:UInt32}}"
    )
    return sql, params
