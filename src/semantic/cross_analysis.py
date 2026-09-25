"""
Cross-dimension analysis - genuinely different query shape from
query_builder.py's core design (which assumes ONE entity_type/entity_id
per query). These tools GROUP BY two dimensions at once:
  - Revive: which zones does a banner run in (or vice versa)?
  - Exchange: how does a demand partner perform across different supply
    partners (or vice versa)?

Kept in their own module for the same reason realtime_exchange.py is
separate: forcing a two-dimension breakdown into the single-entity
registry would complicate the common case to serve this less common one.
Both still go through the metric registry for the actual metric math, so
there's no duplicated formula logic - only the grouping shape is new.
"""
from __future__ import annotations

from pydantic import BaseModel

from src.semantic.analytics_client import AnalyticsClient
from src.semantic.metric_registry import EXCHANGE, REVIVE, get_metric
from src.semantic.mysql_query_builder import apply_scope


# ---------------------------------------------------------------------
# Revive: banner <-> zone linking
# ---------------------------------------------------------------------
class BannerZonePair(BaseModel):
    banner_id: int
    banner_name: str
    zone_id: int
    zone_name: str
    impressions: int
    clicks: int
    ctr: float


class BannerZoneMapping(BaseModel):
    banner_id: int | None
    zone_id: int | None
    days: int
    pairs: list[BannerZonePair]


def build_banner_zone_mapping_query(banner_id: int | None, zone_id: int | None,
                                     days: int, limit: int = 50,
                                     agency_id: int | None = None) -> tuple[str, dict]:
    # banner_id and zone_id are both optional: omitting both returns the top
    # `limit` banner-zone pairs account-wide, ordered by impressions - the
    # query is already bounded by LIMIT regardless of which filters are
    # present, so there's no unbounded-scan risk in leaving both off.
    impressions = get_metric(REVIVE, "impressions")
    clicks = get_metric(REVIVE, "clicks")
    ctr = get_metric(REVIVE, "ctr")

    where = ["f.date_time >= UTC_TIMESTAMP() - INTERVAL :days DAY"]
    params: dict = {"days": days, "limit": limit}
    if banner_id is not None:
        where.append("f.ad_id = :banner_id")
        params["banner_id"] = banner_id
    if zone_id is not None:
        where.append("f.zone_id = :zone_id")
        params["zone_id"] = zone_id
    apply_scope(where, params, agency_id)

    sql = (
        f"SELECT f.ad_id AS banner_id, b.description AS banner_name, "
        f"f.zone_id AS zone_id, z.zonename AS zone_name, "
        f"{impressions.sql_expression()} AS impressions, "
        f"{clicks.sql_expression()} AS clicks, "
        f"{ctr.sql_expression()} AS ctr "
        f"FROM rv_data_summary_ad_hourly f "
        f"LEFT JOIN rv_banners b ON b.bannerid = f.ad_id "
        f"LEFT JOIN rv_zones z ON z.zoneid = f.zone_id "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY f.ad_id, b.description, f.zone_id, z.zonename "
        f"HAVING impressions > 0 "
        f"ORDER BY impressions DESC LIMIT :limit"
    )
    return sql, params


def get_banner_zone_mapping(client: AnalyticsClient, banner_id: int | None = None,
                             zone_id: int | None = None, days: int = 30) -> BannerZoneMapping:
    """[Revive] Shows which zones a banner runs in, or which banners run in
    a zone (use list_entities first to resolve a name to an ID). Provide
    banner_id OR zone_id to scope to one entity; provide neither to get an
    account-wide overview of the top banner-zone pairs by impression volume
    (bounded to 50 rows) - use that instead of calling this once per banner
    or zone when the question is about the full mapping. Returns
    impressions/clicks/CTR per banner-zone pair."""
    sql, params = build_banner_zone_mapping_query(banner_id, zone_id, days, agency_id=client.agency_id)
    df = client.raw_query(sql, params, domain=REVIVE)
    pairs = [
        BannerZonePair(banner_id=int(r["banner_id"]), banner_name=str(r["banner_name"]),
                       zone_id=int(r["zone_id"]), zone_name=str(r["zone_name"]),
                       impressions=int(r["impressions"]), clicks=int(r["clicks"]),
                       ctr=float(r["ctr"]))
        for _, r in df.iterrows()
    ]
    return BannerZoneMapping(banner_id=banner_id, zone_id=zone_id, days=days, pairs=pairs)


