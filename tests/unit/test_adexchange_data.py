"""The AdExchange synthetic data encodes its intended scenarios."""
from __future__ import annotations

import pytest

from src.adexchange_data.generate_adexchange_data import generate_adexchange_dataset


@pytest.fixture(scope="module")
def data():
    return generate_adexchange_dataset(hourly_days=14, raw_hours=3)


def _daily_timeout_rate(hourly, partner_id):
    rows = hourly[hourly["supply_partner_id"] == partner_id].copy()
    rows["date"] = rows["hour"].dt.date
    by_date = rows.groupby("date")
    return by_date["timeouts"].sum(), by_date["bid_requests"].sum()


def _campaign_id(data, scenario):
    campaigns = data["_campaigns_with_scenario"]
    return campaigns[campaigns["scenario"] == scenario]["campaign_id"].iloc[0]


def test_timeout_spike_is_recent_and_isolated(data):
    hourly, supply = data["ax_hourly_stats"], data["_supply_partners_with_scenario"]
    spike_id = supply[supply["scenario"] == "timeout_spike"]["supply_partner_id"].iloc[0]
    stable_id = supply[supply["scenario"] == "stable"]["supply_partner_id"].iloc[0]

    timeouts, requests = _daily_timeout_rate(hourly, spike_id)
    rate = timeouts / requests * 100
    early, last_3_days = rate.iloc[:-3].mean(), rate.iloc[-3:].mean()
    assert last_3_days > early * 3

    stable_timeouts, stable_requests = _daily_timeout_rate(hourly, stable_id)
    stable_last_3 = stable_timeouts.iloc[-3:].sum() / stable_requests.iloc[-3:].sum() * 100
    assert last_3_days > stable_last_3 * 3


def test_win_rate_decline_campaign_declines(data):
    hourly = data["ax_hourly_stats"]
    rows = hourly[hourly["campaign_id"] == _campaign_id(data, "win_rate_decline")]
    # One campaign's rows span several ad units in ad-unit-then-hour order, so
    # aggregate by hour and sort before splitting into early and late halves.
    by_hour = rows.groupby("hour")[["wins", "bids"]].sum().sort_index()
    mid = len(by_hour) // 2
    first = by_hour["wins"].iloc[:mid].sum() / max(1, by_hour["bids"].iloc[:mid].sum())
    second = by_hour["wins"].iloc[mid:].sum() / max(1, by_hour["bids"].iloc[mid:].sum())
    assert second < first


def test_bid_price_growth_campaign_grows(data):
    hourly = data["ax_hourly_stats"]
    rows = hourly[hourly["campaign_id"] == _campaign_id(data, "bid_price_growth")]
    price = rows.groupby("hour")["avg_bid_price"].mean().sort_index()
    mid = len(price) // 2
    assert price.iloc[mid:].mean() > price.iloc[:mid].mean()


def test_raw_window_has_auction_structure(data):
    status_counts = data["ax_bid_responses"]["status"].value_counts()
    impressions = data["ax_impressions"]
    assert set(status_counts.index) >= {"bid", "no_bid"}
    assert len(impressions) > 0
    # A request can win at most once.
    assert len(impressions) <= status_counts.get("bid", 0)
