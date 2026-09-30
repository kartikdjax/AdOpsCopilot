"""load_guard refuses to let the Revive loader overwrite a database that
isn't a marked, synthetic-only Copilot database. Runs against in-memory
SQLite with just the tables the guard reads."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from src.revive_data.load_guard import (
    MARKER_TABLE, UnsafeDatabaseError, claim, ensure_safe_to_load, is_marked,
)

DB = "revive_test"


@pytest.fixture
def conn():
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE rv_clients (clientname TEXT)"))
        c.execute(text("CREATE TABLE rv_affiliates (name TEXT)"))
        c.execute(text("CREATE TABLE rv_campaigns (campaignname TEXT)"))
        c.execute(text("CREATE TABLE rv_zones (zonename TEXT)"))
        c.execute(text("CREATE TABLE rv_banners (bannerid INTEGER)"))
        c.execute(text("CREATE TABLE rv_data_summary_ad_hourly (ad_id INTEGER)"))
        c.execute(text("INSERT INTO rv_clients VALUES ('Advertiser_1')"))
        c.execute(text("INSERT INTO rv_affiliates VALUES ('Website_1')"))
        c.execute(text("INSERT INTO rv_campaigns VALUES ('Advertiser_1_Campaign_1')"))
        c.execute(text("INSERT INTO rv_zones VALUES ('Zone_1_healthy')"))
        yield c


def test_unmarked_database_is_refused(conn):
    with pytest.raises(UnsafeDatabaseError, match="not marked"):
        ensure_safe_to_load(conn, DB)


def test_claimed_synthetic_database_is_accepted(conn):
    claim(conn, DB, confirm=DB)
    assert is_marked(conn)
    ensure_safe_to_load(conn, DB)


def test_claim_is_idempotent(conn):
    claim(conn, DB, confirm=DB)
    claim(conn, DB, confirm=DB)
    assert conn.execute(text(f"SELECT COUNT(*) FROM {MARKER_TABLE}")).scalar() == 1


def test_claim_must_name_the_target_database(conn):
    with pytest.raises(UnsafeDatabaseError, match="doesn't match"):
        claim(conn, DB, confirm="some_other_db")
    assert not is_marked(conn)


def test_claim_refuses_database_with_real_rows(conn):
    conn.execute(text("INSERT INTO rv_clients VALUES ('NB Test Advertiser')"))
    with pytest.raises(UnsafeDatabaseError, match="NB Test Advertiser"):
        claim(conn, DB, confirm=DB)
    assert not is_marked(conn)


def test_marked_database_with_real_rows_is_refused(conn):
    claim(conn, DB, confirm=DB)
    conn.execute(text("INSERT INTO rv_zones VALUES ('Homepage leaderboard')"))
    with pytest.raises(UnsafeDatabaseError, match="Homepage leaderboard"):
        ensure_safe_to_load(conn, DB)


def test_non_revive_database_is_refused():
    with create_engine("sqlite://").connect() as c:
        with pytest.raises(UnsafeDatabaseError, match="doesn't look like a Revive database"):
            ensure_safe_to_load(c, DB)
