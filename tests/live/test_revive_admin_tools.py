"""inspect_revive_object and run_revive_check against the loaded revive608
data: every check finds exactly its planted problem (admin_fixtures.PLANTED),
with no misses and no false positives among the synthetic rows."""
from __future__ import annotations

import pytest

from src.revive_data.admin_fixtures import PLANTED, SYNTHETIC_ID_START
from src.semantic import revive_admin as ra

# Which column identifies a row, per check.
_ROW_KEY = {
    "campaigns_expiring": lambda r: r["campaign_id"],
    "campaigns_behind_pace": lambda r: r["campaign_id"],
    "active_no_delivery": lambda r: r["campaign_id"],
    "campaigns_not_running": lambda r: r["campaign_id"],
    "unlinked_zones": lambda r: r["zone_id"],
    "size_mismatch": lambda r: (r["banner_id"], r["zone_id"]),
    "zero_fill_zones": lambda r: r["zone_id"],
    "inactive_users": lambda r: r["user_id"],
}


def test_checks_fixtures_and_row_keys_agree():
    assert set(_ROW_KEY) == set(ra.CHECKS) == set(PLANTED)


@pytest.mark.parametrize("name", sorted(PLANTED))
def test_check_finds_exactly_its_planted_problem(admin, name):
    found = [_ROW_KEY[name](r) for r in ra.run_revive_check(admin, name).rows]
    if name == "inactive_users":  # the install's own users aren't ours to assert on
        found = [uid for uid in found if uid >= SYNTHETIC_ID_START]
    assert sorted(found) == sorted(PLANTED[name])


def test_all_counts_match_individual_checks(admin):
    for name, count in ra.run_revive_check(admin, "all").counts.items():
        assert count == len(ra.run_revive_check(admin, name).rows), name


def test_parameters_change_the_answer(admin):
    assert ra.run_revive_check(admin, "campaigns_expiring", days=2).rows == []  # planted expiry is 3 days out
    assert ra.run_revive_check(admin, "campaigns_behind_pace", threshold_pct=40).rows == []


@pytest.mark.parametrize("kwargs", [
    {"check_name": "size_mismatch", "days": 3},
    {"check_name": "campaigns_expiring", "days": -1},
    {"check_name": "no_such_check"},
], ids=["days-on-undated-check", "negative-days", "unknown-check"])
def test_invalid_check_calls_are_rejected(admin, kwargs):
    with pytest.raises(ValueError):
        ra.run_revive_check(admin, **kwargs)


SAMPLES = {"campaign": 3, "banner": 14, "zone": 3007, "affiliate": 4001,
           "client": 2000, "manager": 2, "user": 108}


def test_samples_cover_every_object_type():
    assert set(SAMPLES) == set(ra.OBJECTS)


@pytest.mark.parametrize("object_type", sorted(SAMPLES))
def test_inspect_every_object_type(admin, object_type):
    assert ra.inspect_revive_object(admin, object_type, SAMPLES[object_type]).fields["id"] == SAMPLES[object_type]


def test_inspect_details(admin):
    user = ra.inspect_revive_object(admin, "user", 108)
    assert not any("password" in k for k in user.fields)
    assert {a["account_name"] for a in user.links["accounts"]} == {"Advertiser_1", "Advertiser_3"}

    campaign = ra.inspect_revive_object(admin, "campaign", 3).fields
    assert campaign["status_label"] == "running" and campaign["revenue_type_label"] == "CPM"
    assert campaign["booked_clicks"] == "unlimited"
    assert ra.inspect_revive_object(admin, "banner", 14).links["targeting_rules"][0]["data"] == "IN"
    access = {u["username"] for u in ra.inspect_revive_object(admin, "client", 2000).links["users_with_access"]}
    assert {"adv1_owner", "agency_buyer", "default_mgr_analyst", "admin"} <= access


def test_inspect_missing_object_is_rejected(admin):
    with pytest.raises(ValueError):
        ra.inspect_revive_object(admin, "zone", 999_999)
