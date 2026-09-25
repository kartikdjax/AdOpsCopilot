"""Verifies inspect_revive_object and run_revive_check against the live
revive608 database, loaded by: python -m src.revive_data.load_revive_data --days 30

Every check must find exactly its PLANTED problem (admin_fixtures.py) -
no misses, no false positives among the synthetic data.
"""
from __future__ import annotations

import sys
sys.path.insert(0, ".")

from src.config import get_settings
from src.revive_data.admin_fixtures import PLANTED, SYNTHETIC_ID_START
from src.semantic import revive_admin as ra
from src.semantic.analytics_client import AnalyticsClient

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


def main() -> None:
    client = AnalyticsClient(get_settings())

    print("=" * 70)
    print("TEST 1: every check finds exactly its planted problem")
    print("=" * 70)
    assert set(_ROW_KEY) == set(ra.CHECKS) == set(PLANTED), "checks, test keys and PLANTED drifted apart"
    for name in ra.CHECKS:
        result = ra.run_revive_check(client, name)
        found = [_ROW_KEY[name](r) for r in result.rows]
        if name == "inactive_users":  # the real install's own users aren't ours to assert on
            found = [uid for uid in found if uid >= SYNTHETIC_ID_START]
        print(f"  {name:24s} found {found}")
        assert sorted(found) == sorted(PLANTED[name]), f"FAILED: {name} expected {PLANTED[name]}, got {found}"
    print("PASS\n")

    print("=" * 70)
    print("TEST 2: check_name='all' counts match the individual checks")
    print("=" * 70)
    overview = ra.run_revive_check(client, "all")
    for name, count in overview.counts.items():
        assert count == len(ra.run_revive_check(client, name).rows), f"FAILED: count mismatch for {name}"
    print(f"  {overview.counts}")
    print("PASS\n")

    print("=" * 70)
    print("TEST 3: parameters change the answer and are validated")
    print("=" * 70)
    assert ra.run_revive_check(client, "campaigns_expiring", days=2).rows == [], "3-day expiry shouldn't match days=2"
    assert len(ra.run_revive_check(client, "campaigns_behind_pace", threshold_pct=40).rows) == 0
    for bad in [lambda: ra.run_revive_check(client, "size_mismatch", days=3),
                lambda: ra.run_revive_check(client, "campaigns_expiring", days=-1),
                lambda: ra.run_revive_check(client, "no_such_check")]:
        try:
            bad()
            raise AssertionError("FAILED: invalid call accepted")
        except ValueError as e:
            print(f"  Correctly rejected: {e}")
    print("PASS\n")

    print("=" * 70)
    print("TEST 4: inspect every object type; user data never includes a password")
    print("=" * 70)
    samples = {"campaign": 3, "banner": 14, "zone": 3007, "affiliate": 4001,
               "client": 2000, "manager": 2, "user": 108}
    assert set(samples) == set(ra.OBJECTS)
    for object_type, object_id in samples.items():
        r = ra.inspect_revive_object(client, object_type, object_id)
        print(f"  {object_type:9s} {r.fields['name']}: links {{{', '.join(f'{k}: {len(v)}' for k, v in r.links.items())}}}")
        assert r.fields["id"] == object_id
    user = ra.inspect_revive_object(client, "user", 108)
    assert not any("password" in k for k in user.fields), "FAILED: password field exposed"
    assert {a["account_name"] for a in user.links["accounts"]} == {"Advertiser_1", "Advertiser_3"}

    campaign = ra.inspect_revive_object(client, "campaign", 3).fields
    assert campaign["status_label"] == "running" and campaign["revenue_type_label"] == "CPM"
    assert campaign["booked_clicks"] == "unlimited"
    banner = ra.inspect_revive_object(client, "banner", 14)
    assert banner.links["targeting_rules"][0]["data"] == "IN"
    access = {u["username"] for u in ra.inspect_revive_object(client, "client", 2000).links["users_with_access"]}
    assert {"adv1_owner", "agency_buyer", "default_mgr_analyst", "admin"} <= access, access
    try:
        ra.inspect_revive_object(client, "zone", 999_999)
        raise AssertionError("FAILED: missing object accepted")
    except ValueError as e:
        print(f"  Correctly rejected: {e}")
    print("PASS\n")

    print("=" * 70)
    print("ALL REVIVE ADMIN TOOL CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
