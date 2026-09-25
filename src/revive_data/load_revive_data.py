"""
Loads the Revive-schema synthetic dataset into the real local Revive
Adserver MySQL database (revive608), replacing the earlier ClickHouse
mirror for the revive domain.

Run: python -m src.revive_data.load_revive_data --days 30
"""
from __future__ import annotations

import argparse
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from src.config import get_settings
from src.revive_data.admin_fixtures import SYNTHETIC_ID_START
from src.revive_data.generate_revive_data import SYNTHETIC_MANAGER_START, generate_revive_dataset

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


def load_dataset(host: str, port: int, database: str, username: str, password: str,
                  days: int) -> None:
    # URL.create (not an f-string) because the password can contain characters
    # like "@" that would otherwise be misparsed as the userinfo/host separator.
    engine = create_engine(URL.create(
        "mysql+pymysql", username=username, password=password, host=host, port=port, database=database,
    ))

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


if __name__ == "__main__":
    settings = get_settings()  # defaults come from .env, like the app's own connection
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=settings.mysql_host)
    parser.add_argument("--port", type=int, default=settings.mysql_port)
    parser.add_argument("--database", default=settings.mysql_database)
    parser.add_argument("--username", default=settings.mysql_username)
    parser.add_argument("--password", default=settings.mysql_password)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    load_dataset(args.host, args.port, args.database, args.username, args.password, args.days)
