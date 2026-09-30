# Spec Delta

## Purpose

Gives operators one unauthenticated URL that says whether the Copilot can answer questions, and which data source is at fault when it can't.

## ADDED Requirements

### Requirement: Health reports each data dependency
`GET /health` SHALL report the reachability of the Revive MySQL database (`revive`) and ClickHouse (`exchange`) separately, each as `up` or `down`. The overall `status` SHALL be `ok` when every dependency is up and `degraded` when any is down. The response SHALL keep the `provider` and `active_sessions` fields and SHALL use HTTP 200 in both states.

#### Scenario: All dependencies up
- **WHEN** both databases answer
- **THEN** `/health` returns 200 with `status` `ok` and both dependencies `up`

#### Scenario: One dependency down
- **WHEN** ClickHouse is unreachable and MySQL answers
- **THEN** `/health` returns 200 with `status` `degraded`, `exchange` `down` and `revive` `up`

### Requirement: Health checks are time-limited
Each dependency check SHALL finish within 2 seconds. A dependency that hasn't answered by then SHALL be reported `down`, and the checks SHALL run concurrently so `/health` answers within about 2 seconds even when both hang.

#### Scenario: Hung database
- **WHEN** one dependency check doesn't answer
- **THEN** `/health` still responds within about 2 seconds, reporting that dependency `down`

### Requirement: Health needs no sign-in and reveals no connection details
`GET /health` SHALL answer without a session. Its response SHALL NOT contain hostnames, ports, database names, usernames or error messages; the reason a check failed SHALL be written only to the server log.

#### Scenario: Anonymous caller
- **WHEN** a caller without a session requests `/health`
- **THEN** the response is 200

#### Scenario: Failure detail stays private
- **WHEN** a dependency check fails with an error naming the host and database
- **THEN** the response contains only `down` for that dependency, and the error is logged
