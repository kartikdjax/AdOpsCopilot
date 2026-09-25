"""Verifies get_revive_audit_log (live, against the planted audit events in
admin_fixtures.py) and the Revive system status attached to
get_data_freshness (live for the real state, fake client for the
maintenance states this install can't produce without writing to
Revive's own maintenance tables).
"""
from __future__ import annotations

import sys
sys.path.insert(0, ".")

import pandas as pd

from src.config import get_settings
from src.semantic import core_tools as ct
from src.semantic import revive_admin as ra
from src.semantic.analytics_client import AnalyticsClient


def _changes(event) -> dict:
    return {c.field: (c.was, c.now) for c in event.changes}


class FakeStatusClient:
    """Serves rv_application_variable and the two maintenance logs."""

    def __init__(self, stats_minutes_ago: float | None, priority_minutes_ago: float | None):
        self._minutes = {"rv_log_maintenance_statistics": stats_minutes_ago,
                         "rv_log_maintenance_priority": priority_minutes_ago}

    def raw_query(self, sql, params, domain=None):
        if "rv_application_variable" in sql:
            return pd.DataFrame({"name": ["oa_version", "Geo_version"], "value": ["6.0.8", "6.0.9"]})
        table = next(t for t in self._minutes if t in sql)
        minutes = self._minutes[table]
        if minutes is None:
            return pd.DataFrame({"last_run": [None], "minutes_ago": [None]})
        return pd.DataFrame({"last_run": [pd.Timestamp("2026-09-24 08:00:00")], "minutes_ago": [minutes]})


def main() -> None:
    client = AnalyticsClient(get_settings())

    print("=" * 70)
    print("TEST 1: each planted story is answered by the audit log")
    print("=" * 70)
    paused = ra.get_revive_audit_log(client, object_type="campaign", object_id=4).events
    assert len(paused) == 1 and paused[0].user == "mgr2_ops"
    assert _changes(paused[0])["status"] == ("0 (running)", "1 (paused)")
    print(f"  Who paused campaign 4?      {paused[0].user} at {paused[0].time_utc}")

    booked = ra.get_revive_audit_log(client, object_type="campaign", object_id=3, days=30).events
    was, now = _changes(booked[0])["booked_impressions"]
    assert now == 2 * was, "campaign 3's booking should have doubled"
    print(f"  Why is campaign 3 behind?   booked_impressions {was:,} -> {now:,}")

    zone = ra.get_revive_audit_log(client, object_type="zone", object_id=3002, days=30).events
    capping = [e for e in zone if "capping" in _changes(e)]
    assert len(capping) == 1 and _changes(capping[0])["capping"] == (0, 3)
    live_cap = ra.inspect_revive_object(client, "zone", 3002).fields["capping"]
    assert live_cap == 3, "audit and live zone settings disagree"
    print(f"  What changed on Zone_3?     capping 0 -> 3 at {capping[0].time_utc} (live value: {live_cap})")

    banner = ra.get_revive_audit_log(client, object_type="banner", object_id=14).events
    assert {e.object_type for e in banner} == {"banner", "banner-zone link"}, "link events must follow the banner"
    print(f"  Banner 14 history:          {[f'{e.action} {e.object_type}' for e in banner]}")

    by_user = ra.get_revive_audit_log(client, username="mgr2_ops", action="changed", days=30).events
    assert {e.user for e in by_user} == {"mgr2_ops"} and {e.action for e in by_user} == {"changed"}
    print(f"  mgr2_ops changes (30 days): {len(by_user)}")
    print("PASS\n")

    print("=" * 70)
    print("TEST 2: passwords never leave the audit log; windows and filters hold")
    print("=" * 70)
    everything = ra.get_revive_audit_log(client, days=3650).events
    assert everything, "expected audit history"
    assert not any("password" in c.field.lower() for e in everything for c in e.changes), "FAILED: password exposed"
    user_105 = ra.get_revive_audit_log(client, object_type="user", object_id=105, days=31).events
    assert list(_changes(user_105[0])) == ["contact_name"], "only the non-secret field should remain"
    assert ra.get_revive_audit_log(client, object_type="user", object_id=105, days=7).events == []
    for bad in [lambda: ra.get_revive_audit_log(client, object_id=4),
                lambda: ra.get_revive_audit_log(client, object_type="campaigns"),
                lambda: ra.get_revive_audit_log(client, action="paused")]:
        try:
            bad()
            raise AssertionError("FAILED: invalid call accepted")
        except ValueError as e:
            print(f"  Correctly rejected: {e}")
    print(f"  newest {len(everything)} events (the tool cap) have no password fields")
    print("PASS\n")

    print("=" * 70)
    print("TEST 3: get_data_freshness(revive) reports the real system state")
    print("=" * 70)
    freshness = ct.get_data_freshness(client, "revive")
    system = freshness.system
    assert system["revive_version"] == "6.0.8" and "Geo" in system["plugins"]
    assert system["statistics_maintenance"]["status"] == "never_run"
    print(f"  stats: {freshness.status}, lag {freshness.lag_minutes} min; Revive {system['revive_version']}, "
          f"{len(system['plugins'])} plugins; maintenance: {system['statistics_maintenance']['status']}")
    print("PASS\n")

    print("=" * 70)
    print("TEST 4: maintenance ok / overdue / never run (fake client)")
    print("=" * 70)
    ok = ra.get_system_status(FakeStatusClient(35, 40))
    assert ok.statistics_maintenance.status == "ok" and not ok.warnings
    overdue = ra.get_system_status(FakeStatusClient(35, 300))
    assert overdue.priority_maintenance.status == "overdue" and len(overdue.warnings) == 1
    never = ra.get_system_status(FakeStatusClient(None, None))
    assert len(never.warnings) == 2
    print(f"  ok: {ok.warnings}\n  overdue: {overdue.warnings}\n  never: {len(never.warnings)} warnings")
    print("PASS\n")

    print("=" * 70)
    print("ALL REVIVE AUDIT + STATUS CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
