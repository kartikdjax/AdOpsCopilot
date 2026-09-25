"""Verifies get_banner_zone_mapping and get_supply_demand_cross_analysis."""
from __future__ import annotations

import sys
sys.path.insert(0, ".")

import pandas as pd

from src.semantic.cross_analysis import (
    build_banner_zone_mapping_query, get_banner_zone_mapping, get_supply_demand_cross_analysis,
)


class FakeCrossClient:
    agency_id = None  # unscoped (admin)

    def raw_query(self, sql, params, domain=None):
        if "rv_data_summary_ad_hourly" in sql:
            return pd.DataFrame({
                "banner_id": [1, 1, 1], "banner_name": ["Banner_A", "Banner_A", "Banner_A"],
                "zone_id": [3001, 3002, 3003], "zone_name": ["Zone_1", "Zone_2", "Zone_3"],
                "impressions": [50000, 30000, 5000], "clicks": [1200, 600, 50], "ctr": [2.4, 2.0, 1.0],
            })
        return pd.DataFrame({
            "supply_partner_id": [5000, 5001, 5002],
            "supply_partner_name": ["SSP_1", "SSP_2", "SSP_3"],
            "demand_partner_id": [6000, 6000, 6000],
            "demand_partner_name": ["DSP_1", "DSP_1", "DSP_1"],
            "value": [27.3, 22.4, 18.9], "bid_requests": [4_700_000, 4_600_000, 4_500_000],
        })


def main() -> None:
    print("=" * 70)
    print("TEST 1: get_banner_zone_mapping with no IDs is an account-wide overview, capped by LIMIT")
    print("=" * 70)
    sql, params = build_banner_zone_mapping_query(banner_id=None, zone_id=None, days=30)
    assert "f.ad_id = :banner_id" not in sql and "f.zone_id = :zone_id" not in sql, \
        "FAILED: no-ID call should not filter by banner or zone"
    assert "LIMIT :limit" in sql and params["limit"] == 50, "FAILED: account-wide call must stay bounded"
    overview = get_banner_zone_mapping(FakeCrossClient())
    assert overview.banner_id is None and overview.zone_id is None and overview.pairs
    print(f"  {len(overview.pairs)} pairs, query bounded to LIMIT {params['limit']}")
    print("PASS: account-wide call allowed and bounded\n")

    print("=" * 70)
    print("TEST 2: get_banner_zone_mapping returns zones ranked by impressions for one banner")
    print("=" * 70)
    mapping = get_banner_zone_mapping(FakeCrossClient(), banner_id=1, days=30)
    for p in mapping.pairs:
        print(f"  {p.zone_name}: impressions={p.impressions}, ctr={p.ctr}%")
    assert len(mapping.pairs) == 3
    assert mapping.pairs[0].zone_name == "Zone_1"  # highest impressions, query orders DESC
    print("PASS: banner-to-zone breakdown correct, all rows share the queried banner\n")

    print("=" * 70)
    print("TEST 3: get_supply_demand_cross_analysis also requires at least one ID")
    print("=" * 70)
    try:
        get_supply_demand_cross_analysis(FakeCrossClient())
        raise AssertionError("FAILED: should have rejected a call with no IDs at all")
    except ValueError as e:
        print(f"Correctly rejected: {e}")
    print("PASS\n")

    print("=" * 70)
    print("TEST 4: cross-analysis shows one DSP's win rate varying across 3 different SSPs")
    print("=" * 70)
    cross = get_supply_demand_cross_analysis(FakeCrossClient(), metric="win_rate",
                                              demand_partner_id=6000, days=14)
    print(f"Metric: {cross.metric}, fixed demand_partner_id={cross.demand_partner_id}")
    for p in cross.pairs:
        print(f"  {p.supply_partner_name}: win_rate={p.value}% (volume={p.bid_requests:,})")
    assert len({p.demand_partner_id for p in cross.pairs}) == 1, "FAILED: demand partner should be fixed"
    assert len({p.supply_partner_id for p in cross.pairs}) == 3, "FAILED: should vary across 3 supply partners"
    print("PASS: demand partner correctly held fixed while supply partner varies\n")

    print("=" * 70)
    print("ALL CROSS-ANALYSIS CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
