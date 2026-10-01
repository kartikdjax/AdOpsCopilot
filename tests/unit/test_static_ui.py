"""The web UI works under a path prefix: its API calls and assets are relative."""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "static"


def test_api_calls_are_relative():
    calls = re.findall(r"""\bapi\(\s*["'`]([^"'`]*)""", (STATIC / "app.js").read_text())
    assert calls, "no api() calls found"
    assert not [c for c in calls if c.startswith("/")]


def test_fetch_only_through_api_helper():
    # Any other fetch() with a literal absolute path would bypass the prefix.
    assert not re.findall(r"""\bfetch\(\s*["'`]/""", (STATIC / "app.js").read_text())


def test_assets_are_relative():
    html = (STATIC / "index.html").read_text()
    assert not re.findall(r"""(?:href|src)=["']/""", html)


def test_sign_in_requires_a_working_session():
    js = (STATIC / "app.js").read_text()
    handler = js[js.index('signinForm.addEventListener("submit"'):js.index('document.getElementById("signout-btn")')]
    assert 'api("auth/me")' in handler
    assert "me.ok ? me : resp" not in handler  # never fall back to the sign-in response
    assert "if (!me.ok)" in handler and "showAuthError" in handler.split("if (!me.ok)")[1]
