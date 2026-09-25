"""
Loads the AdExchange synthetic dataset (raw recent window + hourly
history) into ClickHouse.

Run: python -m src.adexchange_data.load_adexchange_data --hourly-days 14 --raw-hours 3
"""
from __future__ import annotations

import argparse
import logging

import clickhouse_connect

from src.adexchange_data.generate_adexchange_data import generate_adexchange_dataset

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RAW_TABLES = ["ax_bid_requests", "ax_bid_responses", "ax_impressions", "ax_clicks"]
DIM_TABLES = ["ax_supply_partners", "ax_ad_units", "ax_demand_partners", "ax_dsp_campaigns"]


def load_dataset(host: str, port: int, database: str, username: str, password: str,
                  hourly_days: int, raw_hours: int) -> None:
    client = clickhouse_connect.get_client(
        host=host, port=port, database=database, username=username, password=password,
    )

    logger.info("Generating AdExchange dataset: hourly_days=%d, raw_hours=%d", hourly_days, raw_hours)
    data = generate_adexchange_dataset(hourly_days=hourly_days, raw_hours=raw_hours)

    for table in DIM_TABLES:
        logger.info("Loading %d rows into %s...", len(data[table]), table)
        client.insert_df(table, data[table])

    hourly = data["ax_hourly_stats"]
    logger.info("Loading %s rows into ax_hourly_stats...", f"{len(hourly):,}")
    client.insert_df("ax_hourly_stats", hourly)

    for table in RAW_TABLES:
        df = data[table]
        if df.empty:
            logger.warning("No rows generated for %s - skipping", table)
            continue
        logger.info("Loading %s rows into %s...", f"{len(df):,}", table)
        chunk_size = 200_000
        for start in range(0, len(df), chunk_size):
            client.insert_df(table, df.iloc[start:start + chunk_size])

    logger.info("Done. Verify with: SELECT count() FROM adexchange.ax_hourly_stats")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--database", default="adexchange")
    parser.add_argument("--username", default="default")
    parser.add_argument("--password", default="dev_local_password")
    parser.add_argument("--hourly-days", type=int, default=14)
    parser.add_argument("--raw-hours", type=int, default=3)
    args = parser.parse_args()

    load_dataset(args.host, args.port, args.database, args.username, args.password,
                 args.hourly_days, args.raw_hours)
