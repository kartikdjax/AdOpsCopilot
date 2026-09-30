"""Live tests read the local revive608 database and ClickHouse. They skip,
with the reason, when either isn't reachable, when revive608 isn't a
claimed synthetic database, or when its data is too old: the planted
problems are relative to load time (a campaign "expiring in 3 days"
stops expiring after 3 days), so reload before running:

    python -m src.revive_data.load_revive_data --days 30
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta

import pytest

# The API tests must not touch the real Copilot user database. Set before
# anything imports src.api.db, which reads it at import time.
os.environ.setdefault("COPILOT_DB_PATH", os.path.join(tempfile.mkdtemp(), "copilot_test.db"))

MAX_DATA_AGE = timedelta(hours=24)


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/live/" in item.nodeid:
            item.add_marker(pytest.mark.live)


@pytest.fixture(scope="session")
def admin():
    from src.config import get_settings
    from src.revive_data.load_guard import is_marked
    from src.semantic.analytics_client import AnalyticsClient

    try:
        client = AnalyticsClient(get_settings())
        with client._mysql_engine.connect() as conn:
            marked = is_marked(conn)
        last = client.raw_query("SELECT MAX(date_time) AS last FROM rv_data_summary_ad_hourly", {},
                                domain="revive")["last"].iloc[0]
    except Exception as e:  # noqa: BLE001 - any connection failure means "not available here"
        pytest.skip(f"live databases not reachable: {type(e).__name__}: {str(e)[:120]}")
    if not marked:
        pytest.skip("revive608 isn't a claimed synthetic database (load_revive_data --claim revive608)")
    if last is None or datetime.utcnow() - last.to_pydatetime() > MAX_DATA_AGE:
        pytest.skip(f"revive608 data last runs to {last}; reload it (load_revive_data --days 30)")
    return client
