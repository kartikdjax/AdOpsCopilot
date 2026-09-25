"""Small SQLite persistence layer for authentication and chat history."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("COPILOT_DB_PATH", "data/copilot.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'pending',
    agency_id INTEGER
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK(mode IN ('revive','exchange')),
    title TEXT NOT NULL,
    messages_json TEXT NOT NULL,
    tool_calls_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chats_user_updated ON chats(user_id, updated_at DESC);
"""


# Columns added after the first release. Existing users get role 'pending'
# (no Revive data) until an admin grants access - see src/api/manage_users.py.
_USER_COLUMNS = {
    "role": "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'pending'",
    "agency_id": "ALTER TABLE users ADD COLUMN agency_id INTEGER",
}


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    existing = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
    for column, ddl in _USER_COLUMNS.items():
        if column not in existing:
            db.execute(ddl)
    db.commit()
    return db
