"""
Semantic metric registry - the single source of truth for every metric
formula in the copilot.

Why this exists: without a registry, each tool computes CTR its own way
and you eventually ship the classic AI-analytics failure - "the dashboard
says CTR is 2.1% but the copilot says 2.4%". One definition, used by every
tool, makes that impossible.

It's also what keeps the tool count low: calculate_kpi, compare_periods,
analyze_trend, detect_anomalies and rank_entities all read from here, so
adding a new metric makes it available to ALL of them with zero new tools.

NOTE on domain-specific definitions: `fill_rate` and `ctr` exist in BOTH
domains with genuinely DIFFERENT formulas (ad-server fill is
impressions/requests; exchange fill is wins/bid_requests). That is not a
bug to unify - they measure different things. The registry keys metrics by
(domain, name) and get_metric_definition always discloses which one applies.
"""
from __future__ import annotations

from dataclasses import dataclass

REVIVE = "revive"
EXCHANGE = "exchange"


@dataclass(frozen=True, slots=True)
class MetricDef:
    name: str
    domain: str
    kind: str              # "count" | "ratio" | "monetary" | "average"
    description: str
    numerator: str          # ClickHouse SQL aggregate expression
    denominator: str | None = None
    multiplier: float = 1.0  # 100 -> percentage, 1000 -> per-mille (eCPM)
    unit: str = ""

    @property
    def key(self) -> str:
        return f"{self.domain}.{self.name}"

    @property
    def formula_text(self) -> str:
        """Human-readable formula, used by get_metric_definition so the LLM
        can explain a number rather than just report it."""
        if self.denominator is None:
            return self.numerator
        mult = "" if self.multiplier == 1.0 else f" * {self.multiplier:g}"
        return f"({self.numerator} / {self.denominator}){mult}"

    def sql_expression(self) -> str:
        """The SQL expression that computes this metric. NULLIF() guards
        against divide-by-zero returning inf/NaN, which would otherwise
        flow into the LLM's answer as a nonsense number. Uppercase NULLIF
        works identically in both ClickHouse (exchange domain) and MySQL
        (revive domain) - this one method serves both dialects."""
        if self.denominator is None:
            return self.numerator
        # Both sides bracketed so a compound numerator like "sum(a) - sum(b)"
        # divides as a whole rather than by operator precedence.
        expr = f"({self.numerator}) / NULLIF({self.denominator}, 0)"
        if self.multiplier != 1.0:
            expr = f"({expr}) * {self.multiplier:g}"
        return f"round({expr}, 4)"


# ---------------------------------------------------------------------------
# Revive (ad server) metrics - source: revive.rv_data_summary_ad_hourly
# ---------------------------------------------------------------------------
_REVIVE_METRICS = [
    MetricDef(name="requests", domain=REVIVE, kind="count", unit="requests",
              description="Ad requests received - a zone asking the ad server for a banner to serve.",
              numerator="sum(requests)"),
    MetricDef(name="impressions", domain=REVIVE, kind="count", unit="impressions",
              description="Ads actually served in response to a request.",
              numerator="sum(impressions)"),
    MetricDef(name="clicks", domain=REVIVE, kind="count", unit="clicks",
              description="Clicks recorded on served impressions.",
              numerator="sum(clicks)"),
    MetricDef(name="conversions", domain=REVIVE, kind="count", unit="conversions",
              description="Conversions attributed to clicks.",
              numerator="sum(conversions)"),
    MetricDef(name="fill_rate", domain=REVIVE, kind="ratio", unit="%",
              description=("Share of ad requests that were filled with an impression. "
                           "AD SERVER definition - distinct from the exchange's fill_rate, "
                           "which is wins/bid_requests."),
              numerator="sum(impressions)", denominator="sum(requests)", multiplier=100),
    MetricDef(name="ctr", domain=REVIVE, kind="ratio", unit="%",
              description="Click-through rate: clicks divided by impressions served.",
              numerator="sum(clicks)", denominator="sum(impressions)", multiplier=100),
    MetricDef(name="cvr", domain=REVIVE, kind="ratio", unit="%",
              description="Conversion rate: conversions divided by clicks.",
              numerator="sum(conversions)", denominator="sum(clicks)", multiplier=100),
    # Money - total_revenue is what advertisers are billed (campaign
    # revenue/revenue_type), total_cost is what websites are paid (zone
    # cost/cost_type). Both are filled by Revive's maintenance run.
    MetricDef(name="revenue", domain=REVIVE, kind="monetary", unit="currency",
              description="Advertiser revenue earned on delivery, from each campaign's pricing (CPM, CPC, ...).",
              numerator="sum(total_revenue)"),
    MetricDef(name="cost", domain=REVIVE, kind="monetary", unit="currency",
              description="Payout owed to websites, from each zone's cost model (revenue share, fixed CPM, ...).",
              numerator="sum(total_cost)"),
    MetricDef(name="margin", domain=REVIVE, kind="monetary", unit="currency",
              description="Revenue minus website cost - what the ad network keeps. Negative means the zone loses money.",
              numerator="sum(total_revenue) - sum(total_cost)"),
    MetricDef(name="margin_pct", domain=REVIVE, kind="ratio", unit="%",
              description="Margin as a share of revenue.",
              numerator="sum(total_revenue) - sum(total_cost)", denominator="sum(total_revenue)",
              multiplier=100),
    MetricDef(name="ecpm", domain=REVIVE, kind="monetary", unit="currency per 1000",
              description=("Revenue per 1000 impressions. AD SERVER definition - distinct from the "
                           "exchange's ecpm, which is spend per 1000 wins."),
              numerator="sum(total_revenue)", denominator="sum(impressions)", multiplier=1000),
]

