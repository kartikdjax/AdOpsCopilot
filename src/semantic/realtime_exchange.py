"""
Real-time exchange health - the one tool with no core-tool equivalent,
because it reads ax_bid_requests/ax_bid_responses (raw, per-auction)
rather than ax_hourly_stats (the metric registry's only Exchange source).

Kept deliberately separate from query_builder.py: that module's entire
design assumes one fact table per domain at a fixed grain. Raw auction
data is a genuinely different query shape (no GROUP BY period, optional
join from responses back to requests for ad_unit scoping), so bolting it
onto the registry would complicate the 90% case to serve this 10% one.
"""
from __future__ import annotations

from pydantic import BaseModel

from src.semantic.analytics_client import AnalyticsClient
from src.semantic.metric_registry import EXCHANGE


class RealtimeExchangeHealth(BaseModel):
    minutes: int
    ad_unit_id: int | None
    demand_partner_id: int | None
    bid_requests: int
    qps: float
    bid_responses: int
    bids: int
    timeouts: int
    bid_rate_pct: float | None
    timeout_rate_pct: float | None
    avg_latency_ms: float | None


def build_realtime_requests_query(minutes: int, ad_unit_id: int | None) -> tuple[str, dict]:
    where = ["request_time >= now() - INTERVAL {minutes:UInt32} MINUTE"]
    params: dict = {"minutes": minutes}
    if ad_unit_id is not None:
        where.append("ad_unit_id = {ad_unit_id:UInt32}")
        params["ad_unit_id"] = ad_unit_id
    sql = f"SELECT count() AS requests FROM adexchange.ax_bid_requests WHERE {' AND '.join(where)}"
    return sql, params


def build_realtime_responses_query(minutes: int, ad_unit_id: int | None,
                                    demand_partner_id: int | None) -> tuple[str, dict]:
    join = ""
    where = ["r.response_time >= now() - INTERVAL {minutes:UInt32} MINUTE"]
    params: dict = {"minutes": minutes}
    if ad_unit_id is not None:
        # Only join back to bid_requests when scoping by ad_unit - it's
        # not on the responses table directly, unlike demand_partner_id.
        join = " INNER JOIN adexchange.ax_bid_requests q ON q.request_id = r.request_id"
        where.append("q.ad_unit_id = {ad_unit_id:UInt32}")
        params["ad_unit_id"] = ad_unit_id
    if demand_partner_id is not None:
        where.append("r.demand_partner_id = {demand_partner_id:UInt32}")
        params["demand_partner_id"] = demand_partner_id

    sql = (
        f"SELECT count() AS responses, countIf(status='bid') AS bids, "
        f"countIf(status='timeout') AS timeouts, avg(latency_ms) AS avg_latency_ms "
        f"FROM adexchange.ax_bid_responses r{join} WHERE {' AND '.join(where)}"
    )
    return sql, params


def get_realtime_exchange_health(
    client: AnalyticsClient, minutes: int = 15,
    ad_unit_id: int | None = None, demand_partner_id: int | None = None,
) -> RealtimeExchangeHealth:
    """Live operational snapshot from RAW auction data - QPS, bid rate,
    timeout rate, latency - for the last N minutes. This is the "what's
    happening right now" tool; for trends over days/weeks use
    analyze_trend/detect_anomalies against the hourly-rollup metrics
    instead (raw auction data isn't retained long enough for that).

    Args:
        minutes: how far back to look. Keep this small (5-60) - raw
            tables have short retention in a real deployment.
        ad_unit_id: optional, scope to one piece of supply-side inventory.
        demand_partner_id: optional, scope to one DSP.
    """
    if minutes > 180:
        raise ValueError(
            f"minutes={minutes} is too large for a real-time tool - raw auction tables "
            f"have short retention in production; use the hourly-rollup tools "
            f"(analyze_trend, calculate_kpi) for anything beyond a few hours."
        )

    req_sql, req_params = build_realtime_requests_query(minutes, ad_unit_id)
    resp_sql, resp_params = build_realtime_responses_query(minutes, ad_unit_id, demand_partner_id)

    req_df = client.raw_query(req_sql, req_params, domain=EXCHANGE)
    resp_df = client.raw_query(resp_sql, resp_params, domain=EXCHANGE)

    bid_requests = int(req_df.iloc[0]["requests"]) if not req_df.empty else 0
    responses = int(resp_df.iloc[0]["responses"]) if not resp_df.empty else 0
    bids = int(resp_df.iloc[0]["bids"]) if not resp_df.empty else 0
    timeouts = int(resp_df.iloc[0]["timeouts"]) if not resp_df.empty else 0
    avg_latency = resp_df.iloc[0]["avg_latency_ms"] if not resp_df.empty else None

    qps = round(bid_requests / max(1, minutes * 60), 3)
    bid_rate = round(bids / responses * 100, 2) if responses else None
    timeout_rate = round(timeouts / bid_requests * 100, 2) if bid_requests else None

    return RealtimeExchangeHealth(
        minutes=minutes, ad_unit_id=ad_unit_id, demand_partner_id=demand_partner_id,
        bid_requests=bid_requests, qps=qps, bid_responses=responses, bids=bids, timeouts=timeouts,
        bid_rate_pct=bid_rate, timeout_rate_pct=timeout_rate,
        avg_latency_ms=round(float(avg_latency), 2) if avg_latency is not None else None,
    )
