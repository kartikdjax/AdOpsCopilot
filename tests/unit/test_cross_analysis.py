"""get_banner_zone_mapping and get_supply_demand_cross_analysis."""
from __future__ import annotations

import pandas as pd
import pytest

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


def test_banner_zone_mapping_without_ids_is_bounded_overview():
    sql, params = build_banner_zone_mapping_query(banner_id=None, zone_id=None, days=30)
    assert "f.ad_id = :banner_id" not in sql and "f.zone_id = :zone_id" not in sql
    assert "LIMIT :limit" in sql and params["limit"] == 50
    overview = get_banner_zone_mapping(FakeCrossClient())
    assert overview.banner_id is None and overview.zone_id is None and overview.pairs


def test_banner_zone_mapping_for_one_banner():
    mapping = get_banner_zone_mapping(FakeCrossClient(), banner_id=1, days=30)
    assert len(mapping.pairs) == 3
    assert mapping.pairs[0].zone_name == "Zone_1"


def test_supply_demand_cross_analysis_requires_an_id():
    with pytest.raises(ValueError):
        get_supply_demand_cross_analysis(FakeCrossClient())


def test_supply_demand_cross_analysis_holds_demand_partner_fixed():
    cross = get_supply_demand_cross_analysis(FakeCrossClient(), metric="win_rate",
                                             demand_partner_id=6000, days=14)
    assert len({p.demand_partner_id for p in cross.pairs}) == 1
    assert len({p.supply_partner_id for p in cross.pairs}) == 3