# ---------------------------------------------------------------------
# Exchange: supply partner <-> demand partner cross-analysis
# ---------------------------------------------------------------------
class SupplyDemandPair(BaseModel):
    supply_partner_id: int
    supply_partner_name: str
    demand_partner_id: int
    demand_partner_name: str
    value: float
    bid_requests: int


class SupplyDemandCrossAnalysis(BaseModel):
    metric: str
    supply_partner_id: int | None
    demand_partner_id: int | None
    days: int
    pairs: list[SupplyDemandPair]


def build_supply_demand_cross_query(metric_name: str, supply_partner_id: int | None,
                                     demand_partner_id: int | None, days: int,
                                     limit: int = 50) -> tuple[str, dict]:
    if supply_partner_id is None and demand_partner_id is None:
        raise ValueError(
            "Provide at least one of supply_partner_id or demand_partner_id - without "
            "either, this returns every supply-demand pair in the account. Use "
            "list_entities(domain='exchange', entity_type='supply_partner' or "
            "'demand_partner') first to find an ID."
        )

    metric = get_metric(EXCHANGE, metric_name)
    volume = get_metric(EXCHANGE, "bid_requests")

    where = ["f.hour >= now() - INTERVAL {days:UInt32} DAY"]
    params: dict = {"days": days, "limit": limit}
    if supply_partner_id is not None:
        where.append("f.supply_partner_id = {supply_partner_id:UInt32}")
        params["supply_partner_id"] = supply_partner_id
    if demand_partner_id is not None:
        where.append("f.demand_partner_id = {demand_partner_id:UInt32}")
        params["demand_partner_id"] = demand_partner_id

    sql = (
        f"SELECT f.supply_partner_id AS supply_partner_id, sp.partner_name AS supply_partner_name, "
        f"f.demand_partner_id AS demand_partner_id, dp.partner_name AS demand_partner_name, "
        f"{metric.sql_expression()} AS value, "
        f"{volume.sql_expression()} AS bid_requests "
        f"FROM adexchange.ax_hourly_stats f "
        f"LEFT JOIN adexchange.ax_supply_partners sp ON sp.supply_partner_id = f.supply_partner_id "
        f"LEFT JOIN adexchange.ax_demand_partners dp ON dp.demand_partner_id = f.demand_partner_id "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY f.supply_partner_id, sp.partner_name, f.demand_partner_id, dp.partner_name "
        f"HAVING bid_requests > 0 "
        f"ORDER BY bid_requests DESC LIMIT {{limit:UInt32}}"
    )
    return sql, params


def get_supply_demand_cross_analysis(
    client: AnalyticsClient, metric: str = "win_rate",
    supply_partner_id: int | None = None, demand_partner_id: int | None = None,
    days: int = 30,
) -> SupplyDemandCrossAnalysis:
    """[Exchange] Cross-tabulates a metric by BOTH supply and demand
    partner at once - e.g. 'how does DSP X perform across different
    SSPs' or 'which DSPs perform best on supply partner Y'. Provide
    exactly one of supply_partner_id/demand_partner_id to fix that side
    and see how it varies across the other. Use list_available_metrics
    or get_metric_definition to confirm the metric name first."""
    sql, params = build_supply_demand_cross_query(metric, supply_partner_id, demand_partner_id, days)
    df = client.raw_query(sql, params, domain=EXCHANGE)
    pairs = [
        SupplyDemandPair(
            supply_partner_id=int(r["supply_partner_id"]), supply_partner_name=str(r["supply_partner_name"]),
            demand_partner_id=int(r["demand_partner_id"]), demand_partner_name=str(r["demand_partner_name"]),
            value=float(r["value"]), bid_requests=int(r["bid_requests"]),
        )
        for _, r in df.iterrows()
    ]
    return SupplyDemandCrossAnalysis(metric=metric, supply_partner_id=supply_partner_id,
                                      demand_partner_id=demand_partner_id, days=days, pairs=pairs)
