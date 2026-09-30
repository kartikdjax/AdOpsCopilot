# Design

## Context

- `/health` (`src/api/main.py`) returns the LLM provider and a count of rows in the SQLite `sessions` table. It touches no data source.
- Both database connections live in one `AnalyticsClient` created when `src/mcp_server.py` is imported: a clickhouse-connect client and a SQLAlchemy engine for MySQL. The API imports the MCP server at startup, and clickhouse-connect contacts ClickHouse on creation, so the API does not start at all while ClickHouse is down. `/health` can therefore only report ClickHouse `down` when it fails after startup; MySQL is connected lazily and can be down at any time.
- Neither connection has an explicit timeout today, so a naive `SELECT 1` against a black-holed host can block for a long time.

## Goals / Non-Goals

**Goals:**
- Reuse the existing connections so `/health` checks exactly what tool calls use.
- Keep the check logic testable without databases.

**Non-Goals:**
- Letting the API start while ClickHouse is down (lazy ClickHouse connection). Worth doing, but it changes startup behaviour and belongs in its own change.
- Checking the LLM provider or the Chroma knowledge base. Calling the LLM costs money and rate limit on every probe.
- Caching health results, or a separate readiness vs liveness endpoint.

## Decisions

**A `ping(domain)` method on `AnalyticsClient`.** Runs `SELECT 1` on the MySQL engine for `revive` and on the ClickHouse client for `exchange`. Alternative: new connections built inside the health route. Rejected: it would duplicate connection settings and could pass while the connections the tools actually use are broken.

**Check logic in a new `src/api/health.py`, separate from the route.** A function takes a mapping of dependency name to a blocking check callable, runs each in a worker thread (`asyncio.to_thread`) under `asyncio.wait_for(..., 2.0)` concurrently via `asyncio.gather`, and returns `{name: "up" | "down"}` plus the overall status. Any exception or timeout means `down`, logged with the exception. The route wires in `AnalyticsClient.ping`. Alternative: put it in `main.py`. Rejected: importing `main.py` connects to ClickHouse, so unit tests couldn't import the logic.

**The thread-based timeout abandons, rather than cancels, a hung check.** `wait_for` returns after 2 s but the worker thread keeps waiting on the socket. That's acceptable for a health probe; to stop threads piling up under a hammering monitor, the MySQL engine also gets `connect_args={"connect_timeout": 2}`. ClickHouse keeps its client-wide timeout, because shortening it would also cut off long analytics queries. Alternative: driver timeouts only. Rejected as the sole guard: they don't cover every stall (e.g. DNS), and ClickHouse has no per-query network timeout to use.

**HTTP 200 when degraded.** The process is alive; the body says what's wrong. Alternative: 503 when degraded. Rejected for now: a container orchestrator using `/health` as a liveness probe would restart a healthy API because a database is down, which doesn't fix the database. A separate readiness endpoint can use 503 later.

**Response shape.** `HealthResponse` gains `dependencies: dict[str, Literal["up", "down"]]`; `status` becomes `Literal["ok", "degraded"]`. Existing fields stay.

## Risks / Trade-offs

- [Probe load: every `/health` call opens work on both databases] → `SELECT 1` is trivial, and the engine's connection pool reuses connections. Add caching only if monitors poll aggressively.
- [ClickHouse down at startup still means no API, so no `/health` at all] → Documented as a non-goal; the monitor sees a connection refusal, which is itself a clear signal.
- [Abandoned threads on hangs] → The MySQL connect timeout bounds its threads; a hung ClickHouse check lives until the client's own timeout, so a monitor polling a hung ClickHouse every few seconds holds a few idle threads meanwhile.
