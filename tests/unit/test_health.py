"""The /health dependency checks: concurrency, the per-check timeout, and
failure details staying in the log."""
from __future__ import annotations

import logging
import threading
import time

import pytest
from pydantic import ValidationError

from src.api.health import check_dependencies
from src.api.models import HealthResponse


def _ok():
    return None


def _fails():
    raise ConnectionError("Can't connect to MySQL server on 'db.internal:3306' (database revive608)")


async def test_all_up():
    assert await check_dependencies({"revive": _ok, "exchange": _ok}) == (
        "ok", {"revive": "up", "exchange": "up"})


async def test_one_raising_is_down():
    assert await check_dependencies({"revive": _ok, "exchange": _fails}) == (
        "degraded", {"revive": "up", "exchange": "down"})


async def test_hung_checks_time_out_concurrently():
    release = threading.Event()

    def hangs():
        release.wait(10)

    start = time.monotonic()
    try:
        result = await check_dependencies({"revive": hangs, "exchange": hangs}, timeout=0.5)
    finally:
        release.set()  # let the abandoned threads finish
    # Two hung checks cost one timeout, not two.
    assert time.monotonic() - start < 0.9
    assert result == ("degraded", {"revive": "down", "exchange": "down"})


async def test_default_timeout_answers_within_three_seconds():
    release = threading.Event()
    start = time.monotonic()
    try:
        status, deps = await check_dependencies({"revive": lambda: release.wait(10), "exchange": _ok})
    finally:
        release.set()
    assert time.monotonic() - start < 3
    assert status == "degraded" and deps["revive"] == "down"


async def test_failure_detail_goes_to_log_only(caplog):
    with caplog.at_level(logging.WARNING, logger="src.api.health"):
        result = await check_dependencies({"revive": _fails})
    assert result == ("degraded", {"revive": "down"})
    assert "db.internal" not in repr(result) and "revive608" not in repr(result)
    assert "db.internal:3306" in caplog.text and "revive608" in caplog.text


def test_health_response_limits_status():
    fields = {"provider": "groq", "active_sessions": 0, "dependencies": {"revive": "up", "exchange": "up"}}
    assert HealthResponse(status="degraded", **fields).status == "degraded"
    with pytest.raises(ValidationError):
        HealthResponse(status="fine", **fields)
    with pytest.raises(ValidationError):
        HealthResponse(status="ok", **{**fields, "dependencies": {"revive": "maybe", "exchange": "up"}})
