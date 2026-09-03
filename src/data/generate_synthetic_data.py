"""
Synthetic AdTech data generator.

Since there's no live data source yet, this generates a realistic dataset
with DELIBERATE, LABELED patterns - a CTR improvement, a budget exhaustion
event, a sudden anomaly, seasonal spend growth - so that later features
(trend analysis, anomaly detection, report generation) have real signal
to find, instead of pure noise that would make every feature look broken
or untestable.

Pure pandas/numpy logic here - no ClickHouse dependency, so it's fully
testable in any environment. See load_to_clickhouse.py for the part that
actually writes this into ClickHouse on your machine.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

DEVICE_WEIGHTS = {"mobile": 0.55, "desktop": 0.35, "tablet": 0.10}
GEO_WEIGHTS = {"IN": 0.45, "US": 0.25, "GB": 0.12, "AE": 0.10, "SG": 0.08}

# Each scenario tells a specific, labeled story - these are the "ground
# truth" events that Week 2 Day 4-style evaluation and anomaly-detection
# tools should be able to rediscover from the raw data alone.
SCENARIOS = ["stable", "ctr_improvement", "budget_exhaustion", "ctr_anomaly_drop", "seasonal_spend_growth"]


@dataclass(frozen=True, slots=True)
class Advertiser:
    advertiser_id: int
    advertiser_name: str
    industry: str


@dataclass(frozen=True, slots=True)
class Campaign:
    campaign_id: int
    advertiser_id: int
    campaign_name: str
    scenario: str
    daily_budget: float
    start_date: datetime
    end_date: datetime
    base_impressions: int
    base_ctr: float          # as a fraction, e.g. 0.021 = 2.1%
    base_conversion_rate: float
    cpc: float


def generate_advertisers(n: int = 5, seed: int = 42) -> list[Advertiser]:
    rng = np.random.default_rng(seed)
    industries = ["e-commerce", "fintech", "travel", "gaming", "education"]
    return [
        Advertiser(advertiser_id=1000 + i, advertiser_name=f"Advertiser_{i+1}",
                   industry=industries[i % len(industries)])
        for i in range(n)
    ]


def generate_campaigns(advertisers: list[Advertiser], campaigns_per_advertiser: int = 3,
                        total_days: int = 60, seed: int = 42, scale: float = 1.0) -> list[Campaign]:
    rng = np.random.default_rng(seed)
    end_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    start_date = end_date - timedelta(days=total_days)

    campaigns: list[Campaign] = []
    campaign_id = 1
    for adv in advertisers:
        for i in range(campaigns_per_advertiser):
            scenario = SCENARIOS[campaign_id % len(SCENARIOS)]
            campaigns.append(Campaign(
                campaign_id=campaign_id,
                advertiser_id=adv.advertiser_id,
                campaign_name=f"{adv.advertiser_name}_Campaign_{i+1}_{scenario}",
                scenario=scenario,
                daily_budget=float(rng.uniform(500, 5000)),
                start_date=start_date,
                end_date=end_date,
                base_impressions=max(1, int(rng.integers(2000, 8000) * scale)),
                base_ctr=float(rng.uniform(0.015, 0.035)),
                base_conversion_rate=float(rng.uniform(0.03, 0.08)),
                cpc=float(rng.uniform(0.15, 0.80)),
            ))
            campaign_id += 1
    return campaigns


def _day_metrics(campaign: Campaign, day_index: int, total_days: int) -> dict:
    """Returns (impressions, ctr, conversion_rate) for one campaign-day,
    shaped according to the campaign's scenario. This is where each
    scenario's 'story' actually gets encoded."""
    impressions = campaign.base_impressions
    ctr = campaign.base_ctr
    conversion_rate = campaign.base_conversion_rate

    midpoint = total_days // 2

    if campaign.scenario == "ctr_improvement":
        # Mirrors the tutorial's CTR story: a targeting update at the
        # midpoint lifts CTR from baseline to ~1.6x, permanently.
        if day_index >= midpoint:
            ctr = campaign.base_ctr * 1.6

    elif campaign.scenario == "budget_exhaustion":
        # Spend ramps up in the back half; once daily spend would exceed
        # budget, delivery (impressions) gets capped - a real, common
        # AdTech pattern ("campaign ran out of budget by 3pm").
        if day_index >= midpoint:
            impressions = int(impressions * 1.8)
        max_affordable_clicks = campaign.daily_budget / campaign.cpc
        max_impressions_for_budget = int(max_affordable_clicks / max(ctr, 0.001))
        impressions = min(impressions, max_impressions_for_budget)

    elif campaign.scenario == "ctr_anomaly_drop":
        # A single-day crash (e.g. broken creative, tracking pixel down)
        # on a specific known day, recovering immediately after.
        anomaly_day = total_days - 10
        if day_index == anomaly_day:
            ctr = campaign.base_ctr * 0.15

    elif campaign.scenario == "seasonal_spend_growth":
        # Gradual, compounding growth - "spend up 12% month over month" -
        # not a step change, a trend.
        growth_factor = 1.0 + (day_index / total_days) * 0.12
        impressions = int(impressions * growth_factor)

    # "stable" scenario: no modification - pure baseline + noise, added below.

    return {"impressions": impressions, "ctr": ctr, "conversion_rate": conversion_rate}


