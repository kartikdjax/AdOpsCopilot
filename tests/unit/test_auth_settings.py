"""The auth routes under deployment settings: sign-up switch, cookie path
(from the proxy's X-Forwarded-Prefix) and Secure flag. Uses only the auth
router and a temporary SQLite file."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import auth, db
from src.config import get_settings

NEW_USER = {"email": "new@example.com", "password": "correct-horse", "display_name": "New User"}


@pytest.fixture
def web(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "copilot.db")

    def make(**env):
        for name in ("ALLOW_SIGNUP", "COOKIE_SECURE"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()
        app = FastAPI()
        app.include_router(auth.router)
        return TestClient(app)

    yield make
    get_settings.cache_clear()


def _count_users() -> int:
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def test_signup_disabled_by_default(web):
    response = web().post("/auth/signup", json=NEW_USER)
    assert response.status_code == 403
    assert _count_users() == 0


def test_signup_when_enabled(web):
    response = web(ALLOW_SIGNUP="true").post("/auth/signup", json=NEW_USER)
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "pending"


def _cookie(response) -> str:
    return response.headers["set-cookie"]


def test_cookie_path_from_proxy_prefix_and_secure_flag(web):
    client = web(ALLOW_SIGNUP="true", COOKIE_SECURE="true")
    via_proxy = {"X-Forwarded-Prefix": "/copilot"}
    cookie = _cookie(client.post("/auth/signup", json=NEW_USER, headers=via_proxy))
    assert "Path=/copilot" in cookie
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie

    signed_in = client.post("/auth/signin", headers=via_proxy,
                            json={"email": NEW_USER["email"], "password": NEW_USER["password"]})
    token = _cookie(signed_in).split(";")[0].split("=", 1)[1]
    cleared = _cookie(client.post("/auth/signout", headers=via_proxy, cookies={auth.SESSION_COOKIE: token}))
    assert "Path=/copilot" in cleared and ("Max-Age=0" in cleared or "expires=" in cleared.lower())


def test_opened_directly_uses_root_path_and_session_works(web):
    client = web(ALLOW_SIGNUP="true")
    signup = client.post("/auth/signup", json=NEW_USER)
    assert "Path=/;" in _cookie(signup) and "Secure" not in _cookie(signup)
    # The browser sends a Path=/ cookie to every API route.
    assert client.get("/auth/me").status_code == 200


@pytest.mark.parametrize("prefix", ["/copilot;evil", "copilot", "/co pilot", "/../x", '/"x'])
def test_invalid_prefix_is_ignored(web, prefix):
    cookie = _cookie(web(ALLOW_SIGNUP="true").post("/auth/signup", json=NEW_USER,
                                                   headers={"X-Forwarded-Prefix": prefix}))
    assert "Path=/;" in cookie


def test_trailing_slash_prefix(web):
    cookie = _cookie(web(ALLOW_SIGNUP="true").post("/auth/signup", json=NEW_USER,
                                                   headers={"X-Forwarded-Prefix": "/copilot/"}))
    assert "Path=/copilot;" in cookie


@pytest.mark.parametrize("order", ["stale-first", "stale-last"])
def test_leftover_cookie_with_same_name(web, order):
    """A browser can send an old copilot_session (Path=/ from another port on
    the same host) beside the current one; whichever is valid must win."""
    client = web(ALLOW_SIGNUP="true")
    token = _cookie(client.post("/auth/signup", json=NEW_USER)).split(";")[0].split("=", 1)[1]
    client.cookies.clear()
    pair = [f"{auth.SESSION_COOKIE}=stale-token-from-another-app", f"{auth.SESSION_COOKIE}={token}"]
    header = "; ".join(pair if order == "stale-first" else pair[::-1])
    me = client.get("/auth/me", headers={"Cookie": header})
    assert me.status_code == 200 and me.json()["user"]["email"] == NEW_USER["email"]


def test_only_stale_cookies_are_rejected(web):
    client = web()
    me = client.get("/auth/me", headers={"Cookie": f"{auth.SESSION_COOKIE}=a; {auth.SESSION_COOKIE}=b"})
    assert me.status_code == 401
