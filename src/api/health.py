"""Dependency checks behind GET /health.

Kept apart from main.py so it can be tested without importing the MCP
server, which connects to ClickHouse at import time.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Literal

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 2.0

DependencyState = Literal["up", "down"]


async def _run(name: str, check: Callable[[], object], timeout: float) -> DependencyState:
    try:
        # A check that hangs past the timeout is abandoned, not cancelled: its
        # thread keeps waiting on the socket until the driver gives up.
        await asyncio.wait_for(asyncio.to_thread(check), timeout)
        return "up"
    except Exception:  # noqa: BLE001 - any failure means "down"; the detail goes to the log only
        logger.warning("Health check %r failed", name, exc_info=True)
        return "down"


async def check_dependencies(checks: dict[str, Callable[[], object]],
                             timeout: float = CHECK_TIMEOUT_SECONDS
                             ) -> tuple[Literal["ok", "degraded"], dict[str, DependencyState]]:
    """Run blocking checks concurrently, each limited to `timeout` seconds.
    A check is up if it returns and down if it raises or times out; the
    overall status is "ok" only when every check is up."""
    names = list(checks)
    states = await asyncio.gather(*(_run(n, checks[n], timeout) for n in names))
    dependencies = dict(zip(names, states))
    status = "ok" if all(s == "up" for s in states) else "degraded"
    return status, dependencies