def generate_events_for_campaign(campaign: Campaign, total_days: int, seed: int) -> pd.DataFrame:
    """Generates raw event-level rows (impression/click/conversion) for one
    campaign across its full date range, vectorized with numpy per day."""
    rng = np.random.default_rng(seed + campaign.campaign_id)
    all_rows: list[pd.DataFrame] = []

    for day_index in range(total_days):
        day = campaign.start_date + timedelta(days=day_index)
        metrics = _day_metrics(campaign, day_index, total_days)

        # Add realistic day-to-day noise on top of the scenario's shape
        daily_impressions = max(0, int(rng.normal(metrics["impressions"], metrics["impressions"] * 0.08)))
        if daily_impressions == 0:
            continue

        daily_clicks = int(rng.binomial(daily_impressions, min(metrics["ctr"], 0.99)))
        daily_conversions = int(rng.binomial(daily_clicks, min(metrics["conversion_rate"], 0.99))) if daily_clicks > 0 else 0

        rows = []
        for event_type, count, spend_each in (
            ("impression", daily_impressions, 0.0),
            ("click", daily_clicks, campaign.cpc),
            ("conversion", daily_conversions, 0.0),
        ):
            if count == 0:
                continue
            seconds_offsets = rng.integers(0, 86400, size=count)
            event_times = [day + timedelta(seconds=int(s)) for s in seconds_offsets]
            devices = rng.choice(list(DEVICE_WEIGHTS.keys()), size=count, p=list(DEVICE_WEIGHTS.values()))
            geos = rng.choice(list(GEO_WEIGHTS.keys()), size=count, p=list(GEO_WEIGHTS.values()))
            rows.append(pd.DataFrame({
                "event_time": event_times,
                "campaign_id": campaign.campaign_id,
                "event_type": event_type,
                "spend": spend_each,
                "device_type": devices,
                "geo_country": geos,
            }))
        if rows:
            all_rows.append(pd.concat(rows, ignore_index=True))

    if not all_rows:
        return pd.DataFrame(columns=["event_time", "campaign_id", "event_type", "spend", "device_type", "geo_country"])
    return pd.concat(all_rows, ignore_index=True)


def generate_full_dataset(total_days: int = 60, seed: int = 42, scale: float = 1.0) -> dict[str, pd.DataFrame]:
    advertisers = generate_advertisers(seed=seed)
    campaigns = generate_campaigns(advertisers, total_days=total_days, seed=seed, scale=scale)

    events = pd.concat(
        [generate_events_for_campaign(c, total_days, seed) for c in campaigns],
        ignore_index=True,
    )

    advertisers_df = pd.DataFrame([asdict(a) for a in advertisers])
    campaigns_df = pd.DataFrame([asdict(c) for c in campaigns])

    return {"advertisers": advertisers_df, "campaigns": campaigns_df, "events": events}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate synthetic AdTech data")
    parser.add_argument("--days", type=int, default=60, help="Number of days of history to generate")
    parser.add_argument("--scale", type=float, default=1.0,
                         help="Multiplier on daily impression volume (0.1 = 10%% scale, for fast local testing)")
    args = parser.parse_args()

    data = generate_full_dataset(total_days=args.days, scale=args.scale)
    events = data["events"]
    campaigns = data["campaigns"]

    print(f"Generated {len(campaigns)} campaigns, {len(events):,} raw events\n")
    print("Campaign scenarios:")
    print(campaigns[["campaign_id", "campaign_name", "scenario"]].to_string(index=False))

    print("\n" + "=" * 70)
    print("Verification: daily CTR for the 'ctr_improvement' campaign")
    print("(should show a step-change around the midpoint, not a smooth ramp)")
    print("=" * 70)
    ctr_campaign_id = campaigns[campaigns["scenario"] == "ctr_improvement"]["campaign_id"].iloc[0]
    daily = events[events["campaign_id"] == ctr_campaign_id].copy()
    daily["event_date"] = pd.to_datetime(daily["event_time"]).dt.date
    pivot = daily.pivot_table(index="event_date", columns="event_type", values="spend", aggfunc="count", fill_value=0)
    pivot["ctr_pct"] = (pivot.get("click", 0) / pivot.get("impression", 1) * 100).round(2)
    print(pivot["ctr_pct"].iloc[::10])  # sample every 10th day to keep output short

    print("\n" + "=" * 70)
    print("Verification: the 'ctr_anomaly_drop' campaign's crash day is visible")
    print("=" * 70)
    anomaly_campaign_id = campaigns[campaigns["scenario"] == "ctr_anomaly_drop"]["campaign_id"].iloc[0]
    daily2 = events[events["campaign_id"] == anomaly_campaign_id].copy()
    daily2["event_date"] = pd.to_datetime(daily2["event_time"]).dt.date
    pivot2 = daily2.pivot_table(index="event_date", columns="event_type", values="spend", aggfunc="count", fill_value=0)
    pivot2["ctr_pct"] = (pivot2.get("click", 0) / pivot2.get("impression", 1) * 100).round(2)
    min_ctr_day = pivot2["ctr_pct"].idxmin()
    print(f"Lowest-CTR day found: {min_ctr_day} -> CTR={pivot2['ctr_pct'].min()}% "
          f"(neighbors average ~{pivot2['ctr_pct'].drop(min_ctr_day).mean():.2f}%)")


if __name__ == "__main__":
    main()
