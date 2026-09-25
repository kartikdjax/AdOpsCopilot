"""Authentication helpers and API routes for the pilot UI."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from src.api.db import get_db
from src.semantic.access import Scope

router = APIRouter(prefix="/auth", tags=["authentication"])
SESSION_COOKIE = "copilot_session"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        _, salt_hex, digest_hex = encoded.split("$", 2)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def get_current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in required")
    db = get_db()
    try:
        row = db.execute(
            """SELECT u.id, u.email, u.display_name, u.role, u.agency_id
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > ?""",
            (hashlib.sha256(token.encode()).hexdigest(), _now()),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
        return dict(row)
    finally:
        db.close()


def user_scope(user: dict[str, Any]) -> Scope | None:
    """The data scope for a signed-in user, read fresh from the users table
    on every request - a role change applies on the user's next message.
    None = no Revive access (role 'pending', or a manager with no agency)."""
    role, agency_id = user.get("role"), user.get("agency_id")
    if role == "admin":
        return Scope("admin")
    if role == "manager" and agency_id is not None:
        return Scope("manager", int(agency_id))
    return None


class SignUpRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)


class SignInRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


@router.post("/signup")
def signup(payload: SignUpRequest, response: Response):
    email = payload.email.strip().lower()
    db = get_db()
    try:
        if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise HTTPException(status_code=409, detail="An account with that email already exists")
        user_id = secrets.token_hex(16)
        db.execute(
            "INSERT INTO users(id,email,display_name,password_hash,created_at) VALUES(?,?,?,?,?)",
            (user_id, email, payload.display_name.strip(), _hash_password(payload.password), _now()),
        )
        db.commit()
        _set_session(response, user_id, db)
        return {"user": {"id": user_id, "email": email, "display_name": payload.display_name.strip(),
                         "role": "pending", "agency_id": None}}
    finally:
        db.close()


@router.post("/signin")
def signin(payload: SignInRequest, response: Response):
    email = payload.email.strip().lower()
    db = get_db()
    try:
        row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row or not _verify_password(payload.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        _set_session(response, row["id"], db)
        return {"user": {"id": row["id"], "email": row["email"], "display_name": row["display_name"],
                         "role": row["role"], "agency_id": row["agency_id"]}}
    finally:
        db.close()


@router.post("/signout")
def signout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db = get_db()
        try:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))
            db.commit()
        finally:
            db.close()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "signed_out"}


@router.get("/me")
def me(user: dict[str, Any] = Depends(get_current_user)):
    """Also names the Revive manager a manager-role user is limited to, so
    the UI can say whose data they're seeing."""
    agency_name = None
    if user.get("role") == "manager" and user.get("agency_id") is not None:
        from src.api.manage_users import revive_manager_name
        try:
            agency_name = revive_manager_name(int(user["agency_id"]))
        except Exception:  # noqa: BLE001 - a missing name must not block sign-in
            agency_name = None
    return {"user": {**user, "agency_name": agency_name}}


def _set_session(response: Response, user_id: str, db: sqlite3.Connection) -> None:
    raw = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    # 30-day rolling session. The token itself contains no user data.
    from datetime import timedelta
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)", (token_hash, user_id, expires.isoformat()))
    db.commit()
    response.set_cookie(SESSION_COOKIE, raw, max_age=30 * 86400, httponly=True, samesite="lax", secure=False, path="/")
