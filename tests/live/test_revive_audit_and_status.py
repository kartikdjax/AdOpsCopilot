"""get_revive_audit_log against the planted audit events (admin_fixtures.py)
and the Revive system status reported by get_data_freshness."""
from __future__ import annotations

import pytest

from src.semantic import core_tools as ct
from src.semantic import revive_admin as ra


def _changes(event) -> dict:
    return {c.field: (c.was, c.now) for c in event.changes}


def test_who_paused_campaign_4(admin):
    paused = ra.get_revive_audit_log(admin, object_type="campaign", object_id=4).events
    assert len(paused) == 1 and paused[0].user == "mgr2_ops"
    assert _changes(paused[0])["status"] == ("0 (running)", "1 (paused)")


def test_why_campaign_3_is_behind(admin):
    booked = ra.get_revive_audit_log(admin, object_type="campaign", object_id=3, days=30).events
    was, now = _changes(booked[0])["booked_impressions"]
    assert now == 2 * was


def test_zone_capping_change_matches_live_setting(admin):
    events = ra.get_revive_audit_log(admin, object_type="zone", object_id=3002, days=30).events
    capping = [e for e in events if "capping" in _changes(e)]
    assert len(capping) == 1 and _changes(capping[0])["capping"] == (0, 3)
    assert ra.inspect_revive_object(admin, "zone", 3002).fields["capping"] == 3


def test_banner_history_includes_its_zone_links(admin):
    events = ra.get_revive_audit_log(admin, object_type="banner", object_id=14).events
    assert {e.object_type for e in events} == {"banner", "banner-zone link"}


def test_filter_by_user_and_action(admin):
    events = ra.get_revive_audit_log(admin, username="mgr2_ops", action="changed", days=30).events
    assert {e.user for e in events} == {"mgr2_ops"} and {e.action for e in events} == {"changed"}


def test_passwords_never_leave_the_audit_log(admin):
    everything = ra.get_revive_audit_log(admin, days=3650).events
    assert everything
    assert not any("password" in c.field.lower() for e in everything for c in e.changes)
    user_105 = ra.get_revive_audit_log(admin, object_type="user", object_id=105, days=31).events
    assert list(_changes(user_105[0])) == ["contact_name"]


def test_day_window_applies(admin):
    assert ra.get_revive_audit_log(admin, object_type="user", object_id=105, days=7).events == []


@pytest.mark.parametrize("kwargs", [
    {"object_id": 4}, {"object_type": "campaigns"}, {"action": "paused"},
], ids=["id-without-type", "unknown-type", "unknown-action"])
def test_invalid_audit_calls_are_rejected(admin, kwargs):
    with pytest.raises(ValueError):
        ra.get_revive_audit_log(admin, **kwargs)


def test_freshness_reports_revive_system_state(admin):
    # Reflects the dev install itself: Revive 6.0.8 with the Geo plugin, statistics
    # maintenance never run.
    system = ct.get_data_freshness(admin, "revive").system
    assert system["revive_version"] == "6.0.8" and "Geo" in system["plugins"]
    assert system["statistics_maintenance"]["status"] == "never_run"
