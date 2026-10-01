"""
Stops the exchange loaders from writing to a ClickHouse database the
Copilot doesn't own. The loader truncates and reloads every ax_ table, and
a shared ClickHouse server (like the deployment's) holds other people's
databases, so the target must carry the Copilot marker table first.

A database gets the marker when setup creates it (src.deploy.setup), or
explicitly with: python -m src.adexchange_data.load_adexchange_data --claim adexchange
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

MARKER_TABLE = "copilot_synthetic_marker"
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class UnsafeDatabaseError(RuntimeError):
    """The target ClickHouse database is not one the loaders may overwrite."""


def _checked(database: str) -> str:
    if not _NAME.fullmatch(database):
        raise UnsafeDatabaseError(f"Invalid ClickHouse database name {database!r}.")
    return database


def database_exists(client: Any, database: str) -> bool:
    return bool(int(client.command(f"EXISTS DATABASE {_checked(database)}")))


def is_marked(client: Any, database: str) -> bool:
    return database_exists(client, database) and bool(
        int(client.command(f"EXISTS TABLE {_checked(database)}.{MARKER_TABLE}")))


def ensure_safe_to_load(client: Any, database: str) -> None:
    if not is_marked(client, database):
        raise UnsafeDatabaseError(
            f"ClickHouse database {database} is not marked as a Copilot synthetic database, so the loader "
            f"won't touch it. If every ax_ table in it may be replaced, mark it once with: "
            f"python -m src.adexchange_data.load_adexchange_data --claim {database}")


def mark(client: Any, database: str) -> None:
    """Create the marker table in an existing database (idempotent)."""
    db = _checked(database)
    if is_marked(client, db):
        return
    client.command(f"CREATE TABLE IF NOT EXISTS {db}.{MARKER_TABLE} "
                   f"(claimed_at DateTime, note String) ENGINE = TinyLog")
    client.command(f"INSERT INTO {db}.{MARKER_TABLE} VALUES "
                   f"('{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}', "
                   f"'Synthetic data owned by AdOps Copilot; the exchange loaders may replace it.')")


def claim(client: Any, database: str, confirm: str) -> None:
    """Mark an existing database. `confirm` must repeat its name."""
    if confirm != database:
        raise UnsafeDatabaseError(f"--claim {confirm} doesn't match the target database {database}; "
                                  f"nothing was changed.")
    if not database_exists(client, database):
        raise UnsafeDatabaseError(f"ClickHouse database {database} doesn't exist; run setup to create it.")
    mark(client, database)
