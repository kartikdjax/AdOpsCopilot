# Proposal

## Why

The Copilot runs only on a developer machine, so the team can't use it. The target is a server with public access at https://kafka.djaxbidder.com that already runs nginx or Apache with TLS, ClickHouse and MySQL 8.0. Today's setup assumes local databases, dev passwords, the domain root, an open sign-up API and hand-run data loads. None of that is safe or workable on a public server.

## What Changes

- **Deployment bundle** (`deploy/`): a compose file that runs the API image, plus a scheduler, using the host's network so they reach the existing MySQL and ClickHouse on localhost. The API listens on `127.0.0.1` only and has no database containers or published database ports. It also contains an `.env.example` with placeholders, nginx and Apache snippets for `/copilot/`, a one-time MySQL setup SQL for the operator, and a runbook.
- **Serving under `/copilot/`**: the UI calls the API with relative URLs. The session cookie's path and `Secure` flag come from settings. The API trusts proxy headers only from localhost.
- **Invite-only accounts**: `POST /auth/signup` is off unless `ALLOW_SIGNUP=true`. **BREAKING** for anyone relying on the sign-up API; the UI has no sign-up form. A new `manage_users add` command creates an account with a generated password and a role.
- **Least-privilege MySQL**: the app connects as a read-only user, and the setup and refresh jobs as a loader user limited to the Copilot's own database. Root credentials never reach the containers.
- **Fresh databases on the server**: a new Revive database (`copilot_revive`) gets the Revive tables the Copilot reads plus Revive's base rows, then synthetic data. A new ClickHouse `adexchange` database gets the exchange schema and data. Each is marked as Copilot-owned, and setup refuses an existing database it doesn't own.
- **Exchange loader replaces its data** instead of appending, guarded like the Revive loader, so it can be re-run.
- **One-command setup** (`setup` service): schemas, base rows, synthetic data and the knowledge base.
- **Scheduled refresh**: the real-time auction window every 15 minutes, and the Revive and exchange history daily, so time-relative data stays current.
- **Image**: the embedding model is built into the image and the app runs offline from Hugging Face; 2 uvicorn workers; interactive API docs off by default.
- **Session storage for 2 workers**: SQLite in WAL mode with a busy timeout.
- Redis stays out. Local development (`uvicorn`, the existing `docker-compose.yml` with its ClickHouse container) keeps working as today.

## Capabilities

### New Capabilities
- `deployment`: how the Copilot is packaged, configured and served on a server: path prefix, proxy and cookie settings, secrets, database access, setup, scheduled refresh, and session storage across workers.

### Modified Capabilities
- `user-access`: sign-up becomes opt-in (`ALLOW_SIGNUP`), and operators create accounts from the server.
- `synthetic-data`: the exchange loader replaces its data and only writes to a Copilot-owned ClickHouse database; a fresh Revive database can be bootstrapped with the tables and base rows the Copilot needs.

## Impact

- Code: `src/config.py` (new settings), `src/api/auth.py` (sign-up switch, cookie settings), `src/api/db.py` (WAL, busy timeout), `src/api/main.py` (docs switch), `src/api/manage_users.py` (`add`), `static/app.js` (relative URLs), the exchange loaders (settings, guard, replace), new setup and scheduler modules, and a Revive MySQL schema file taken from Revive 6.0.8.
- Files: `deploy/` (compose, `.env.example`, proxy snippets, MySQL setup SQL, runbook) and a Dockerfile change (model download, offline mode).
- Server: one operator-run SQL step as root, an nginx or Apache location block, and `docker compose` in `deploy/`.
- Tests: unit tests for the settings, sign-up switch, cookie, relative URLs, WAL, guards, setup steps and compose file; a local end-to-end run of the deployment compose against local MySQL and ClickHouse.
- No new Python dependencies.
