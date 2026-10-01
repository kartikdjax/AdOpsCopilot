"""The exchange loaders only write to a Copilot-owned ClickHouse database,
and the full loader replaces its tables instead of appending."""
from __future__ import annotations

import pytest

from src.adexchange_data import load_adexchange_data as loader
from src.adexchange_data import load_guard, refresh_realtime_window as refresher


class FakeClickHouse:
    """Records commands and inserts; answers EXISTS from a set of names."""

    def __init__(self, existing: set[str]):
        self.existing = set(existing)
        self.log: list[tuple[str, str]] = []

    def command(self, sql: str):
        self.log.append(("command", sql))
        if sql.startswith("EXISTS DATABASE "):
            return int(sql.split()[-1] in self.existing)
        if sql.startswith("EXISTS TABLE "):
            return int(sql.split()[-1] in self.existing)
        if sql.startswith("CREATE TABLE IF NOT EXISTS"):
            self.existing.add(sql.split()[5])
        return None

    def insert_df(self, table, df):
        self.log.append(("insert", table))


MARKED = {"adexchange", f"adexchange.{load_guard.MARKER_TABLE}"}


def test_loader_refuses_unmarked_database():
    client = FakeClickHouse({"adexchange"})
    with pytest.raises(load_guard.UnsafeDatabaseError, match="not marked"):
        loader.load_into(client, "adexchange", hourly_days=1, raw_hours=1)
    assert not [e for e in client.log if e[0] == "insert" or "TRUNCATE" in e[1]]


def test_refresh_refuses_unmarked_database():
    client = FakeClickHouse({"adexchange"})
    with pytest.raises(load_guard.UnsafeDatabaseError):
        refresher.refresh_into(client, "adexchange", raw_hours=1, seed=11)
    assert not [e for e in client.log if e[0] == "insert" or "TRUNCATE" in e[1]]


def test_loader_truncates_every_table_before_inserting():
    client = FakeClickHouse(MARKED)
    loader.load_into(client, "adexchange", hourly_days=1, raw_hours=1)
    first_insert = next(i for i, e in enumerate(client.log) if e[0] == "insert")
    truncated = {e[1].split()[-1] for e in client.log[:first_insert] if "TRUNCATE" in e[1]}
    expected = {f"adexchange.{t}" for t in [*loader.DIM_TABLES, loader.HOURLY_TABLE, *loader.RAW_TABLES]}
    assert truncated == expected
    assert not [e for e in client.log[first_insert:] if "TRUNCATE" in e[1]]


def test_claim_marks_an_existing_database_once():
    client = FakeClickHouse({"adexchange"})
    load_guard.claim(client, "adexchange", "adexchange")
    load_guard.claim(client, "adexchange", "adexchange")
    assert load_guard.is_marked(client, "adexchange")
    assert len([e for e in client.log if e[1].startswith("INSERT INTO")]) == 1


def test_claim_needs_matching_name_and_existing_database():
    with pytest.raises(load_guard.UnsafeDatabaseError, match="doesn't match"):
        load_guard.claim(FakeClickHouse({"adexchange"}), "adexchange", "other")
    with pytest.raises(load_guard.UnsafeDatabaseError, match="doesn't exist"):
        load_guard.claim(FakeClickHouse(set()), "adexchange", "adexchange")


def test_invalid_database_name_rejected():
    with pytest.raises(load_guard.UnsafeDatabaseError, match="Invalid"):
        load_guard.is_marked(FakeClickHouse(set()), "adexchange; DROP DATABASE x")