# ---------------------------------------------------------------------------
# Exchange (RTB) metrics - source: adexchange.ax_hourly_stats
# ---------------------------------------------------------------------------
_EXCHANGE_METRICS = [
    MetricDef(name="bid_requests", domain=EXCHANGE, kind="count", unit="requests",
              description="Bid requests sent into the auction.",
              numerator="sum(bid_requests)"),
    MetricDef(name="bid_responses", domain=EXCHANGE, kind="count", unit="responses",
              description="Responses received from demand partners, excluding timeouts.",
              numerator="sum(bid_responses)"),
    MetricDef(name="bids", domain=EXCHANGE, kind="count", unit="bids",
              description="Responses that contained an actual bid (not a no-bid).",
              numerator="sum(bids)"),
    MetricDef(name="wins", domain=EXCHANGE, kind="count", unit="wins",
              description="Bids that won their auction and served an impression.",
              numerator="sum(wins)"),
    MetricDef(name="timeouts", domain=EXCHANGE, kind="count", unit="timeouts",
              description="Bid requests where the demand partner failed to respond in time.",
              numerator="sum(timeouts)"),
    MetricDef(name="spend", domain=EXCHANGE, kind="monetary", unit="currency",
              description="Total clearing price paid across won auctions.",
              numerator="sum(spend)"),
    MetricDef(name="clicks", domain=EXCHANGE, kind="count", unit="clicks",
              description="Clicks recorded on won impressions.",
              numerator="sum(clicks)"),
    MetricDef(name="bid_rate", domain=EXCHANGE, kind="ratio", unit="%",
              description="Share of received responses that contained a bid - demand appetite for this supply.",
              numerator="sum(bids)", denominator="sum(bid_responses)", multiplier=100),
    MetricDef(name="win_rate", domain=EXCHANGE, kind="ratio", unit="%",
              description="Share of bids that won their auction.",
              numerator="sum(wins)", denominator="sum(bids)", multiplier=100),
    MetricDef(name="timeout_rate", domain=EXCHANGE, kind="ratio", unit="%",
              description="Share of bid requests lost to demand-partner timeouts. A supply-quality and latency signal.",
              numerator="sum(timeouts)", denominator="sum(bid_requests)", multiplier=100),
    MetricDef(name="fill_rate", domain=EXCHANGE, kind="ratio", unit="%",
              description=("Share of bid requests that resulted in a win. EXCHANGE definition - "
                           "distinct from the ad server's fill_rate, which is impressions/requests."),
              numerator="sum(wins)", denominator="sum(bid_requests)", multiplier=100),
    MetricDef(name="ctr", domain=EXCHANGE, kind="ratio", unit="%",
              description="Click-through rate on won impressions.",
              numerator="sum(clicks)", denominator="sum(wins)", multiplier=100),
    MetricDef(name="ecpm", domain=EXCHANGE, kind="monetary", unit="currency per 1000",
              description="Effective cost per thousand impressions: spend per 1000 wins.",
              numerator="sum(spend)", denominator="sum(wins)", multiplier=1000),
    MetricDef(name="avg_latency_ms", domain=EXCHANGE, kind="average", unit="ms",
              description=("Average demand-partner response latency, weighted by bid request volume. "
                           "Rising latency usually precedes a rising timeout rate."),
              numerator="sum(avg_latency_ms * bid_requests)", denominator="sum(bid_requests)"),
]

METRICS: dict[str, MetricDef] = {m.key: m for m in (_REVIVE_METRICS + _EXCHANGE_METRICS)}


def get_metric(domain: str, name: str) -> MetricDef:
    key = f"{domain}.{name}"
    metric = METRICS.get(key)
    if metric is None:
        available = sorted(m.name for m in METRICS.values() if m.domain == domain)
        raise ValueError(
            f"Unknown metric {name!r} for domain {domain!r}. Available: {', '.join(available)}"
        )
    return metric


def list_metrics(domain: str | None = None) -> list[MetricDef]:
    metrics = list(METRICS.values())
    if domain:
        metrics = [m for m in metrics if m.domain == domain]
    return sorted(metrics, key=lambda m: (m.domain, m.name))
