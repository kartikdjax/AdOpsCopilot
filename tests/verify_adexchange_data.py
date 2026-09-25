"""Verifies the AdExchange synthetic data encodes its intended scenarios."""
from __future__ import annotations

import sys
sys.path.insert(0, ".")

from src.adexchange_data.generate_adexchange_data import generate_adexchange_dataset


def main() -> None:
    print("Generating AdExchange dataset (14 days hourly + 3 hours raw)...")
    data = generate_adexchange_dataset(hourly_days=14, raw_hours=3)
    hourly = data["ax_hourly_stats"]
    supply = data["_supply_partners_with_scenario"]
    campaigns = data["_campaigns_with_scenario"]

    print(f"\n{len(hourly):,} hourly rollup rows")
    print(f"{len(data['ax_bid_requests']):,} raw bid requests, "
          f"{len(data['ax_bid_responses']):,} raw bid responses, "
          f"{len(data['ax_impressions']):,} raw impressions, "
          f"{len(data['ax_clicks']):,} raw clicks (last 3 hours)\n")

    print("=" * 70)
    print("TEST 1: timeout_spike supply partner - elevated timeouts in the LAST 3 days only")
    print("=" * 70)
    spike_partner_id = supply[supply["scenario"] == "timeout_spike"]["supply_partner_id"].iloc[0]
    stable_partner_id = supply[supply["scenario"] == "stable"]["supply_partner_id"].iloc[0]

    spike_data = hourly[hourly["supply_partner_id"] == spike_partner_id].copy()
    spike_data["date"] = spike_data["hour"].dt.date
    daily_timeout_rate = (spike_data.groupby("date")["timeouts"].sum()
                          / spike_data.groupby("date")["bid_requests"].sum() * 100)

    early_period = daily_timeout_rate.iloc[:-3].mean()
    last_3_days = daily_timeout_rate.iloc[-3:].mean()
    print(f"Timeout partner - early period avg: {early_period:.1f}%, last 3 days avg: {last_3_days:.1f}%")
    assert last_3_days > early_period * 3, f"FAILED: expected a clear spike, got {early_period:.1f}% -> {last_3_days:.1f}%"

    stable_data = hourly[hourly["supply_partner_id"] == stable_partner_id].copy()
    stable_data["date"] = stable_data["hour"].dt.date
    stable_last_3 = (stable_data.groupby("date")["timeouts"].sum().iloc[-3:].sum()
                     / stable_data.groupby("date")["bid_requests"].sum().iloc[-3:].sum() * 100)
    print(f"Stable partner - last 3 days timeout rate: {stable_last_3:.1f}% (should stay low)")
    assert last_3_days > stable_last_3 * 3, "FAILED: spike partner should be clearly worse than stable partner"
    print(f"PASS: timeout spike is isolated to the affected partner and the recent window\n")

    print("=" * 70)
    print("TEST 2: win_rate_decline campaign actually declines")
    print("=" * 70)
    decline_campaign_id = campaigns[campaigns["scenario"] == "win_rate_decline"]["campaign_id"].iloc[0]
    c_data = hourly[hourly["campaign_id"] == decline_campaign_id]
    # IMPORTANT: rows for one campaign span multiple ad_units, concatenated
    # in ad_unit-then-hour order - NOT sorted by time. Must aggregate by
    # hour and sort chronologically before splitting into halves, or the
    # split doesn't actually correspond to "early period vs late period".
    by_hour = c_data.groupby("hour")[["wins", "bids"]].sum().sort_index()
    midpoint = len(by_hour) // 2
    first_half_win_rate = by_hour["wins"].iloc[:midpoint].sum() / max(1, by_hour["bids"].iloc[:midpoint].sum()) * 100
    second_half_win_rate = by_hour["wins"].iloc[midpoint:].sum() / max(1, by_hour["bids"].iloc[midpoint:].sum()) * 100
    print(f"First half win rate: {first_half_win_rate:.1f}%, second half: {second_half_win_rate:.1f}%")
    assert second_half_win_rate < first_half_win_rate, "FAILED: win rate did not decline"
    print(f"PASS: win rate declined from {first_half_win_rate:.1f}% to {second_half_win_rate:.1f}%\n")

    print("=" * 70)
    print("TEST 3: bid_price_growth campaign's average bid price actually grows")
    print("=" * 70)
    growth_campaign_id = campaigns[campaigns["scenario"] == "bid_price_growth"]["campaign_id"].iloc[0]
    g_data = hourly[hourly["campaign_id"] == growth_campaign_id]
    by_hour_price = g_data.groupby("hour")["avg_bid_price"].mean().sort_index()
    midpoint = len(by_hour_price) // 2
    first_half_price = by_hour_price.iloc[:midpoint].mean()
    second_half_price = by_hour_price.iloc[midpoint:].mean()
    print(f"First half avg bid price: ${first_half_price:.3f}, second half: ${second_half_price:.3f}")
    assert second_half_price > first_half_price, "FAILED: bid price did not grow"
    print(f"PASS: bid price grew from ${first_half_price:.3f} to ${second_half_price:.3f}\n")

    print("=" * 70)
    print("TEST 4: raw recent-window data has real auction structure")
    print("=" * 70)
    responses = data["ax_bid_responses"]
    impressions = data["ax_impressions"]
    status_counts = responses["status"].value_counts()
    print(f"Response status breakdown:\n{status_counts}")
    assert set(status_counts.index) >= {"bid", "no_bid"}, "FAILED: expected both bid and no_bid statuses present"
    assert len(impressions) > 0, "FAILED: no impressions generated - winner selection is broken"
    assert len(impressions) <= status_counts.get("bid", 0), (
        "FAILED: more impressions than actual bids - a request can win at most once"
    )
    print(f"PASS: {len(impressions)} impressions from {status_counts.get('bid', 0)} total bids "
          f"({len(impressions)/max(1,status_counts.get('bid',1))*100:.1f}% of bids won)")

    print("\n" + "=" * 70)
    print("ALL CORRECTNESS CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
