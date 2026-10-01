# Spec Delta

## Purpose

Defines how the Copilot is packaged and served on a server: behind an existing reverse proxy under a path, reaching the server's own databases with least privilege, keeping secrets out of the image, and keeping its synthetic data current.

## ADDED Requirements

### Requirement: The app works under a path prefix
The web UI SHALL call the API with URLs relative to the page, so the whole app works when a reverse proxy serves it under a path such as `/copilot/` and strips that prefix. The session cookie's path SHALL be the prefix the proxy reports in the `X-Forwarded-Prefix` header, and `/` when there is none, so the same deployment works both through the proxy and when opened directly. A prefix that isn't a plain path SHALL be ignored.

#### Scenario: UI uses relative URLs
- **WHEN** the UI script is checked for API calls
- **THEN** every call it makes uses a path without a leading slash

#### Scenario: Cookie limited to the proxy's path
- **WHEN** a user signs in through a proxy that sends `X-Forwarded-Prefix: /copilot`
- **THEN** the session cookie is set with path `/copilot`, and signing out clears it on that same path

#### Scenario: Opened directly
- **WHEN** a user signs in without any forwarded prefix
- **THEN** the session cookie is set with path `/`

#### Scenario: Invalid prefix
- **WHEN** the forwarded prefix contains characters outside a plain path, such as `;`
- **THEN** it is ignored and the cookie path is `/`

#### Scenario: Leftover cookie with the same name
- **WHEN** the browser sends an old session cookie for the same host (for example `Path=/` from the app opened on another port) together with the new one
- **THEN** the request is signed in with whichever cookie holds a valid session

#### Scenario: Session didn't stick
- **WHEN** sign-in succeeds but the next request isn't signed in
- **THEN** the UI tells the user the browser didn't keep the session instead of showing the app

### Requirement: Secure cookies and trusted proxy headers behind HTTPS
When the `Secure` cookie setting is on, the session cookie SHALL carry the `Secure` flag. The API SHALL listen only on `127.0.0.1` in the deployment, and SHALL accept forwarded-proto and client-address headers only from `127.0.0.1`.

#### Scenario: Secure cookie
- **WHEN** a user signs in with the secure-cookie setting on
- **THEN** the session cookie has the `Secure`, `HttpOnly` and `SameSite=Lax` flags

#### Scenario: Not reachable directly
- **WHEN** the deployment compose file is checked
- **THEN** the API binds to `127.0.0.1`, forwarded headers are trusted only from `127.0.0.1`, and no service publishes a port

### Requirement: Secrets stay on the server
Database and LLM credentials SHALL be read only from a server-side `.env` file that git ignores. The image and every committed file SHALL contain only placeholders. The containers SHALL never receive MySQL root credentials.

#### Scenario: Example environment file
- **WHEN** `deploy/.env.example` is checked
- **THEN** every password and API key value is an empty placeholder, and no variable names a MySQL root user

#### Scenario: Real environment file ignored
- **WHEN** git checks whether `deploy/.env` is ignored
- **THEN** it is ignored

### Requirement: Least-privilege database access
The API SHALL connect to MySQL as a read-only user. The setup and refresh jobs SHALL connect as a separate loader user whose rights cover only the Copilot's own database. When no loader user is configured, the loader SHALL use the app's MySQL settings, as in local development.

#### Scenario: Separate users
- **WHEN** the loader credentials are set in the environment
- **THEN** the setup and refresh jobs use them and the API uses the read-only credentials

#### Scenario: Local development
- **WHEN** no loader credentials are set
- **THEN** the loader uses the same MySQL settings as the API

### Requirement: One-command first-time setup
A setup command SHALL prepare an empty server in one run: create the Revive tables the Copilot reads and Revive's base rows in the target MySQL database if it holds no Revive tables, create the `adexchange` ClickHouse database and schema if it doesn't exist, mark both as Copilot-owned, load synthetic data into both, and seed the knowledge base. Running it again SHALL be safe. It SHALL refuse, without changing anything, a MySQL database that holds Revive tables but isn't Copilot-owned, or an existing `adexchange` database that isn't Copilot-owned.

#### Scenario: Empty server
- **WHEN** setup runs against an empty MySQL database and a ClickHouse server without `adexchange`
- **THEN** both are created, marked, loaded, and the knowledge base is seeded

#### Scenario: Run again
- **WHEN** setup runs a second time
- **THEN** it reloads the synthetic data without duplicating rows

#### Scenario: Someone else's database
- **WHEN** setup targets a MySQL database with Revive tables and no Copilot marker
- **THEN** it exits non-zero naming that database, and changes nothing

### Requirement: Synthetic data stays current
A scheduler SHALL refresh the real-time auction window every 15 minutes, and reload the Revive and exchange synthetic history once a day. A failed run SHALL be logged and SHALL NOT stop later runs.

#### Scenario: Real-time window
- **WHEN** 15 minutes pass
- **THEN** the raw auction tables are regenerated to end at the current time

#### Scenario: Failure doesn't stop the schedule
- **WHEN** one refresh run raises an error
- **THEN** the error is logged and the next scheduled run still happens

### Requirement: Sessions shared across workers
The API SHALL run with 2 worker processes sharing one SQLite session store in WAL mode with a busy timeout of at least 5 seconds, so a user signed in on one worker is signed in on all.

#### Scenario: Connection settings
- **WHEN** the API opens the session database
- **THEN** the journal mode is WAL and the busy timeout is at least 5000 ms

#### Scenario: Concurrent writers
- **WHEN** two processes each write 50 sessions to the same database at the same time
- **THEN** all 100 writes succeed

### Requirement: The image runs without downloading models
The image SHALL contain the embedding model, and the app SHALL start and search the knowledge base with Hugging Face access disabled.

#### Scenario: Offline start
- **WHEN** the image runs with outbound access to Hugging Face blocked
- **THEN** the knowledge base loads the model from the image

### Requirement: API docs off unless enabled
The interactive API documentation SHALL be off unless a setting enables it.

#### Scenario: Default
- **WHEN** the app starts with default settings and `/docs` is requested
- **THEN** the response is 404 (served by the UI's static handler, not the docs page)
