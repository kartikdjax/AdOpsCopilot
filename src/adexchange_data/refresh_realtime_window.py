"""
Refreshes ONLY the raw auction tables (ax_bid_requests/responses/
impressions/clicks), anchored to the current moment - fixes the "real-time
health shows zero activity" issue that happens once the originally-loaded
raw window ages past `now() - N minutes`.

Uses the SAME seed as load_adexchange_data.py's default, so ad_unit_id/
campaign_id values line up with whatever's already in ax_ad_units and
ax_dsp_campaigns - this does NOT touch the hourly history or dimension
tables, only the short-lived raw tables.

Run this right before testing get_realtime_exchange_health, or on a timer
(cron/systemd) if you want it to stay "live" continuously during a demo.

Run: python -m src.adexchange_data.refresh_realtime_window --raw-hours 3
"""
from __future__ import annotations

import argparse
import logging
import sys

import clickhouse_connect

from src.adexchange_data.generate_adexchange_data import (
    generate_ad_units, generate_campaigns, generate_demand_partners,
    generate_raw_recent_window, generate_supply_partners,
)
from src.adexchange_data.load_guard import UnsafeDatabaseError, ensure_safe_to_load
from src.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RAW_TABLES = ["ax_bid_requests", "ax_bid_responses", "ax_impressions", "ax_clicks"]


def refresh(host: str, port: int, database: str, username: str, password: str,
            raw_hours: int, seed: int) -> None:
    client = clickhouse_connect.get_client(
        host=host, port=port, database=database, username=username, password=password,
    )
    refresh_into(client, database, raw_hours, seed)


def refresh_into(client, database: str, raw_hours: int, seed: int) -> None:
    ensure_safe_to_load(client, database)

    supply_partners = generate_supply_partners(seed=seed)
    ad_units = generate_ad_units(supply_partners, seed=seed)
    demand_partners = generate_demand_partners(seed=seed)
    campaigns = generate_campaigns(demand_partners, seed=seed)

    logger.info("Clearing existing raw data (it's about to be replaced with a fresh window)...")
    for table in RAW_TABLES:
        client.command(f"TRUNCATE TABLE {database}.{table}")

    logger.info("Generating a fresh %d-hour raw window anchored to now...", raw_hours)
    raw = generate_raw_recent_window(ad_units, campaigns, hours=raw_hours, seed=seed)

    for table in RAW_TABLES:
        df = raw[table]
        if df.empty:
            logger.warning("No rows generated for %s", table)
            continue
        client.insert_df(table, df)
        logger.info("Loaded %s rows into %s", f"{len(df):,}", table)

    logger.info("Done. Real-time queries covering the last %d hours will now return data.", raw_hours)


if __name__ == "__main__":
    settings = get_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=settings.clickhouse_host)
    parser.add_argument("--port", type=int, default=settings.clickhouse_port)
    parser.add_argument("--database", default="adexchange")
    parser.add_argument("--username", default=settings.clickhouse_username)
    parser.add_argument("--password", default=settings.clickhouse_password)
    parser.add_argument("--raw-hours", type=int, default=3)
    parser.add_argument("--seed", type=int, default=11,
                         help="Must match the seed used when the dimension tables were loaded")
    args = parser.parse_args()

    try:
        refresh(args.host, args.port, args.database, args.username, args.password,
                args.raw_hours, args.seed)
    except UnsafeDatabaseError as e:
        logger.error("Refusing to refresh: %s", e)
        sys.exit(1)
