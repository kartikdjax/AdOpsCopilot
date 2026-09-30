"""Revive maintenance status (ok / overdue / never run) from a fake client -
states the dev install can't produce without writing to Revive's own
maintenance tables."""
from __future__ import annotations

import pandas as pd

from src.semantic import revive_admin as ra


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


def test_maintenance_ok():
    status = ra.get_system_status(FakeStatusClient(35, 40))
    assert status.statistics_maintenance.status == "ok" and not status.warnings


def test_maintenance_overdue():
    status = ra.get_system_status(FakeStatusClient(35, 300))
    assert status.priority_maintenance.status == "overdue" and len(status.warnings) == 1


def test_maintenance_never_run():
    assert len(ra.get_system_status(FakeStatusClient(None, None)).warnings) == 2
