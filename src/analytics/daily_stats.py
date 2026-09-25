"""
Aggregates raw event-level data into daily per-campaign stats.

This produces the EXACT shape that ClickHouse's daily_campaign_stats
materialized view returns (see Phase 1 schema). Keeping this logic
separate and pure means trend_analysis.py and anomaly_detection.py can
be developed and unit-tested against synthetic data, with zero changes
needed when they later run against real ClickHouse query results.
"""
from __future__ import annotations

import pandas as pd


def events_to_daily_stats(events: pd.DataFrame, campaign_id: int) -> pd.DataFrame:
    """Returns a DataFrame with one row per day: event_date, impressions,
    clicks, conversions, spend, ctr_pct, cvr_pct - for a single campaign."""
    campaign_events = events[events["campaign_id"] == campaign_id].copy()
    campaign_events["event_date"] = pd.to_datetime(campaign_events["event_time"]).dt.date

    pivot = campaign_events.pivot_table(
        index="event_date", columns="event_type", values="spend",
        aggfunc="count", fill_value=0,
    )
    spend_by_day = campaign_events[campaign_events["event_type"] == "click"].groupby("event_date")["spend"].sum()

    daily = pd.DataFrame({
        "impressions": pivot.get("impression", 0),
        "clicks": pivot.get("click", 0),
        "conversions": pivot.get("conversion", 0),
    })
    daily["spend"] = spend_by_day.reindex(daily.index, fill_value=0.0)
    daily["ctr_pct"] = (daily["clicks"] / daily["impressions"].replace(0, pd.NA) * 100).fillna(0).round(3)
    daily["cvr_pct"] = (daily["conversions"] / daily["clicks"].replace(0, pd.NA) * 100).fillna(0).round(3)

    daily = daily.reset_index().rename(columns={"index": "event_date"})
    daily["event_date"] = pd.to_datetime(daily["event_date"])
    return daily.sort_values("event_date").reset_index(drop=True)
