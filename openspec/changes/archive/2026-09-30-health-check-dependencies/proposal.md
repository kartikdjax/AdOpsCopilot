# Proposal

## Why

`GET /health` always answers `"ok"` as long as the API process is up, even when the Revive MySQL database or ClickHouse is unreachable and every Revive or exchange question will fail. Operators running a per-customer install need one unauthenticated URL that says whether the Copilot can actually answer questions, and which data source is the problem.

## What Changes

- `GET /health` reports each data dependency separately: the Revive MySQL database and ClickHouse, each `up` or `down`.
- The overall `status` becomes `degraded` when any dependency is down, and stays `ok` only when all are up.
- Each check is time-limited, so a hung database can't make `/health` hang.
- The response never includes hostnames, ports, database names, usernames or error text; failure details go to the server log only.
- `/health` keeps working without sign-in, and keeps its existing `provider` and `active_sessions` fields, so current callers aren't broken.
- The HTTP status stays 200 when degraded (assumption: the process is alive and serving; the body says what's wrong).

## Capabilities

### New Capabilities
- `service-health`: the unauthenticated health endpoint and how it reports the state of the Copilot's data dependencies.

### Modified Capabilities
None.

## Impact

- API: `GET /health` response gains a `dependencies` object; `status` can now be `degraded`. Additive, no breaking change.
- Code: `src/api/main.py` (health route), `src/api/models.py` (response model), a new small health-check module, and a lightweight reachability check on the existing database connections.
- Tests: new unit tests with fake checks; a live test against the running databases.
- No new dependencies. The web UI doesn't call `/health`.
