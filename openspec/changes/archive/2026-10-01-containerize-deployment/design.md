# Design

## Context

- The server already runs nginx or Apache with TLS for `kafka.djaxbidder.com`, ClickHouse (HTTP 8123) and MySQL 8.0.46, all on the host. The Copilot goes under `/copilot/`. Operators' answers: new synthetic Revive database, invite-only accounts.
- The UI (`static/app.js`) calls the API with absolute paths (`/chat`, `/auth/me`, ...) through one `api()` helper, and `index.html` loads `style.css` and `app.js` relatively. The session cookie is set with `path="/"` and `secure=False` in `src/api/auth.py`. The UI has no sign-up form; only `POST /auth/signup` creates accounts, and `manage_users` can list users and change roles but not create them.
- Sessions, users and chat history are in SQLite (`data/copilot.db`), opened with default settings. The only per-process state is `app_state` (settings, LLM provider, in-process MCP client), which is correct per worker.
- The Revive loader already refuses unmarked or foreign-row databases and loads only synthetic rows. It deliberately leaves Revive's own base rows alone: agency 1, accounts 1–2, user 1 and the application variables. The app reads 17 `rv_` tables, and the live `revive608` has 58 tables from a full Revive 6.0.8 install.
- The exchange loaders take ClickHouse settings from argparse defaults (`localhost`, `dev_local_password`), and `load_adexchange_data` only inserts, so running it twice duplicates data. Queries name the `adexchange` database directly, so its name is fixed.
- The embedding model (`all-MiniLM-L6-v2`) downloads from Hugging Face on first use.

## Goals / Non-Goals

**Goals:**
- A deployment an operator can bring up with one SQL step, one `.env`, one proxy block and three compose commands.
- Local development stays exactly as it is.

**Non-Goals:**
- Replacing the host's proxy or managing TLS certificates.
- More than one server or container replica (that is when Redis or another shared session store would be needed).
- Reading a real Revive install's data.
- CI/CD or pushing images to a registry: the image is built on the server from the repo.

## Decisions

**Host networking for the containers.** `network_mode: host` lets the containers reach MySQL and ClickHouse on `127.0.0.1` exactly as local development does. It needs no change to MySQL's `bind-address`, no database port opened to the Docker bridge, and uvicorn binds `127.0.0.1:${COPILOT_PORT:-8000}` so only the host proxy reaches it. Alternative: a bridge network with `host.docker.internal`. Rejected: MySQL on Ubuntu listens on 127.0.0.1 by default, so it would need reconfiguring, and MySQL users would need grants for the bridge's addresses.

**Prefix stripped by the proxy; the app stays prefix-agnostic.** nginx `location /copilot/ { proxy_pass http://127.0.0.1:8000/; }` (Apache `ProxyPass /copilot/ http://127.0.0.1:8000/`) plus a redirect from `/copilot` to `/copilot/`. The UI's `api()` drops the leading slash so `fetch("chat")` resolves against the page (`/copilot/chat`); locally the page is at `/`, so nothing changes there. The cookie path comes from the proxy's `X-Forwarded-Prefix` header (the snippets set `/copilot`), falling back to `/` when the app is opened directly; `Secure` comes from `COOKIE_SECURE` (deploy: true). A fixed `COOKIE_PATH` setting was tried first and dropped: during local testing, opening the app on its own port signed in and then failed every request, because the browser never sent a `/copilot` cookie to `/chat`. uvicorn runs with `--proxy-headers --forwarded-allow-ips 127.0.0.1`. Alternative: `--root-path /copilot` with the prefix kept. Rejected: then every route and static path must handle the prefix, and local runs differ.

