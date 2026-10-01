"""`manage_users add` creates invite-only accounts with a generated password."""
from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import auth, db, manage_users


@pytest.fixture(autouse=True)
def temp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "copilot.db")


def _add(capsys, *args) -> str:
    manage_users.main(["add", *args])
    return capsys.readouterr().out


def _password(out: str) -> str:
    return re.search(r"Password \(shown once.*\): (\S+)", out).group(1)


def test_add_creates_account_that_can_sign_in(capsys):
    out = _add(capsys, "Admin@Example.com", "--name", "Team Admin", "--role", "admin")
    password = _password(out)
    assert len(password) >= 16

    conn = db.get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE email = 'admin@example.com'").fetchone()
    finally:
        conn.close()
    assert row["role"] == "admin" and row["agency_id"] is None
    assert password not in row["password_hash"] and row["password_hash"].startswith("scrypt$")

    app = FastAPI()
    app.include_router(auth.router)
    signed_in = TestClient(app).post("/auth/signin", json={"email": "admin@example.com", "password": password})
    assert signed_in.status_code == 200 and signed_in.json()["user"]["role"] == "admin"


def test_existing_email_is_refused(capsys):
    _add(capsys, "ops@example.com", "--name", "Ops")
    with pytest.raises(SystemExit) as refused:
        _add(capsys, "ops@example.com", "--name", "Someone Else", "--role", "admin")
    assert "already exists" in str(refused.value)
    conn = db.get_db()
    try:
        rows = conn.execute("SELECT display_name, role FROM users WHERE email = 'ops@example.com'").fetchall()
    finally:
        conn.close()
    assert [tuple(r) for r in rows] == [("Ops", "pending")]


def test_manager_needs_existing_revive_manager(capsys, monkeypatch):
    monkeypatch.setattr(manage_users, "revive_manager_name", lambda agency_id: None)
    with pytest.raises(SystemExit) as refused:
        _add(capsys, "m@example.com", "--name", "M", "--role", "manager", "--agency-id", "99")
    assert "No Revive manager" in str(refused.value)
    with pytest.raises(SystemExit):
        _add(capsys, "m@example.com", "--name", "M", "--role", "manager")
