"""The SQLite session store is safe for several worker processes."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap

from src.api import db


def test_wal_and_busy_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "copilot.db")
    conn = db.get_db()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
    finally:
        conn.close()


def test_two_processes_write_concurrently(tmp_path):
    path = tmp_path / "copilot.db"
    writer = textwrap.dedent("""
        import sys, secrets
        from datetime import datetime, timezone
        from src.api import db
        conn = db.get_db()
        user = f"user-{sys.argv[1]}"
        conn.execute("INSERT OR IGNORE INTO users(id,email,display_name,password_hash,created_at) VALUES(?,?,?,?,?)",
                     (user, user + "@example.com", user, "x", datetime.now(timezone.utc).isoformat()))
        conn.commit()
        for _ in range(50):
            conn.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
                         (secrets.token_hex(16), user, "2099-01-01"))
            conn.commit()
        conn.close()
    """)
    env = {**os.environ, "COPILOT_DB_PATH": str(path)}
    db_init = subprocess.run([sys.executable, "-c", "from src.api import db; db.get_db().close()"],
                             env=env, cwd=os.getcwd(), capture_output=True, text=True)
    assert db_init.returncode == 0, db_init.stderr
    procs = [subprocess.Popen([sys.executable, "-c", writer, str(i)], env=env, cwd=os.getcwd(),
                              stderr=subprocess.PIPE, text=True) for i in (1, 2)]
    for p in procs:
        _, err = p.communicate(timeout=120)
        assert p.returncode == 0, err
    import sqlite3
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 100
    finally:
        conn.close()
