"""Verifies the Revive synthetic data actually encodes its intended scenarios."""
from __future__ import annotations

import sys
sys.path.insert(0, ".")

from src.revive_data.generate_revive_data import generate_revive_dataset


def main() -> None:
    print("Generating Revive-schema dataset (14 days)...")
    data = generate_revive_dataset(total_days=14)
    stats = data["rv_data_summary_ad_hourly"]
    zones = data["_zones_with_scenario"]

    print(f"\n{len(data['rv_clients'])} clients, {len(data['rv_campaigns'])} campaigns, "
          f"{len(data['rv_banners'])} banners, {len(zones)} zones")
    print(f"{len(stats):,} hourly stat rows generated\n")

    print("=" * 70)
    print("TEST 1: fill rate by zone scenario (requests -> impressions)")
    print("=" * 70)
    by_zone = stats.groupby("zone_id").agg(requests=("requests", "sum"), impressions=("impressions", "sum"))
    by_zone["fill_rate_pct"] = (by_zone["impressions"] / by_zone["requests"] * 100).round(1)
    merged = zones.merge(by_zone, left_on="zoneid", right_index=True)
    print(merged[["zonename", "scenario", "fill_rate_pct"]].to_string(index=False))

    healthy_rate = merged[merged["scenario"] == "healthy"]["fill_rate_pct"].iloc[0]
    under_mon_rate = merged[merged["scenario"] == "under_monetized"]["fill_rate_pct"].iloc[0]
    assert under_mon_rate < healthy_rate, (
        f"FAILED: under_monetized ({under_mon_rate}%) should be well below healthy ({healthy_rate}%)"
    )
    print(f"\nPASS: under_monetized ({under_mon_rate}%) is well below healthy ({healthy_rate}%)")

    print("\n" + "=" * 70)
    print("TEST 2: fill_rate_decline zone actually declines over time")
    print("=" * 70)
    decline_zone_id = zones[zones["scenario"] == "fill_rate_decline"]["zoneid"].iloc[0]
    decline_stats = stats[stats["zone_id"] == decline_zone_id].copy()
    decline_stats["date"] = decline_stats["date_time"].dt.date
    daily = decline_stats.groupby("date").agg(requests=("requests", "sum"), impressions=("impressions", "sum"))
    daily["fill_rate_pct"] = (daily["impressions"] / daily["requests"] * 100).round(1)

    first_half_avg = daily["fill_rate_pct"].iloc[:len(daily) // 2].mean()
    second_half_avg = daily["fill_rate_pct"].iloc[len(daily) // 2:].mean()
    print(f"First half avg fill rate: {first_half_avg:.1f}%")
    print(f"Second half avg fill rate: {second_half_avg:.1f}%")
    assert second_half_avg < first_half_avg, "FAILED: fill_rate_decline zone did not actually decline"
    print(f"PASS: fill rate declined from {first_half_avg:.1f}% to {second_half_avg:.1f}%")

    print("\n" + "=" * 70)
    print("TEST 3: seasonal_growth zone's request volume actually grows")
    print("=" * 70)
    growth_zone_id = zones[zones["scenario"] == "seasonal_growth"]["zoneid"].iloc[0]
    growth_stats = stats[stats["zone_id"] == growth_zone_id].copy()
    growth_stats["date"] = growth_stats["date_time"].dt.date
    daily_requests = growth_stats.groupby("date")["requests"].sum()
    first_half_req = daily_requests.iloc[:len(daily_requests) // 2].mean()
    second_half_req = daily_requests.iloc[len(daily_requests) // 2:].mean()
    print(f"First half avg daily requests: {first_half_req:.0f}")
    print(f"Second half avg daily requests: {second_half_req:.0f}")
    assert second_half_req > first_half_req, "FAILED: seasonal_growth zone did not actually grow"
    print(f"PASS: requests grew from {first_half_req:.0f}/day to {second_half_req:.0f}/day")

    print("\n" + "=" * 70)
    print("ALL CORRECTNESS CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
