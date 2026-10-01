"""
Keeps the synthetic data current in a deployment:

- every 15 minutes: regenerate the real-time auction window (raw ax_ tables),
  so get_realtime_exchange_health keeps seeing traffic;
- daily at 02:30 UTC: reload the Revive and exchange history, whose planted
  problems and trends are relative to load time.

A failed job is logged and the schedule carries on.

Run: python -m src.deploy.scheduler
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REALTIME_EVERY = timedelta(minutes=15)
DAILY_AT = (2, 30)  # UTC hour, minute


@dataclass
class Job:
    name: str
    run: Callable[[], None]
    next_due: Callable[[datetime], datetime]  # given "now", when it's next due
    run_at_start: bool = False
    due_at: datetime | None = None


def every(interval: timedelta) -> Callable[[datetime], datetime]:
    return lambda now: now + interval


def daily_at(hour: int, minute: int) -> Callable[[datetime], datetime]:
    def next_due(now: datetime) -> datetime:
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return due if due > now else due + timedelta(days=1)
    return next_due


def run_due(jobs: list[Job], now: datetime) -> None:
    """Run every job that is due, then schedule its next run. Failures are
    logged and never stop the other jobs or later runs."""
    for job in jobs:
        if job.due_at is None:
            job.due_at = now if job.run_at_start else job.next_due(now)
        if now < job.due_at:
            continue
        try:
            logger.info("Running %s", job.name)
            job.run()
            logger.info("%s done", job.name)
        except Exception:  # noqa: BLE001 - a scheduler must survive any job failure
            logger.exception("%s failed; will try again at its next run", job.name)
        job.due_at = job.next_due(now)


def _realtime() -> None:
    from src.adexchange_data.refresh_realtime_window import refresh
    from src.config import get_settings
    s = get_settings()
    refresh(s.clickhouse_host, s.clickhouse_port, "adexchange", s.clickhouse_username, s.clickhouse_password,
            raw_hours=3, seed=11)


def _daily() -> None:
    from src.deploy.setup import run
    run(seed_knowledge_base=False)  # re-checks ownership, then reloads both databases


def default_jobs() -> list[Job]:
    return [Job("realtime", _realtime, every(REALTIME_EVERY), run_at_start=True),
            Job("daily reload", _daily, daily_at(*DAILY_AT))]


def main(clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
         sleep: Callable[[float], None] = time.sleep, jobs: list[Job] | None = None,
         max_ticks: int | None = None) -> None:
    jobs = jobs if jobs is not None else default_jobs()
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        run_due(jobs, clock())
        ticks += 1
        sleep(30)


if __name__ == "__main__":
    main()
