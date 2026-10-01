"""
Loads the AdExchange synthetic dataset (raw recent window + hourly
history) into ClickHouse.

Replaces every table it writes (truncate, then insert), so it can be re-run.
Refuses a database without the Copilot marker (see load_guard.py); connection
settings come from .env / the environment (CLICKHOUSE_*).

Run: python -m src.adexchange_data.load_adexchange_data --hourly-days 14 --raw-hours 3
     python -m src.adexchange_data.load_adexchange_data --claim adexchange   # mark an existing database first
"""
from __future__ import annotations

import argparse
import logging
import sys

import clickhouse_connect

from src.adexchange_data.generate_adexchange_data import generate_adexchange_dataset
from src.adexchange_data.load_guard import UnsafeDatabaseError, claim, ensure_safe_to_load
from src.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RAW_TABLES = ["ax_bid_requests", "ax_bid_responses", "ax_impressions", "ax_clicks"]
DIM_TABLES = ["ax_supply_partners", "ax_ad_units", "ax_demand_partners", "ax_dsp_campaigns"]
HOURLY_TABLE = "ax_hourly_stats"


def load_dataset(host: str, port: int, database: str, username: str, password: str,
                  hourly_days: int, raw_hours: int) -> None:
    client = clickhouse_connect.get_client(
        host=host, port=port, database=database, username=username, password=password,
    )
    load_into(client, database, hourly_days, raw_hours)


def load_into(client, database: str, hourly_days: int, raw_hours: int) -> None:
    ensure_safe_to_load(client, database)

    logger.info("Generating AdExchange dataset: hourly_days=%d, raw_hours=%d", hourly_days, raw_hours)
    data = generate_adexchange_dataset(hourly_days=hourly_days, raw_hours=raw_hours)

    # Replace, don't append: a second run would otherwise duplicate everything.
    for table in [*DIM_TABLES, HOURLY_TABLE, *RAW_TABLES]:
        client.command(f"TRUNCATE TABLE IF EXISTS {database}.{table}")

    for table in DIM_TABLES:
        logger.info("Loading %d rows into %s...", len(data[table]), table)
        client.insert_df(table, data[table])

    hourly = data[HOURLY_TABLE]
    logger.info("Loading %s rows into %s...", f"{len(hourly):,}", HOURLY_TABLE)
    client.insert_df(HOURLY_TABLE, hourly)

    for table in RAW_TABLES:
        df = data[table]
        if df.empty:
            logger.warning("No rows generated for %s - skipping", table)
            continue
        logger.info("Loading %s rows into %s...", f"{len(df):,}", table)
        chunk_size = 200_000
        for start in range(0, len(df), chunk_size):
            client.insert_df(table, df.iloc[start:start + chunk_size])

    logger.info("Done. Verify with: SELECT count() FROM %s.%s", database, HOURLY_TABLE)


if __name__ == "__main__":
    settings = get_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=settings.clickhouse_host)
    parser.add_argument("--port", type=int, default=settings.clickhouse_port)
    parser.add_argument("--database", default="adexchange")
    parser.add_argument("--username", default=settings.clickhouse_username)
    parser.add_argument("--password", default=settings.clickhouse_password)
    parser.add_argument("--hourly-days", type=int, default=14)
    parser.add_argument("--raw-hours", type=int, default=3)
    parser.add_argument("--claim", metavar="DATABASE",
                        help="mark an existing DATABASE (must equal the target) as Copilot-owned, then load")
    args = parser.parse_args()

    try:
        if args.claim is not None:
            claim(clickhouse_connect.get_client(host=args.host, port=args.port, username=args.username,
                                                password=args.password), args.database, args.claim)
        load_dataset(args.host, args.port, args.database, args.username, args.password,
                     args.hourly_days, args.raw_hours)
    except UnsafeDatabaseError as e:
        logger.error("Refusing to load: %s", e)
        sys.exit(1)
