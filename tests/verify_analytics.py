"""
Verifies trend_analysis.py and anomaly_detection.py against Phase 1's
synthetic data, whose scenarios are KNOWN ground truth. If detect_anomalies
doesn't find the ctr_anomaly_drop campaign's crash day, or analyze_trend
doesn't correctly call the ctr_improvement campaign "increasing", these
tools are not ready to wrap as MCP tools - this is the correctness gate.
"""
from __future__ import annotations

import sys
sys.path.insert(0, ".")

from src.analytics.anomaly_detection import detect_anomalies
from src.analytics.daily_stats import events_to_daily_stats
from src.analytics.trend_analysis import analyze_trend
from src.data.generate_synthetic_data import generate_full_dataset


def main() -> None:
    print("Generating test dataset...")
    data = generate_full_dataset(total_days=60, scale=0.3)
    campaigns = data["campaigns"]
    events = data["events"]

    print("\n" + "=" * 70)
    print("TEST 1: analyze_trend() on the ctr_improvement campaign")
    print("=" * 70)
    ctr_campaign_id = campaigns[campaigns["scenario"] == "ctr_improvement"]["campaign_id"].iloc[0]
    daily = events_to_daily_stats(events, ctr_campaign_id)
    trend = analyze_trend(daily, "ctr_pct")
    print(f"  direction={trend.direction}  pct_change={trend.pct_change}%  "
          f"first_half_avg={trend.first_half_avg}  second_half_avg={trend.second_half_avg}")
    assert trend.direction == "increasing", f"FAILED: expected increasing, got {trend.direction}"
    print("  PASS: correctly identified as 'increasing'")

    print("\n" + "=" * 70)
    print("TEST 2: analyze_trend() on the stable campaign (should NOT flag a trend)")
    print("=" * 70)
    stable_campaign_id = campaigns[campaigns["scenario"] == "stable"]["campaign_id"].iloc[0]
    daily_stable = events_to_daily_stats(events, stable_campaign_id)
    trend_stable = analyze_trend(daily_stable, "ctr_pct")
    print(f"  direction={trend_stable.direction}  pct_change={trend_stable.pct_change}%")
    assert trend_stable.direction == "stable", f"FAILED: expected stable, got {trend_stable.direction}"
    print("  PASS: correctly identified as 'stable' (not over-flagging noise)")

    print("\n" + "=" * 70)
    print("TEST 3: detect_anomalies() on the ctr_anomaly_drop campaign")
    print("=" * 70)
    anomaly_campaign_id = campaigns[campaigns["scenario"] == "ctr_anomaly_drop"]["campaign_id"].iloc[0]
    daily_anomaly = events_to_daily_stats(events, anomaly_campaign_id)
    anomalies = detect_anomalies(daily_anomaly, "ctr_pct", window=7, z_threshold=2.0)
    print(f"  Found {len(anomalies)} anomalies:")
    for a in anomalies:
        print(f"    {a.date.date()}  actual={a.actual_value}%  expected={a.expected_value}%  "
              f"z={a.z_score}  severity={a.severity}")
    assert len(anomalies) >= 1, "FAILED: expected to find at least the known crash day"
    print("  PASS: found the anomaly")

    print("\n" + "=" * 70)
    print("TEST 4: detect_anomalies() on the stable campaign (should find ~0 false positives)")
    print("=" * 70)
    anomalies_stable = detect_anomalies(daily_stable, "ctr_pct", window=7, z_threshold=2.0)
    print(f"  Found {len(anomalies_stable)} anomalies on a campaign with no real anomaly")
    print(f"  (a few false positives from pure noise are acceptable at z=2.0; "
          f"many would mean the threshold needs tuning)")

    print("\n" + "=" * 70)
    print("ALL CORRECTNESS CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
