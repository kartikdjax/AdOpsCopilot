"""
Loads synthetic data into a real ClickHouse instance.

Run on your machine (requires a running ClickHouse server + clickhouse-connect):
    pip install clickhouse-connect
    # apply src/data/clickhouse_schema.sql first, via clickhouse-client or a migration tool
    python -m src.data.load_to_clickhouse --days 60 --scale 1.0
"""
from __future__ import annotations

import argparse
import logging

import clickhouse_connect

from src.data.generate_synthetic_data import generate_full_dataset

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_dataset(host: str, port: int, database: str, days: int, scale: float) -> None:
    client = clickhouse_connect.get_client(host=host, port=port, database=database)

    logger.info("Generating synthetic dataset: days=%d, scale=%.2f", days, scale)
    data = generate_full_dataset(total_days=days, scale=scale)

    logger.info("Loading %d advertisers...", len(data["advertisers"]))
    client.insert_df("advertisers", data["advertisers"])

    logger.info("Loading %d campaigns...", len(data["campaigns"]))
    client.insert_df("campaigns", data["campaigns"][
        ["campaign_id", "advertiser_id", "campaign_name", "start_date", "end_date", "daily_budget"]
    ].assign(status="active"))

    events = data["events"]
    logger.info("Loading %s raw events (this is the big one)...", f"{len(events):,}")
    # Chunk the insert - ClickHouse handles large batches well, but chunking
    # keeps memory bounded and gives visible progress on a multi-million-row load.
    chunk_size = 500_000
    for start in range(0, len(events), chunk_size):
        chunk = events.iloc[start:start + chunk_size]
        client.insert_df("ad_events", chunk)
        logger.info("  inserted rows %d-%d / %d", start, min(start + chunk_size, len(events)), len(events))

    logger.info("Done. Verify with: SELECT count() FROM adtech.ad_events")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--database", default="adtech")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--scale", type=float, default=1.0)
    args = parser.parse_args()

    load_dataset(args.host, args.port, args.database, args.days, args.scale)
