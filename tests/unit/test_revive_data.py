"""The Revive synthetic data encodes its intended zone scenarios."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.revive_data import admin_fixtures, generate_revive_data
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


def _seasonal_growth_halves(data):
    """Mean requests per hourly row, early half vs late half of the time range.
    Per row, not per day: the first and last calendar days are partial, and the
    planted campaign-6 stop removes rows from this zone near the end, both of
    which shrink daily totals whatever the underlying growth."""
    zones, stats = data["_zones_with_scenario"], data["rv_data_summary_ad_hourly"]
    zone_id = zones[zones["scenario"] == "seasonal_growth"]["zoneid"].iloc[0]
    rows = stats[stats["zone_id"] == zone_id]
    midpoint = rows["date_time"].min() + (rows["date_time"].max() - rows["date_time"].min()) / 2
    early = rows[rows["date_time"] < midpoint]["requests"].mean()
    late = rows[rows["date_time"] >= midpoint]["requests"].mean()
    return early, late


def test_seasonal_growth_zone_grows(data):
    early, late = _seasonal_growth_halves(data)
    assert late > early


@pytest.mark.parametrize("load_hour", range(0, 24, 3))
def test_seasonal_growth_holds_at_any_load_time(monkeypatch, load_hour):
    """The data is generated relative to now; growth must show whatever hour it's loaded."""
    fixed = datetime(2026, 9, 30, load_hour, 17, 42, tzinfo=timezone.utc)

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(generate_revive_data, "datetime", FixedClock)
    monkeypatch.setattr(admin_fixtures, "datetime", FixedClock)
    early, late = _seasonal_growth_halves(generate_revive_dataset(total_days=14))
    assert late > early
