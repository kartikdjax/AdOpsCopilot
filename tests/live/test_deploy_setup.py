"""Setup against the local MySQL and ClickHouse, using throwaway databases
(dropped afterwards): an empty server is bootstrapped and loaded, a second
run doesn't duplicate data, and someone else's database is refused.
Also covers the exchange loader replacing rather than appending."""
from __future__ import annotations

import clickhouse_connect
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from src.adexchange_data import load_guard as exchange_guard
from src.config import get_settings
from src.deploy import setup
from src.revive_data import load_guard as revive_guard

REVIVE_DB = "copilot_revive_test"
FOREIGN_DB = "copilot_revive_foreign_test"
EXCHANGE_DB = "copilot_test_adexchange"
UNUSED_EXCHANGE_DB = "copilot_test_adexchange_unused"


def _server_engine(database: str | None = None):
    s = get_settings()
    return create_engine(URL.create("mysql+pymysql", username=s.mysql_username, password=s.mysql_password,
                                    host=s.mysql_host, port=s.mysql_port, database=database))


def _clickhouse():
    s = get_settings()
    return clickhouse_connect.get_client(host=s.clickhouse_host, port=s.clickhouse_port,
                                         username=s.clickhouse_username, password=s.clickhouse_password)


def _drop_all():
    with _server_engine().begin() as conn:
        for db in (REVIVE_DB, FOREIGN_DB):
            conn.execute(text(f"DROP DATABASE IF EXISTS {db}"))
    ch = _clickhouse()
    for db in (EXCHANGE_DB, UNUSED_EXCHANGE_DB):
        ch.command(f"DROP DATABASE IF EXISTS {db}")


@pytest.fixture
def servers(monkeypatch):
    try:
        _drop_all()
    except Exception as e:  # noqa: BLE001 - no local MySQL/ClickHouse means skip
        pytest.skip(f"local MySQL or ClickHouse not reachable: {type(e).__name__}: {str(e)[:120]}")
    for name in ("MYSQL_LOADER_USERNAME", "MYSQL_LOADER_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    def use(database: str) -> None:
        with _server_engine().begin() as conn:
            conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {database}"))
        monkeypatch.setenv("MYSQL_DATABASE", database)
        get_settings.cache_clear()

    yield use
    get_settings.cache_clear()
    _drop_all()


def _counts():
    with _server_engine(REVIVE_DB).connect() as conn:
        revive = {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                  for t in ("rv_data_summary_ad_hourly", "rv_clients", "rv_agency", "rv_users")}
    ch = _clickhouse()
    exchange = {t: int(ch.command(f"SELECT count() FROM {EXCHANGE_DB}.{t}"))
                for t in ("ax_hourly_stats", "ax_supply_partners", "ax_bid_requests")}
    return revive, exchange


def test_empty_server_then_rerun(servers):
    servers(REVIVE_DB)
    setup.run(revive_days=7, hourly_days=3, raw_hours=1, exchange_database=EXCHANGE_DB,
              seed_knowledge_base=False)

    with _server_engine(REVIVE_DB).connect() as conn:
        assert revive_guard.is_marked(conn)
        admin = conn.execute(text("SELECT username, password FROM rv_users WHERE user_id = 1")).one()
    assert admin.username == "admin" and not admin.password.startswith("$2")
    assert exchange_guard.is_marked(_clickhouse(), EXCHANGE_DB)

    first = _counts()
    assert all(first[0].values()) and all(first[1].values())

    setup.run(revive_days=7, hourly_days=3, raw_hours=1, exchange_database=EXCHANGE_DB,
              seed_knowledge_base=False)
    second = _counts()
    # Same generator inputs -> the same row counts, not double.
    assert second[1] == first[1]
    assert second[0]["rv_clients"] == first[0]["rv_clients"]
    assert second[0]["rv_agency"] == first[0]["rv_agency"]
    assert second[0]["rv_data_summary_ad_hourly"] < 1.5 * first[0]["rv_data_summary_ad_hourly"]


def test_foreign_revive_database_is_refused_before_any_change(servers):
    servers(FOREIGN_DB)
    with _server_engine(FOREIGN_DB).begin() as conn:
        conn.execute(text("CREATE TABLE rv_clients (clientid INT PRIMARY KEY, clientname VARCHAR(255))"))
        conn.execute(text("INSERT INTO rv_clients VALUES (1, 'Real Advertiser')"))

    with pytest.raises(setup.SetupRefused, match=FOREIGN_DB):
        setup.run(revive_days=7, hourly_days=3, raw_hours=1, exchange_database=UNUSED_EXCHANGE_DB,
                  seed_knowledge_base=False)

    with _server_engine(FOREIGN_DB).connect() as conn:
        assert conn.execute(text("SELECT clientname FROM rv_clients")).scalars().all() == ["Real Advertiser"]
        assert not revive_guard.is_marked(conn)
    assert not exchange_guard.database_exists(_clickhouse(), UNUSED_EXCHANGE_DB)


def test_foreign_exchange_database_is_refused(servers):
    servers(REVIVE_DB)
    _clickhouse().command(f"CREATE DATABASE {EXCHANGE_DB}")
    with pytest.raises(setup.SetupRefused, match=EXCHANGE_DB):
        setup.run(revive_days=7, hourly_days=3, raw_hours=1, exchange_database=EXCHANGE_DB,
                  seed_knowledge_base=False)
    with _server_engine(REVIVE_DB).connect() as conn:
        assert conn.execute(text("SHOW TABLES")).all() == []  # nothing bootstrapped
