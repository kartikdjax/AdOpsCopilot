"""Phase 6 extension: Ad Exchange synthetic data. See docstrings on each function."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

SUPPLY_SCENARIOS = ["stable", "timeout_spike"]
CAMPAIGN_SCENARIOS = ["stable", "win_rate_decline", "bid_price_growth"]


@dataclass(frozen=True, slots=True)
class SupplyPartner:
    supply_partner_id: int
    partner_name: str
    partner_type: str
    scenario: str


@dataclass(frozen=True, slots=True)
class AdUnit:
    ad_unit_id: int
    supply_partner_id: int
    ad_unit_name: str
    format: str
    floor_price: float
    base_hourly_requests: int


@dataclass(frozen=True, slots=True)
class DemandPartner:
    demand_partner_id: int
    partner_name: str


@dataclass(frozen=True, slots=True)
class DspCampaign:
    campaign_id: int
    demand_partner_id: int
    campaign_name: str
    daily_budget: float
    scenario: str
    base_win_rate: float
    base_bid_price: float
    base_ctr: float


def generate_supply_partners(n: int = 3, seed: int = 11) -> list[SupplyPartner]:
    return [
        SupplyPartner(supply_partner_id=5000 + i, partner_name=f"SSP_Partner_{i+1}",
                      partner_type="ssp", scenario=SUPPLY_SCENARIOS[i % len(SUPPLY_SCENARIOS)])
        for i in range(n)
    ]


def generate_ad_units(supply_partners: list[SupplyPartner], per_partner: int = 2,
                       seed: int = 11) -> list[AdUnit]:
    rng = np.random.default_rng(seed)
    units, aid = [], 1
    for sp in supply_partners:
        for i in range(per_partner):
            units.append(AdUnit(
                ad_unit_id=aid, supply_partner_id=sp.supply_partner_id,
                ad_unit_name=f"{sp.partner_name}_AdUnit_{i+1}",
                format="banner", floor_price=float(rng.uniform(0.5, 2.0)),
                base_hourly_requests=int(rng.integers(1000, 4000)),
            ))
            aid += 1
    return units


def generate_demand_partners(n: int = 3, seed: int = 11) -> list[DemandPartner]:
    return [DemandPartner(demand_partner_id=6000 + i, partner_name=f"DSP_Partner_{i+1}") for i in range(n)]


def generate_campaigns(demand_partners: list[DemandPartner], per_partner: int = 2,
                        seed: int = 11) -> list[DspCampaign]:
    rng = np.random.default_rng(seed)
    campaigns, cid = [], 1
    for dp in demand_partners:
        for i in range(per_partner):
            scenario = CAMPAIGN_SCENARIOS[cid % len(CAMPAIGN_SCENARIOS)]
            campaigns.append(DspCampaign(
                campaign_id=cid, demand_partner_id=dp.demand_partner_id,
                campaign_name=f"{dp.partner_name}_Campaign_{i+1}_{scenario}",
                daily_budget=float(rng.uniform(1000, 8000)),
                scenario=scenario,
                base_win_rate=float(rng.uniform(0.15, 0.35)),
                base_bid_price=float(rng.uniform(1.0, 4.0)),
                base_ctr=float(rng.uniform(0.008, 0.02)),
            ))
            cid += 1
    return campaigns


def generate_hourly_history(ad_units: list[AdUnit], supply_partners: list[SupplyPartner],
                             campaigns: list[DspCampaign], total_days: int = 14,
                             seed: int = 11) -> pd.DataFrame:
    total_hours = total_days * 24
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    start = now - timedelta(hours=total_hours)
    supply_by_id = {sp.supply_partner_id: sp for sp in supply_partners}

    rows = []
    for ad_unit in ad_units:
        supply_partner = supply_by_id[ad_unit.supply_partner_id]

        for campaign in campaigns:
            rng = np.random.default_rng(seed + ad_unit.ad_unit_id * 1000 + campaign.campaign_id)

            for hour_index in range(total_hours):
                ts = start + timedelta(hours=hour_index)
                midpoint = total_hours // 2

                timeout_rate = 0.02
                latency_base = 45.0
                if supply_partner.scenario == "timeout_spike" and hour_index >= total_hours - (3 * 24):
                    timeout_rate = 0.35
                    latency_base = 220.0

                hour_of_day = hour_index % 24
                traffic_mult = 0.4 + 0.6 * np.sin(np.pi * max(hour_of_day - 4, 0) / 20) ** 2
                requests = max(1, int(ad_unit.base_hourly_requests * traffic_mult * rng.uniform(0.9, 1.1)))

                win_rate = campaign.base_win_rate
                bid_price = campaign.base_bid_price
                if campaign.scenario == "win_rate_decline" and hour_index >= midpoint:
                    progress = (hour_index - midpoint) / max(1, total_hours - midpoint)
                    win_rate = campaign.base_win_rate * (1 - 0.5 * progress)
                if campaign.scenario == "bid_price_growth":
                    growth = 1.0 + (hour_index / total_hours) * 0.5
                    bid_price = campaign.base_bid_price * growth

                bid_price = max(0.05, float(rng.normal(bid_price, bid_price * 0.1)))

                responses = int(requests * (1 - timeout_rate) * rng.uniform(0.9, 1.0))
                timeouts = requests - responses
                bid_rate = rng.uniform(0.5, 0.8)
                bids = int(responses * bid_rate)
                wins = int(rng.binomial(bids, min(max(win_rate, 0.0), 0.99))) if bids > 0 else 0
                win_price = max(0.01, bid_price * rng.uniform(0.75, 0.95))
                spend = round(wins * win_price, 4)
                clicks = int(rng.binomial(wins, min(campaign.base_ctr, 0.99))) if wins > 0 else 0
                avg_latency = float(rng.normal(latency_base, latency_base * 0.15))

                rows.append({
                    "hour": ts, "supply_partner_id": supply_partner.supply_partner_id,
                    "ad_unit_id": ad_unit.ad_unit_id, "demand_partner_id": campaign.demand_partner_id,
                    "campaign_id": campaign.campaign_id, "bid_requests": requests,
                    "bid_responses": responses, "bids": bids, "wins": wins, "timeouts": timeouts,
                    "spend": spend, "clicks": clicks, "avg_latency_ms": round(avg_latency, 2),
                    "avg_bid_price": round(bid_price, 4),
                    "avg_win_price": round(win_price, 4) if wins > 0 else 0.0,
                })

    return pd.DataFrame(rows)


def generate_raw_recent_window(ad_units: list[AdUnit], campaigns: list[DspCampaign],
                                hours: int = 3, seed: int = 11,
                                end_time: datetime | None = None) -> dict[str, pd.DataFrame]:
    """end_time defaults to now() - pass an explicit value to anchor the
    window elsewhere (not needed for normal use, mainly here so
    refresh_realtime_window.py's intent is obvious: it just calls this
    again with a fresh implicit `now`)."""
    rng = np.random.default_rng(seed + 999)
    now = end_time or datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    start = now - timedelta(hours=hours)

    requests_rows, responses_rows, impressions_rows, clicks_rows = [], [], [], []
    devices = ["mobile", "desktop", "tablet", "ctv"]
    geos = ["IN", "US", "GB", "AE", "SG"]

    total_minutes = hours * 60
    for ad_unit in ad_units:
        requests_per_minute = max(1, ad_unit.base_hourly_requests // 60)
        for minute in range(total_minutes):
            ts = start + timedelta(minutes=minute)
            n_requests = int(rng.poisson(requests_per_minute))
            for _ in range(n_requests):
                request_id = str(uuid.uuid4())
                req_time = ts + timedelta(seconds=int(rng.integers(0, 60)))
                requests_rows.append({
                    "request_id": request_id, "request_time": req_time,
                    "ad_unit_id": ad_unit.ad_unit_id, "supply_partner_id": ad_unit.supply_partner_id,
                    "device_type": rng.choice(devices), "geo_country": rng.choice(geos),
                    "floor_price": ad_unit.floor_price,
                })

                responding = rng.choice(campaigns, size=min(len(campaigns), rng.integers(1, 4)), replace=False)
                bids_this_request = []
                for campaign in responding:
                    status_roll = rng.random()
                    if status_roll < 0.05:
                        status, bid_price = "timeout", 0.0
                    elif status_roll < 0.45:
                        status, bid_price = "no_bid", 0.0
                    else:
                        status = "bid"
                        bid_price = max(0.05, float(rng.normal(campaign.base_bid_price, 0.3)))

                    latency = float(rng.normal(45 if status != "timeout" else 250, 15))
                    resp_time = req_time + timedelta(milliseconds=int(max(1, latency)))
                    responses_rows.append({
                        "request_id": request_id, "response_time": resp_time,
                        "demand_partner_id": campaign.demand_partner_id, "campaign_id": campaign.campaign_id,
                        "bid_price": round(bid_price, 4), "latency_ms": int(max(1, latency)),
                        "status": status, "is_winner": 0,
                    })
                    if status == "bid":
                        bids_this_request.append((campaign, bid_price, resp_time))

                if bids_this_request:
                    winner_campaign, winner_bid, winner_resp_time = max(bids_this_request, key=lambda b: b[1])
                    win_price = round(winner_bid * float(rng.uniform(0.75, 0.95)), 4)
                    impression_time = winner_resp_time + timedelta(milliseconds=int(rng.integers(5, 50)))
                    impressions_rows.append({
                        "request_id": request_id, "impression_time": impression_time,
                        "ad_unit_id": ad_unit.ad_unit_id, "supply_partner_id": ad_unit.supply_partner_id,
                        "demand_partner_id": winner_campaign.demand_partner_id,
                        "campaign_id": winner_campaign.campaign_id, "win_price": win_price,
                    })
                    if rng.random() < winner_campaign.base_ctr:
                        clicks_rows.append({
                            "request_id": request_id,
                            "click_time": impression_time + timedelta(seconds=int(rng.integers(1, 120))),
                            "campaign_id": winner_campaign.campaign_id,
                        })

    return {
        "ax_bid_requests": pd.DataFrame(requests_rows),
        "ax_bid_responses": pd.DataFrame(responses_rows),
        "ax_impressions": pd.DataFrame(impressions_rows),
        "ax_clicks": pd.DataFrame(clicks_rows),
    }


def generate_adexchange_dataset(hourly_days: int = 14, raw_hours: int = 3, seed: int = 11) -> dict[str, pd.DataFrame]:
    supply_partners = generate_supply_partners(seed=seed)
    ad_units = generate_ad_units(supply_partners, seed=seed)
    demand_partners = generate_demand_partners(seed=seed)
    campaigns = generate_campaigns(demand_partners, seed=seed)

    hourly = generate_hourly_history(ad_units, supply_partners, campaigns, total_days=hourly_days, seed=seed)
    raw = generate_raw_recent_window(ad_units, campaigns, hours=raw_hours, seed=seed)

    return {
        "ax_supply_partners": pd.DataFrame([{k: v for k, v in asdict(s).items() if k != "scenario"}
                                             for s in supply_partners]),
        "ax_ad_units": pd.DataFrame([{k: v for k, v in asdict(a).items() if k != "base_hourly_requests"}
                                      for a in ad_units]),
        "ax_demand_partners": pd.DataFrame([asdict(d) for d in demand_partners]),
        "ax_dsp_campaigns": pd.DataFrame([{k: v for k, v in asdict(c).items()
                                            if k not in ("scenario", "base_win_rate", "base_bid_price", "base_ctr")}
                                           for c in campaigns]),
        "ax_hourly_stats": hourly,
        **raw,
        "_supply_partners_with_scenario": pd.DataFrame([asdict(s) for s in supply_partners]),
        "_campaigns_with_scenario": pd.DataFrame([asdict(c) for c in campaigns]),
    }
