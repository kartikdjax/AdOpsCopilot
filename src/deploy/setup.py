"""
First-time (and repeatable) setup of a server's data:

1. Revive MySQL database: if it has no rv_ tables, create the tables and
   Revive's base rows (src/revive_data/revive_*.sql) and mark it
   Copilot-owned; then load the synthetic data.
2. ClickHouse: if the exchange database doesn't exist, create it from
   adexchange_schema.sql and mark it; then load the synthetic data.
3. Seed the knowledge base.

Both databases are checked before anything is written: a MySQL database
with Revive tables but no Copilot marker, or an existing exchange database
without one, stops setup with nothing changed.

Run: python -m src.deploy.setup
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import clickhouse_connect
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.engine import URL

from src.adexchange_data import load_guard as exchange_guard
from src.adexchange_data.load_adexchange_data import load_into as load_exchange
from src.config import get_settings
from src.revive_data import load_guard as revive_guard
from src.revive_data.load_revive_data import connection_defaults, load_dataset as load_revive

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SRC = Path(__file__).resolve().parents[1]
REVIVE_SCHEMA = SRC / "revive_data" / "revive_mysql_schema.sql"
REVIVE_BASE_ROWS = SRC / "revive_data" / "revive_base_rows.sql"
EXCHANGE_SCHEMA = SRC / "adexchange_data" / "adexchange_schema.sql"
EXCHANGE_DATABASE = "adexchange"  # the app's queries name it directly


class SetupRefused(RuntimeError):
    """A target database exists but isn't Copilot-owned."""


@dataclass(frozen=True)
class Plan:
    bootstrap_revive: bool
    create_exchange: bool


def _statements(sql: str) -> list[str]:
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    return [s.strip() for s in body.split(";\n") if s.strip().rstrip(";").strip()]


def _revive_tables(conn: Connection) -> list[str]:
    return [t for t in inspect(conn).get_table_names() if t.startswith("rv_")]


def check_revive(conn: Connection, database: str) -> bool:
    """True if the database needs bootstrapping. Raises if it's someone else's."""
    if not _revive_tables(conn):
        return True
    if not revive_guard.is_marked(conn):
        raise SetupRefused(f"MySQL database {database} already has Revive tables and no Copilot marker; "
                           f"setup won't touch it. Use an empty database, or claim this one with "
                           f"load_revive_data --claim {database} if its data may be replaced.")
    return False


def bootstrap_revive(conn: Connection, database: str) -> None:
    # Revive's tables default some datetimes to '0000-00-00 00:00:00', which
    # MySQL 8's default NO_ZERO_DATE / strict mode rejects. Revive's own
    # installer relaxes the mode the same way; this affects this session only.
    conn.execute(text("SET SESSION sql_mode = 'NO_ENGINE_SUBSTITUTION'"))
    for sql_file in (REVIVE_SCHEMA, REVIVE_BASE_ROWS):
        for statement in _statements(sql_file.read_text()):
            conn.execute(text(statement))
    revive_guard.claim(conn, database, database)
    logger.info("Created the Revive tables and base rows in %s and marked it Copilot-owned.", database)


def check_exchange(client, database: str) -> bool:
    """True if the database must be created. Raises if it exists and isn't ours."""
    if not exchange_guard.database_exists(client, database):
        return True
    if not exchange_guard.is_marked(client, database):
        raise SetupRefused(f"ClickHouse database {database} already exists and isn't Copilot-owned; "
                           f"setup won't touch it. Claim it with load_adexchange_data --claim {database} "
                           f"if its ax_ tables may be replaced.")
    return False


def create_exchange(client, database: str) -> None:
    schema = EXCHANGE_SCHEMA.read_text().replace(f"{EXCHANGE_DATABASE}.", f"{database}.").replace(
        f"CREATE DATABASE IF NOT EXISTS {EXCHANGE_DATABASE}", f"CREATE DATABASE IF NOT EXISTS {database}")
    for statement in _statements(schema):
        client.command(statement)
    exchange_guard.mark(client, database)
    logger.info("Created ClickHouse database %s and marked it Copilot-owned.", database)


def run(revive_days: int = 30, hourly_days: int = 14, raw_hours: int = 3,
        exchange_database: str = EXCHANGE_DATABASE, seed_knowledge_base: bool = True) -> None:
    settings = get_settings()
    mysql = connection_defaults()
    engine = create_engine(URL.create("mysql+pymysql", username=mysql["username"], password=mysql["password"],
                                      host=mysql["host"], port=mysql["port"], database=mysql["database"]))
    clickhouse = clickhouse_connect.get_client(host=settings.clickhouse_host, port=settings.clickhouse_port,
                                               username=settings.clickhouse_username,
                                               password=settings.clickhouse_password)

    # Check both before writing anything.
    with engine.connect() as conn:
        plan = Plan(bootstrap_revive=check_revive(conn, mysql["database"]),
                    create_exchange=check_exchange(clickhouse, exchange_database))

    if plan.bootstrap_revive:
        with engine.begin() as conn:
            bootstrap_revive(conn, mysql["database"])
    load_revive(mysql["host"], mysql["port"], mysql["database"], mysql["username"], mysql["password"], revive_days)

    if plan.create_exchange:
        create_exchange(clickhouse, exchange_database)
    load_exchange(clickhouse_connect.get_client(host=settings.clickhouse_host, port=settings.clickhouse_port,
                                                database=exchange_database,
                                                username=settings.clickhouse_username,
                                                password=settings.clickhouse_password),
                  exchange_database, hourly_days, raw_hours)

    if seed_knowledge_base:
        from src.rag.load_seed_documents import main as seed  # loads the embedding model
        seed()
    logger.info("Setup complete.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create and load the Copilot's databases")
    parser.add_argument("--revive-days", type=int, default=30)
    parser.add_argument("--hourly-days", type=int, default=14)
    parser.add_argument("--raw-hours", type=int, default=3)
    parser.add_argument("--skip-knowledge-base", action="store_true")
    args = parser.parse_args(argv)
    try:
        run(args.revive_days, args.hourly_days, args.raw_hours,
            seed_knowledge_base=not args.skip_knowledge_base)
    except (SetupRefused, revive_guard.UnsafeDatabaseError, exchange_guard.UnsafeDatabaseError) as e:
        logger.error("Setup stopped: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
