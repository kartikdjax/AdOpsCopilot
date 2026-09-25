"""
MySQL-dialect entity registry + query builder for the Revive domain only.

Mirrors query_builder.py's shape (EntityDef, an entity registry, a fact
table constant, GRAINS, and one build_*_query function per AnalyticsClient
method) but targets the real local Revive Adserver MySQL database instead
of ClickHouse: SQLAlchemy :name bound params instead of {name:UInt32},
UTC_TIMESTAMP() - INTERVAL instead of now() - INTERVAL (Revive stores
times in UTC, and NOW() follows the server's own time zone), MySQL date-truncation
expressions instead of toStartOfHour/toDate/etc, and ANY_VALUE(...)
instead of ClickHouse's any(...). The exchange domain is untouched and
still goes through query_builder.py + ClickHouse.

Revive's fact table (rv_data_summary_ad_hourly) only has ad_id + zone_id,
so campaign- and client-level questions walk up rv_banners -> rv_campaigns,
and website/manager questions walk up rv_zones -> rv_affiliates - same join
logic as query_builder.py,
just unqualified table names since
this connects directly to the single `revive608` database (no
revive.xxx/adexchange.xxx cross-database qualification needed).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.semantic.metric_registry import REVIVE, get_metric


@dataclass(frozen=True, slots=True)
class EntityDef:
    name: str
    filter_column: str        # column to filter on, fully qualified after joins
    group_column: str          # column to GROUP BY when ranking/breaking down
    label_column: str          # human-readable name, for list_* tools
    label_table: str           # dimension table holding the label
    label_id_column: str
    joins: tuple[str, ...] = ()  # extra JOIN clauses needed to reach this entity
    # For list_entities' parent filter: the parent entity type and the column
    # on THIS entity's label_table that holds the parent's ID.
    parent: tuple[str, str] | None = None


_BANNER_JOIN = "LEFT JOIN rv_banners b ON b.bannerid = f.ad_id"
_CAMPAIGN_JOIN = "LEFT JOIN rv_campaigns c ON c.campaignid = b.campaignid"
_ZONE_JOIN = "LEFT JOIN rv_zones z ON z.zoneid = f.zone_id"
_AFFILIATE_JOIN = "LEFT JOIN rv_affiliates a ON a.affiliateid = z.affiliateid"

# A manager (rv_agency) owns both advertisers and websites, and Revive only
# links a manager's banners to that same manager's zones - so the website
# side (2 joins) and the advertiser side (3 joins) always name the same
# manager. The shorter website path is used.
_ENTITIES = [
    EntityDef(name="zone", filter_column="f.zone_id", group_column="f.zone_id",
              label_column="zonename", label_table="rv_zones", label_id_column="zoneid",
              parent=("affiliate", "affiliateid")),
    EntityDef(name="banner", filter_column="f.ad_id", group_column="f.ad_id",
              label_column="description", label_table="rv_banners", label_id_column="bannerid",
              parent=("campaign", "campaignid")),
    EntityDef(name="campaign", filter_column="b.campaignid", group_column="b.campaignid",
              label_column="campaignname", label_table="rv_campaigns",
              label_id_column="campaignid", joins=(_BANNER_JOIN,),
              parent=("client", "clientid")),
    EntityDef(name="client", filter_column="c.clientid", group_column="c.clientid",
              label_column="clientname", label_table="rv_clients",
              label_id_column="clientid", joins=(_BANNER_JOIN, _CAMPAIGN_JOIN),
              parent=("manager", "agencyid")),
    EntityDef(name="affiliate", filter_column="z.affiliateid", group_column="z.affiliateid",
              label_column="name", label_table="rv_affiliates",
              label_id_column="affiliateid", joins=(_ZONE_JOIN,),
              parent=("manager", "agencyid")),
    EntityDef(name="manager", filter_column="a.agencyid", group_column="a.agencyid",
              label_column="name", label_table="rv_agency", label_id_column="agencyid",
              joins=(_ZONE_JOIN, _AFFILIATE_JOIN)),
]

ENTITY_REGISTRY: dict[str, EntityDef] = {e.name: e for e in _ENTITIES}

# ---------------------------------------------------------------------------
# Manager scoping. Every builder takes agency_id: None = admin (everything),
# an int = only what that manager (rv_agency) owns. It's bound as
# :scope_agency_id by the builder itself - callers never write this SQL.
# ---------------------------------------------------------------------------
OWNED_IDS: dict[str, str] = {
    "zone": ("SELECT oz.zoneid FROM rv_zones oz JOIN rv_affiliates oa ON oa.affiliateid = oz.affiliateid "
             "WHERE oa.agencyid = :scope_agency_id"),
    "banner": ("SELECT ob.bannerid FROM rv_banners ob JOIN rv_campaigns oc ON oc.campaignid = ob.campaignid "
               "JOIN rv_clients ocl ON ocl.clientid = oc.clientid WHERE ocl.agencyid = :scope_agency_id"),
    "campaign": ("SELECT oc.campaignid FROM rv_campaigns oc JOIN rv_clients ocl ON ocl.clientid = oc.clientid "
                 "WHERE ocl.agencyid = :scope_agency_id"),
    "client": "SELECT clientid FROM rv_clients WHERE agencyid = :scope_agency_id",
    "affiliate": "SELECT affiliateid FROM rv_affiliates WHERE agencyid = :scope_agency_id",
    "manager": "SELECT :scope_agency_id",
}
# Login accounts belonging to the manager: its own, its advertisers', its websites'.
OWNED_ACCOUNTS = (
    "SELECT account_id FROM rv_agency WHERE agencyid = :scope_agency_id "
    "UNION SELECT account_id FROM rv_clients WHERE agencyid = :scope_agency_id "
    "UNION SELECT account_id FROM rv_affiliates WHERE agencyid = :scope_agency_id"
)
OWNED_IDS["user"] = (f"SELECT aua.user_id FROM rv_account_user_assoc aua "
                     f"WHERE aua.account_id IN ({OWNED_ACCOUNTS})")

# Revive only links a manager's banners to that manager's own zones, so
# filtering delivery rows by zone scopes every stats query completely.
_SCOPE_FACT = f"f.zone_id IN ({OWNED_IDS['zone']})"


def apply_scope(where: list[str], params: dict, agency_id: int | None, condition: str = _SCOPE_FACT) -> None:
    """Adds the manager filter to a WHERE list in place. No-op for admins."""
    if agency_id is not None:
        where.append(condition)
        params["scope_agency_id"] = agency_id

FACT_TABLE = ("rv_data_summary_ad_hourly", "date_time")

# MySQL date-truncation equivalents of ClickHouse's toStartOfHour/toDate/
# toStartOfWeek/toStartOfMonth. Each takes the (already-aliased) column
# expression and returns the grouped period expression.
GRAINS: dict[str, Callable[[str], str]] = {
    "hour": lambda col: f"DATE_FORMAT({col}, '%Y-%m-%d %H:00:00')",
    "day": lambda col: f"DATE({col})",
    "week": lambda col: f"DATE_SUB(DATE({col}), INTERVAL WEEKDAY({col}) DAY)",
    "month": lambda col: f"DATE_FORMAT({col}, '%Y-%m-01')",
}


def get_entity(name: str) -> EntityDef:
    entity = ENTITY_REGISTRY.get(name)
    if entity is None:
        available = ", ".join(sorted(ENTITY_REGISTRY))
        raise ValueError(f"Unknown revive entity type {name!r}. Available: {available}")
    return entity


def list_entity_types() -> list[str]:
    return sorted(ENTITY_REGISTRY)


def _resolve_joins(entity: EntityDef | None) -> str:
    if entity is None or not entity.joins:
        return ""
    return " " + " ".join(entity.joins)


def build_timeseries_query(metric_name: str, days: int, entity_type: str | None = None,
                            grain: str = "day", agency_id: int | None = None) -> tuple[str, dict]:
    """One metric over time, optionally scoped to a single entity.

    Returns (sql, params). Parameters are bound by SQLAlchemy's :name
    style rather than string-formatted, so entity_id can never carry
    injected SQL.
    """
    metric = get_metric(REVIVE, metric_name)
    if grain not in GRAINS:
        raise ValueError(f"Unknown grain {grain!r}. Available: {', '.join(GRAINS)}")

    fact_table, time_col = FACT_TABLE
    entity = get_entity(entity_type) if entity_type else None
    joins = _resolve_joins(entity)

    where = [f"f.{time_col} >= UTC_TIMESTAMP() - INTERVAL :days DAY"]
    params: dict = {"days": days}
    if entity is not None:
        where.append(f"{entity.filter_column} = :entity_id")
    apply_scope(where, params, agency_id)

    period_expr = GRAINS[grain](f"f.{time_col}")
    sql = (
        f"SELECT {period_expr} AS period, "
        f"{metric.sql_expression()} AS value "
        f"FROM {fact_table} f{joins} "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY period ORDER BY period"
    )
    return sql, params


def build_aggregate_query(metric_names: list[str], days: int, entity_type: str | None = None,
                           offset_days: int = 0, agency_id: int | None = None) -> tuple[str, dict]:
    """Several metrics as single totals over a window. See
    query_builder.build_aggregate_query for the offset_days semantics."""
    metrics = [get_metric(REVIVE, n) for n in metric_names]
    fact_table, time_col = FACT_TABLE
    entity = get_entity(entity_type) if entity_type else None
    joins = _resolve_joins(entity)

    where = [f"f.{time_col} >= UTC_TIMESTAMP() - INTERVAL :start_days DAY",
             f"f.{time_col} < UTC_TIMESTAMP() - INTERVAL :end_days DAY"]
    params: dict = {"start_days": days + offset_days, "end_days": offset_days}
    if entity is not None:
        where.append(f"{entity.filter_column} = :entity_id")
    apply_scope(where, params, agency_id)

    selects = ", ".join(f"{m.sql_expression()} AS {m.name}" for m in metrics)
    sql = f"SELECT {selects} FROM {fact_table} f{joins} WHERE {' AND '.join(where)}"
    return sql, params


def build_period_aggregate_query(metric_names: list[str], start_days_ago: int, end_days_ago: int,
                                  entity_type: str | None = None,
                                  agency_id: int | None = None) -> tuple[str, dict]:
    """Aggregate metrics over [now - start_days_ago, now - end_days_ago).
    See query_builder.build_period_aggregate_query for why this differs
    from build_aggregate_query."""
    if start_days_ago <= end_days_ago:
        raise ValueError(f"start_days_ago ({start_days_ago}) must be > end_days_ago ({end_days_ago})")

    metrics = [get_metric(REVIVE, n) for n in metric_names]
    fact_table, time_col = FACT_TABLE
    entity = get_entity(entity_type) if entity_type else None
    joins = _resolve_joins(entity)

    where = [
        f"f.{time_col} >= UTC_TIMESTAMP() - INTERVAL :start_days DAY",
        f"f.{time_col} < UTC_TIMESTAMP() - INTERVAL :end_days DAY",
    ]
    params: dict = {"start_days": start_days_ago, "end_days": end_days_ago}
    if entity is not None:
        where.append(f"{entity.filter_column} = :entity_id")
    apply_scope(where, params, agency_id)

    selects = ", ".join(f"{m.sql_expression()} AS {m.name}" for m in metrics)
    sql = f"SELECT {selects} FROM {fact_table} f{joins} WHERE {' AND '.join(where)}"
    return sql, params


def build_ranking_query(metric_name: str, entity_type: str, days: int, limit: int = 10,
                         ascending: bool = False, min_volume_metric: str | None = None,
                         agency_id: int | None = None) -> tuple[str, dict]:
    """Rank entities by a metric. min_volume_metric guards against the
    classic ranking trap - see query_builder.build_ranking_query."""
    metric = get_metric(REVIVE, metric_name)
    entity = get_entity(entity_type)
    fact_table, time_col = FACT_TABLE
    joins = _resolve_joins(entity)

    selects = [f"{entity.group_column} AS entity_id", f"{metric.sql_expression()} AS value"]
    if min_volume_metric:
        volume = get_metric(REVIVE, min_volume_metric)
        selects.append(f"{volume.sql_expression()} AS volume")

    where = [f"f.{time_col} >= UTC_TIMESTAMP() - INTERVAL :days DAY"]
    params: dict = {"days": days, "limit": limit}
    apply_scope(where, params, agency_id)
    sql = (
        f"SELECT {', '.join(selects)} "
        f"FROM {fact_table} f{joins} "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY entity_id "
        f"HAVING value IS NOT NULL "
        f"ORDER BY value {'ASC' if ascending else 'DESC'} "
        f"LIMIT :limit"
    )
    return sql, params


def build_entity_list_query(entity_type: str, search: str | None = None,
                             parent_type: str | None = None,
                             limit: int | None = None, agency_id: int | None = None) -> tuple[str, dict]:
    """Names and IDs for an entity type, so the LLM can resolve a name
    mentioned in a question to the ID the other tools need. `search` is a
    case-insensitive substring match on the name; `parent_type` narrows to
    one parent's children (bind its ID as :parent_id, like :entity_id
    elsewhere) - only the entity's direct parent is supported."""
    entity = get_entity(entity_type)
    where: list[str] = []
    params: dict = {}
    if search:
        where.append(f"LOWER({entity.label_column}) LIKE :search")
        params["search"] = f"%{search.lower()}%"
    if parent_type:
        if entity.parent is None or entity.parent[0] != parent_type:
            allowed = entity.parent[0] if entity.parent else "none"
            raise ValueError(f"{entity_type!r} can't be filtered by parent {parent_type!r}. "
                             f"Allowed parent: {allowed}")
        where.append(f"{entity.parent[1]} = :parent_id")
    apply_scope(where, params, agency_id, f"{entity.label_id_column} IN ({OWNED_IDS[entity.name]})")

    sql = f"SELECT {entity.label_id_column} AS entity_id, {entity.label_column} AS name FROM {entity.label_table}"
    if where:
        sql += f" WHERE {' AND '.join(where)}"
    sql += " ORDER BY entity_id"
    if limit is not None:
        sql += " LIMIT :limit"
        params["limit"] = limit
    return sql, params


