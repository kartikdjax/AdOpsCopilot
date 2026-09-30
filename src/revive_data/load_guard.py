"""
Stops load_revive_data from wiping a Revive database that isn't a Copilot
synthetic one. The loader truncates advertisers, campaigns, banners, zones,
websites and stats, so pointing it at a real or shared install by mistake
(a wrong MYSQL_DATABASE in .env, say) would destroy that install's data.

Two checks, both before anything is written:
- the database must carry the Copilot marker table, created only by an
  explicit `--claim <database>` run;
- every row in the tables the loader truncates must look like the
  generator's own rows (its names are fixed patterns like "Advertiser_3").
  This runs on every load, so a row someone added through Revive's UI is
  reported instead of silently deleted.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import Connection, inspect, text

MARKER_TABLE = "copilot_synthetic_marker"

# Name columns the generator fills with fixed patterns (generate_revive_data.py).
# Any other value in these tables was not written by the loader.
_SYNTHETIC_NAMES = {
    "rv_clients": ("clientname", re.compile(r"Advertiser_\d+")),
    "rv_affiliates": ("name", re.compile(r"Website_\d+")),
    "rv_campaigns": ("campaignname", re.compile(r"Advertiser_\d+_Campaign_\d+")),
    "rv_zones": ("zonename", re.compile(r"Zone_\d+_\w+")),
}
_REQUIRED_TABLES = ["rv_clients", "rv_campaigns", "rv_banners", "rv_zones", "rv_affiliates",
                    "rv_data_summary_ad_hourly"]
_MAX_REPORTED_ROWS = 5


class UnsafeDatabaseError(RuntimeError):
    """The target database is not one the loader may overwrite."""


def is_marked(conn: Connection) -> bool:
    return inspect(conn).has_table(MARKER_TABLE)


def foreign_rows(conn: Connection) -> dict[str, list[str]]:
    """Names in the truncated tables that the generator would never write,
    at most a few per table."""
    found: dict[str, list[str]] = {}
    for table, (column, pattern) in _SYNTHETIC_NAMES.items():
        names = conn.execute(text(f"SELECT {column} FROM {table}")).scalars()
        bad = [str(n) for n in names if n is None or not pattern.fullmatch(str(n))]
        if bad:
            found[table] = bad[:_MAX_REPORTED_ROWS]
    return found


def check_revive_schema(conn: Connection, database: str) -> None:
    existing = set(inspect(conn).get_table_names())
    missing = [t for t in _REQUIRED_TABLES if t not in existing]
    if missing:
        raise UnsafeDatabaseError(
            f"{database} doesn't look like a Revive database with the rv_ prefix "
            f"(missing {', '.join(missing)}).")


def check_foreign_rows(conn: Connection, database: str) -> None:
    found = foreign_rows(conn)
    if found:
        detail = "; ".join(f"{t}: {', '.join(repr(n) for n in names)}" for t, names in found.items())
        raise UnsafeDatabaseError(
            f"{database} holds rows the synthetic loader didn't create, and loading would delete them "
            f"({detail}). Remove them or load into a different database.")


def ensure_safe_to_load(conn: Connection, database: str) -> None:
    """Raise UnsafeDatabaseError unless `database` is a marked Copilot
    synthetic database whose truncated tables hold only synthetic rows."""
    check_revive_schema(conn, database)
    if not is_marked(conn):
        raise UnsafeDatabaseError(
            f"{database} is not marked as a Copilot synthetic database, so the loader won't touch it. "
            f"If every advertiser, campaign, banner, zone, website and stats row in it may be replaced, "
            f"mark it once with: python -m src.revive_data.load_revive_data --claim {database}")
    check_foreign_rows(conn, database)


def claim(conn: Connection, database: str, confirm: str) -> None:
    """Mark `database` as synthetic. `confirm` must repeat the database name,
    so a claim can't land on whatever .env happens to point at."""
    if confirm != database:
        raise UnsafeDatabaseError(
            f"--claim {confirm} doesn't match the target database {database}; nothing was changed.")
    check_revive_schema(conn, database)
    check_foreign_rows(conn, database)
    if is_marked(conn):
        return
    conn.execute(text(f"CREATE TABLE {MARKER_TABLE} (claimed_at VARCHAR(32) NOT NULL, note VARCHAR(255) NOT NULL)"))
    conn.execute(text(f"INSERT INTO {MARKER_TABLE} (claimed_at, note) VALUES (:at, :note)"),
                 {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "note": "Synthetic data owned by AI Analytics Copilot; load_revive_data may replace it."})
