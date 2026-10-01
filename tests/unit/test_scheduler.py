"""The refresh scheduler: due times, first runs, and surviving failures."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from src.deploy import scheduler
from src.deploy.scheduler import Job, daily_at, every, run_due

START = datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc)


def _clock(minutes: int) -> datetime:
    return START + timedelta(minutes=minutes)


def test_default_schedule():
    jobs = {j.name: j for j in scheduler.default_jobs()}
    assert jobs["realtime"].run_at_start
    assert jobs["realtime"].next_due(START) == START + timedelta(minutes=15)
    assert jobs["daily reload"].next_due(START) == START.replace(hour=2, minute=30)
    assert jobs["daily reload"].next_due(START.replace(hour=3)) == (START + timedelta(days=1)).replace(hour=2, minute=30)


def test_realtime_every_15_minutes_and_daily_at_0230():
    runs: list[tuple[str, datetime]] = []
    jobs = [Job("realtime", lambda: runs.append(("realtime", now)), every(timedelta(minutes=15)), run_at_start=True),
            Job("daily", lambda: runs.append(("daily", now)), daily_at(2, 30))]
    for minute in range(0, 24 * 60 + 1):  # a whole day, checked every minute
        now = _clock(minute)
        run_due(jobs, now)
    realtime = [t for name, t in runs if name == "realtime"]
    daily = [t for name, t in runs if name == "daily"]
    assert realtime[0] == START and all(b - a == timedelta(minutes=15) for a, b in zip(realtime, realtime[1:]))
    assert daily == [START.replace(hour=2, minute=30)]


def test_failing_job_is_logged_and_runs_again(caplog):
    calls = []

    def flaky():
        calls.append(len(calls))
        if len(calls) == 1:
            raise RuntimeError("ClickHouse down")

    other = []
    jobs = [Job("flaky", flaky, every(timedelta(minutes=15)), run_at_start=True),
            Job("other", lambda: other.append(1), every(timedelta(minutes=15)), run_at_start=True)]
    with caplog.at_level(logging.ERROR, logger="src.deploy.scheduler"):
        run_due(jobs, _clock(0))
        run_due(jobs, _clock(15))
    assert len(calls) == 2 and len(other) == 2
    assert "flaky failed" in caplog.text and "ClickHouse down" in caplog.text


def test_main_loop_ticks_with_injected_clock():
    ticks, slept = [], []
    jobs = [Job("tick", lambda: ticks.append(1), every(timedelta(minutes=15)), run_at_start=True)]
    times = iter([_clock(0), _clock(1), _clock(16)])
    scheduler.main(clock=lambda: next(times), sleep=slept.append, jobs=jobs, max_ticks=3)
    assert len(ticks) == 2 and slept == [30, 30, 30]