def build_child_breakdown_query(metric_name: str, child_entity_type: str, start_days_ago: int,
                                 end_days_ago: int, parent_entity_type: str | None = None,
                                 limit: int = 8, agency_id: int | None = None) -> tuple[str, dict]:
    """Metric broken down by a child entity for one time window, optionally
    scoped to a parent entity. See query_builder.build_child_breakdown_query
    for the join de-duplication rationale."""
    metric = get_metric(REVIVE, metric_name)
    child = get_entity(child_entity_type)
    parent = get_entity(parent_entity_type) if parent_entity_type else None
    fact_table, time_col = FACT_TABLE

    all_joins = list(dict.fromkeys((parent.joins if parent else ()) + child.joins))

    # The label table is always joined under its own alias, even when a
    # join path already reaches it: several label tables share a column
    # name (rv_affiliates.name, rv_agency.name), so an unqualified label
    # would be ambiguous. Joining on a primary key can't duplicate rows.
    join_sql = "" if not all_joins else " " + " ".join(all_joins)
    join_sql += f" LEFT JOIN {child.label_table} lbl ON lbl.{child.label_id_column} = {child.group_column}"

    where = [
        f"f.{time_col} >= UTC_TIMESTAMP() - INTERVAL :start_days DAY",
        f"f.{time_col} < UTC_TIMESTAMP() - INTERVAL :end_days DAY",
    ]
    params: dict = {"start_days": start_days_ago, "end_days": end_days_ago, "limit": limit}
    if parent is not None:
        where.append(f"{parent.filter_column} = :entity_id")
    apply_scope(where, params, agency_id)

    sql = (
        f"SELECT {child.group_column} AS entity_id, "
        f"ANY_VALUE(lbl.{child.label_column}) AS name, "
        f"{metric.sql_expression()} AS value "
        f"FROM {fact_table} f{join_sql} "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY entity_id "
        f"ORDER BY entity_id "
        f"LIMIT :limit"
    )
    return sql, params