**Settings, not code branches.** New settings in `src/config.py`: `allow_signup` (default false), `cookie_secure` (false), `enable_api_docs` (false), `mysql_loader_username` and `mysql_loader_password` (empty = use the app's MySQL settings). `ALLOW_SIGNUP` defaults to off everywhere, since the UI has no sign-up form; the live access-control test turns it on for itself.

**Two MySQL users, created by the operator.** `deploy/mysql-setup.sql` (operator runs once as root, filling in two passwords) creates `copilot_revive`, `copilot_app` with `SELECT` on it, and `copilot_loader` with all rights on it only. Both users are declared for `localhost` and `127.0.0.1`, since TCP from the container arrives as `127.0.0.1`. Root credentials stay with the operator and never enter `.env`.

**Bootstrap from a committed schema file.** `src/revive_data/revive_mysql_schema.sql` holds `CREATE TABLE IF NOT EXISTS` for the 17 tables, taken from `revive608` with `SHOW CREATE TABLE` (a stock Revive 6.0.8 schema; no data). `src/revive_data/revive_base_rows.sql` inserts agency 1, accounts 1 (ADMIN) and 2 (MANAGER), user 1 `admin` with the loader's existing no-login password marker, their two account links, and the application-variable rows. A test checks that every `rv_` table named in `src/` has a definition.

**One setup module, reusing the guards.** `python -m src.deploy.setup` (the compose `setup` service):
1. Revive: if the target database has no `rv_` tables, create schema, base rows and marker (the modified claim requirement); if it has them without a marker, stop; then load via `load_revive_data`.
2. Exchange: if `adexchange` doesn't exist, apply `adexchange_schema.sql` and create the marker; if it exists without a marker, stop; then load.
3. Knowledge base: `load_seed_documents`.
The exchange guard mirrors `load_guard.py` in a small `src/adexchange_data/load_guard.py` (marker table `adexchange.copilot_synthetic_marker`, `--claim adexchange`). Replacing data = `TRUNCATE` each table the loader writes, after the guard, before inserting.

**Scheduler as a compose service, not host cron.** `python -m src.deploy.scheduler` loops: every 15 minutes run the real-time refresh; once a day at 02:30 UTC run the Revive and exchange reloads. Each job runs in a `try`, and failures are logged and never stop the loop. Using the same image, it runs with `restart: unless-stopped`. Alternative: host cron calling `docker compose run`. Rejected: one more thing to set up on the server, outside the repo.

**Session store: WAL + busy timeout.** `get_db()` connects with `timeout=10` and sets `PRAGMA journal_mode=WAL` (persisted in the file) and `busy_timeout=10000`. Two workers × the team's load is well within SQLite's limits.

**Image.** The Dockerfile downloads the model at build (`HF_HOME=/opt/hf`) and sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` at runtime. The `api` command runs uvicorn with `--workers 2`. `data/` (SQLite and Chroma) is a named volume shared by `api`, `setup` and `scheduler`.

**Deployment files in `deploy/`.** `docker-compose.yml` (services `api`, `scheduler`, and `setup` under a profile so it runs only on request), `.env.example`, `nginx-copilot.conf`, `apache-copilot.conf`, `mysql-setup.sql` and `README.md` (the runbook). The root `docker-compose.yml` stays the local-development file.

## Risks / Trade-offs

- [Host networking gives the containers the host's network view] → The API binds 127.0.0.1 only; the image runs our own code; database access is still limited by the two MySQL users.
- [The daily reload truncates and reloads while the app serves; questions in those ~30 s can see partial data] → Runs at 02:30 UTC; the runbook notes it.
- [Two workers each load the embedding model and MCP server, about 1–1.5 GB RAM in total] → Documented; `--workers` is one line to change.
- [The `/copilot` prefix is an assumption] → Set only in the proxy snippets (location and `X-Forwarded-Prefix`); the app itself doesn't depend on it.
- [ClickHouse is used as `default` with a weak password, and it may be reachable from outside] → Out of the app's scope; the runbook recommends a dedicated ClickHouse user limited to `adexchange` and checking the firewall.
- [Credentials were shared in chat] → The runbook's first step is to set new passwords in `.env` and on the database users.

## Migration Plan

1. Operator: run `deploy/mysql-setup.sql` as root with two new passwords.
2. Copy `deploy/.env.example` to `deploy/.env` and fill in the values.
3. `docker compose -f deploy/docker-compose.yml build`, then `run --rm setup`, then `up -d`.
4. Add the nginx or Apache block, reload the proxy, and check `https://kafka.djaxbidder.com/copilot/health`.
5. Create accounts with `docker compose -f deploy/docker-compose.yml exec api python -m src.api.manage_users add ...`.

Rollback: `docker compose -f deploy/docker-compose.yml down` and remove the proxy block. The databases are Copilot-owned and can be dropped.

## Open Questions

- Whether the host proxy is nginx or Apache: both snippets are provided; the operator uses one.
