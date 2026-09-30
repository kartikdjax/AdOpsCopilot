# Tasks

## 1. Dependency checks

- [x] 1.1 Add `AnalyticsClient.ping(domain)` running `SELECT 1` on MySQL for `revive` and ClickHouse for `exchange`, and give the MySQL engine `connect_args={"connect_timeout": 2}`; verify with a live test in `tests/live/` that both domains ping without error.
- [x] 1.2 Create `src/api/health.py` with an async function that runs named blocking checks concurrently, each in a thread under a 2-second timeout, returning each dependency as `up`/`down` and overall `ok`/`degraded`, logging the exception for any failure; verify with `tests/unit/test_health.py` covering all up, one raising, and one hanging past the timeout (the call returns in under ~3 s and reports it `down`).
- [x] 1.3 In the same unit test file, assert that a check raising an error containing a host and database name produces only `down` in the result and the error text appears in the captured log, not in the returned data.

## 2. Endpoint

- [x] 2.1 Extend `HealthResponse` in `src/api/models.py` with `dependencies` (`revive`, `exchange` → `up`/`down`) and `status` limited to `ok`/`degraded`, keeping `provider` and `active_sessions`; verify the model rejects any other status value in a unit test.
- [x] 2.2 Wire `GET /health` in `src/api/main.py` to the checks from 1.2 using the MCP server's `AnalyticsClient`, still with no sign-in dependency; verify with a live test that calls `/health` without a cookie and gets 200, `status` `ok` and both dependencies `up`.
- [x] 2.3 Add a live test that points the exchange check at an unreachable port (patched ping) and gets 200 with `status` `degraded`, `exchange` `down`, `revive` `up`, and no host, port or database name anywhere in the response body.

## 3. Wrap-up

- [x] 3.1 Document the new `/health` response and the 200-when-degraded choice in README.md, and verify the full suite passes with `.venv/bin/pytest`.
