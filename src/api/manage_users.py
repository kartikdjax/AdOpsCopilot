"""
Grant AdOps Copilot access. Run on the server - there is deliberately no web
endpoint for this, so a compromised session can't promote itself.

  python -m src.api.manage_users list
  python -m src.api.manage_users add you@example.com --name "Your Name" --role admin
  python -m src.api.manage_users add ops@example.com --name Ops --role manager --agency-id 2
  python -m src.api.manage_users set-role you@example.com admin
  python -m src.api.manage_users set-role ops@example.com manager --agency-id 2
  python -m src.api.manage_users set-role old@example.com pending

Roles: admin (all Revive data), manager (only that Revive manager's
advertisers, websites and users), pending (no Revive data; the default for
every new sign-up). Changes apply on the user's next message.

Sign-up is off unless ALLOW_SIGNUP is set, so `add` is how people get an
account: it prints a generated password once and stores only its hash.
"""
from __future__ import annotations

import argparse
import secrets
import sys
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from src.api.auth import _hash_password
from src.api.db import get_db
from src.config import get_settings

ROLES = ("admin", "manager", "pending")
PASSWORD_BYTES = 15  # token_urlsafe(15) -> 20 characters


@lru_cache
def _revive_engine():
    s = get_settings()
    return create_engine(URL.create("mysql+pymysql", username=s.mysql_username, password=s.mysql_password,
                                    host=s.mysql_host, port=s.mysql_port, database=s.mysql_database))


def revive_manager_name(agency_id: int) -> str | None:
    with _revive_engine().connect() as conn:
        return conn.execute(text("SELECT name FROM rv_agency WHERE agencyid = :id"), {"id": agency_id}).scalar()


def list_users() -> None:
    db = get_db()
    try:
        rows = db.execute("SELECT email, display_name, role, agency_id FROM users ORDER BY created_at").fetchall()
    finally:
        db.close()
    for r in rows:
        scope = f"manager {r['agency_id']}" if r["role"] == "manager" else ""
        print(f"{r['email']:40s} {r['role']:8s} {scope:12s} {r['display_name']}")


def _check_role(role: str, agency_id: int | None) -> None:
    if role == "manager" and agency_id is None:
        sys.exit("A manager needs --agency-id (the Revive manager's agencyid).")
    if role != "manager" and agency_id is not None:
        sys.exit("--agency-id only applies to the manager role.")
    if agency_id is not None:
        name = revive_manager_name(agency_id)
        if name is None:
            sys.exit(f"No Revive manager with agencyid {agency_id}.")
        print(f"Revive manager {agency_id}: {name}")


def add_user(email: str, display_name: str, role: str, agency_id: int | None) -> None:
    email = email.strip().lower()
    _check_role(role, agency_id)
    password = secrets.token_urlsafe(PASSWORD_BYTES)
    db = get_db()
    try:
        if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            sys.exit(f"An AdOps Copilot user with email {email!r} already exists; use set-role to change it.")
        db.execute("INSERT INTO users(id,email,display_name,password_hash,created_at,role,agency_id) "
                   "VALUES(?,?,?,?,?,?,?)",
                   (secrets.token_hex(16), email, display_name.strip(), _hash_password(password),
                    datetime.now(timezone.utc).isoformat(), role, agency_id))
        db.commit()
    finally:
        db.close()
    print(f"{email}: created with role={role}" + (f", agency_id={agency_id}" if agency_id is not None else ""))
    print(f"Password (shown once, share it securely): {password}")


def set_role(email: str, role: str, agency_id: int | None) -> None:
    _check_role(role, agency_id)

    db = get_db()
    try:
        cursor = db.execute("UPDATE users SET role = ?, agency_id = ? WHERE email = ?",
                            (role, agency_id, email.strip().lower()))
        db.commit()
    finally:
        db.close()
    if cursor.rowcount == 0:
        sys.exit(f"No AdOps Copilot user with email {email!r} - create it with: add {email} --name ... --role ...")
    print(f"{email}: role={role}" + (f", agency_id={agency_id}" if agency_id is not None else ""))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Manage AdOps Copilot user accounts and roles.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Show every user and their role")
    add_parser = sub.add_parser("add", help="Create an account with a generated password")
    add_parser.add_argument("email")
    add_parser.add_argument("--name", required=True, help="display name")
    add_parser.add_argument("--role", choices=ROLES, default="pending")
    add_parser.add_argument("--agency-id", type=int, default=None)
    set_parser = sub.add_parser("set-role", help="Change a user's role")
    set_parser.add_argument("email")
    set_parser.add_argument("role", choices=ROLES)
    set_parser.add_argument("--agency-id", type=int, default=None)
    args = parser.parse_args(argv)

    if args.command == "list":
        list_users()
    elif args.command == "add":
        add_user(args.email, args.name, args.role, args.agency_id)
    else:
        set_role(args.email, args.role, args.agency_id)


if __name__ == "__main__":
    main()
