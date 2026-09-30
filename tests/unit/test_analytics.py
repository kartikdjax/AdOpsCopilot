"""trend_analysis and anomaly_detection against the Phase 1 synthetic data,
whose scenarios are known ground truth: the ctr_improvement campaign must
read as "increasing", the stable one as "stable", and the ctr_anomaly_drop
campaign's crash day must be found."""
from __future__ import annotations

import pytest

from src.analytics.anomaly_detection import detect_anomalies
from src.analytics.daily_stats import events_to_daily_stats
from src.analytics.trend_analysis import analyze_trend
from src.data.generate_synthetic_data import generate_full_dataset


@pytest.fixture(scope="module")
def daily_for():
    data = generate_full_dataset(total_days=60, scale=0.3)
    campaigns, events = data["campaigns"], data["events"]

    def daily(scenario: str):
        campaign_id = campaigns[campaigns["scenario"] == scenario]["campaign_id"].iloc[0]
        return events_to_daily_stats(events, campaign_id)
    return daily


def test_trend_detects_ctr_improvement(daily_for):
    assert analyze_trend(daily_for("ctr_improvement"), "ctr_pct").direction == "increasing"


def test_trend_does_not_flag_noise(daily_for):
    assert analyze_trend(daily_for("stable"), "ctr_pct").direction == "stable"


def test_anomaly_finds_crash_day(daily_for):
    anomalies = detect_anomalies(daily_for("ctr_anomaly_drop"), "ctr_pct", window=7, z_threshold=2.0)
    assert len(anomalies) >= 1
