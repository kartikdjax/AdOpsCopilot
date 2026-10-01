"""
Loads the Revive-schema synthetic dataset into the real local Revive
Adserver MySQL database (revive608), replacing the earlier ClickHouse
mirror for the revive domain.

Run: python -m src.revive_data.load_revive_data --days 30

The loader refuses any database that isn't marked as a Copilot synthetic
one (see load_guard.py). Mark a database once with --claim <database>.
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from src.config import get_settings
from src.revive_data.admin_fixtures import SYNTHETIC_ID_START
from src.revive_data.generate_revive_data import SYNTHETIC_MANAGER_START, generate_revive_dataset
from src.revive_data.load_guard import UnsafeDatabaseError, claim, ensure_safe_to_load

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_DIMENSION_TABLES = ["rv_affiliates", "rv_clients", "rv_campaigns", "rv_banners", "rv_zones"]
# rv_agency is NOT truncated: it holds the install's own Default manager
# (tied to a login account). Only synthetic managers are replaced.
_MANAGER_TABLE = "rv_agency"
# Links and targeting are fully synthetic - truncated like dimensions.
_LINK_TABLES = ["rv_ad_zone_assoc", "rv_placement_zone_assoc", "rv_acls"]
# These also hold the real admin login, so only synthetic IDs are replaced.
_SHARED_TABLES = {"rv_accounts": "account_id", "rv_users": "user_id", "rv_account_user_assoc": "user_id"}
# Revive keeps appending real audit rows, so synthetic ones are identified
# by their (synthetic, never-able-to-log-in) author rather than by ID.
_AUDIT_TABLE = "rv_audit"
_FACT_TABLE = "rv_data_summary_ad_hourly"


def _engine(host: str, port: int, database: str, username: str, password: str):
    # URL.create (not an f-string) because the password can contain characters
    # like "@" that would otherwise be misparsed as the userinfo/host separator.
    return create_engine(URL.create(
        "mysql+pymysql", username=username, password=password, host=host, port=port, database=database,
    ))


def claim_database(host: str, port: int, database: str, username: str, password: str,
                   confirm: str) -> None:
    with _engine(host, port, database, username, password).begin() as conn:
        claim(conn, database, confirm)
    logger.info("%s is marked as a Copilot synthetic database.", database)


def load_dataset(host: str, port: int, database: str, username: str, password: str,
                  days: int) -> None:
    engine = _engine(host, port, database, username, password)
    with engine.connect() as conn:
        ensure_safe_to_load(conn, database)

    logger.info("Generating Revive-schema dataset: days=%d", days)
    data = generate_revive_dataset(total_days=days)

    with engine.begin() as conn:
        for table in [*_DIMENSION_TABLES, *_LINK_TABLES, _FACT_TABLE]:
            conn.execute(text(f"TRUNCATE TABLE {table}"))
        conn.execute(text(f"DELETE FROM {_MANAGER_TABLE} WHERE agencyid >= :start"),
                     {"start": SYNTHETIC_MANAGER_START})
        for table, id_column in _SHARED_TABLES.items():
            conn.execute(text(f"DELETE FROM {table} WHERE {id_column} >= :start"),
                         {"start": SYNTHETIC_ID_START})
        conn.execute(text(f"DELETE FROM {_AUDIT_TABLE} WHERE userid >= :start"), {"start": SYNTHETIC_ID_START})

    logger.info("Loading %d synthetic managers into %s...", len(data[_MANAGER_TABLE]), _MANAGER_TABLE)
    data[_MANAGER_TABLE].to_sql(_MANAGER_TABLE, engine, if_exists="append", index=False, method="multi")

    for table in [*_DIMENSION_TABLES, *_LINK_TABLES, *_SHARED_TABLES, _AUDIT_TABLE]:
        logger.info("Loading %d rows into %s...", len(data[table]), table)
        data[table].to_sql(table, engine, if_exists="append", index=False, method="multi", chunksize=1000)

    stats = data[_FACT_TABLE]
    logger.info("Loading %s rows into %s...", f"{len(stats):,}", _FACT_TABLE)
    chunk_size = 5_000
    for start in range(0, len(stats), chunk_size):
        chunk = stats.iloc[start:start + chunk_size]
        chunk.to_sql(_FACT_TABLE, engine, if_exists="append", index=False, method="multi")
        logger.info("  inserted rows %d-%d / %d", start, min(start + chunk_size, len(stats)), len(stats))

    logger.info("Done. Verify with: SELECT count() FROM %s.%s", database, _FACT_TABLE)


def connection_defaults() -> dict[str, str | int]:
    """Where the loader connects by default: the app's MySQL host and database,
    as the loader user when one is configured (MYSQL_LOADER_*), else the app user."""
    settings = get_settings()
    username, password = settings.loader_mysql_credentials
    return {"host": settings.mysql_host, "port": settings.mysql_port, "database": settings.mysql_database,
            "username": username, "password": password}


if __name__ == "__main__":
    defaults = connection_defaults()
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=defaults["host"])
    parser.add_argument("--port", type=int, default=defaults["port"])
    parser.add_argument("--database", default=defaults["database"])
    parser.add_argument("--username", default=defaults["username"])
    parser.add_argument("--password", default=defaults["password"])
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--claim", metavar="DATABASE",
                        help="mark DATABASE (must equal the target) as synthetic, then load into it")
    args = parser.parse_args()

    try:
        if args.claim is not None:
            claim_database(args.host, args.port, args.database, args.username, args.password, args.claim)
        load_dataset(args.host, args.port, args.database, args.username, args.password, args.days)
    except UnsafeDatabaseError as e:
        logger.error("Refusing to load: %s", e)
        sys.exit(1)
