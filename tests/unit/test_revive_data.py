"""The Revive synthetic data encodes its intended zone scenarios."""
from __future__ import annotations

import pytest

from src.revive_data.generate_revive_data import generate_revive_dataset


@pytest.fixture(scope="module")
def data():
    return generate_revive_dataset(total_days=14)


def _zone_daily(data, scenario):
    zones, stats = data["_zones_with_scenario"], data["rv_data_summary_ad_hourly"]
    zone_id = zones[zones["scenario"] == scenario]["zoneid"].iloc[0]
    rows = stats[stats["zone_id"] == zone_id].copy()
    rows["date"] = rows["date_time"].dt.date
    return rows.groupby("date").agg(requests=("requests", "sum"), impressions=("impressions", "sum"))


def _halves(series):
    mid = len(series) // 2
    return series.iloc[:mid].mean(), series.iloc[mid:].mean()


def test_under_monetized_zone_fills_less_than_healthy(data):
    zones, stats = data["_zones_with_scenario"], data["rv_data_summary_ad_hourly"]
    by_zone = stats.groupby("zone_id").agg(requests=("requests", "sum"), impressions=("impressions", "sum"))
    by_zone["fill_rate"] = by_zone["impressions"] / by_zone["requests"]
    merged = zones.merge(by_zone, left_on="zoneid", right_index=True)
    def rate(scenario):
        return merged[merged["scenario"] == scenario]["fill_rate"].iloc[0]
    assert rate("under_monetized") < rate("healthy")


def test_fill_rate_decline_zone_declines(data):
    daily = _zone_daily(data, "fill_rate_decline")
    first, second = _halves(daily["impressions"] / daily["requests"])
    assert second < first


def test_seasonal_growth_zone_grows(data):
    first, second = _halves(_zone_daily(data, "seasonal_growth")["requests"])
    assert second > first
