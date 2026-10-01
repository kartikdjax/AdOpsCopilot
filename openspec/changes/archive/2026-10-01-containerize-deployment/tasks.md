# Tasks

## 1. Settings and app behaviour

- [x] 1.1 Add `allow_signup`, `cookie_path`, `cookie_secure`, `enable_api_docs`, `mysql_loader_username`, `mysql_loader_password` to `src/config.py` with the defaults in design.md; verify with `tests/unit/test_settings.py` (defaults, and env overrides).
- [x] 1.2 Make `POST /auth/signup` respond 403 unless `allow_signup`, and set/clear the session cookie with `cookie_path` and `cookie_secure`; verify with `tests/unit/test_auth_settings.py` using an app with only the auth router and a temp SQLite file (403 when off, 200 when on, cookie path and Secure flag, sign-out clears on the same path), and turn sign-up on in `tests/live/test_access_control.py`.
- [x] 1.3 Turn off `/docs`, `/redoc` and `/openapi.json` unless `enable_api_docs`; verify with a live test that `/docs` is 404 by default.
- [x] 1.4 Open SQLite with `timeout=10`, WAL and `busy_timeout=10000`; verify with `tests/unit/test_session_db.py` (journal mode and busy timeout read back; two processes writing 50 sessions each all succeed).
- [x] 1.5 Make `static/app.js` call the API with relative paths; verify with `tests/unit/test_static_ui.py` that no API call in `app.js` starts with `/`, and by loading the local app in a browser or with curl at `/` after the change.
- [x] 1.6 Add `manage_users add <email> --name --role [--agency-id]` generating and printing a ≥16-character password, refusing existing emails and unknown managers; verify with `tests/unit/test_manage_users_add.py` (temp SQLite: account created, printed password signs in, no plain text stored, duplicate refused).

- [x] 1.7 (Found in local testing: opening the app on port 8000 with `COOKIE_PATH=/copilot` signed in, then every request failed with "Sign in required".) Take the cookie path from `X-Forwarded-Prefix` (plain paths only, else `/`) instead of a `COOKIE_PATH` setting, send that header from the nginx and Apache snippets, and make the UI report a session that didn't stick; verify with tests in `tests/unit/test_auth_settings.py` (prefix header, no header, invalid header), `tests/unit/test_deploy_files.py` (both snippets send the prefix), `tests/unit/test_static_ui.py` (sign-in checks `auth/me`), and by signing in both at the proxy URL and directly on the API port in the running local deployment.

- [x] 1.8 (Found in browser testing: Chrome signed in at http://localhost/copilot/, then auth/me returned 401, because an old `copilot_session` cookie for localhost with `Path=/` was sent too and the server read that one.) Accept any `copilot_session` value that is a valid session when several are sent; verify with `tests/unit/test_auth_settings.py` (valid token before or after a stale one) and by repeating the sign-in in headless Chrome with a planted stale cookie.

## 2. Data loading for a fresh server

- [x] 2.1 Create `src/revive_data/revive_mysql_schema.sql` from `revive608` (`SHOW CREATE TABLE`, `IF NOT EXISTS`, the 17 tables) and `revive_base_rows.sql` (agency 1, accounts 1–2, no-login `admin`, account links, application variables); verify with `tests/unit/test_revive_bootstrap_files.py` that every `rv_` table named in `src/` has a definition and the admin password is the no-login marker.
- [x] 2.2 Use `mysql_loader_*` settings (falling back to the app's) in the Revive loader; verify with a unit test of the engine URL it builds.
- [x] 2.3 Add `src/adexchange_data/load_guard.py` (marker `adexchange.copilot_synthetic_marker`, `--claim adexchange`), make both exchange loaders read ClickHouse settings from `src/config.py`, require the marker, and have `load_adexchange_data` truncate its tables before inserting; verify with unit tests on a fake ClickHouse client (refuses unmarked, truncates before insert) and a live test that two loads leave one run's row counts on local ClickHouse after claiming it.
- [x] 2.4 Create `src/deploy/setup.py` (bootstrap-or-refuse for MySQL and ClickHouse, then loads and knowledge-base seed); verify with a live test against a new local MySQL database `copilot_revive_test` and a throwaway ClickHouse database name override used only by the test: empty → created, marked, loaded; second run → no duplicates; foreign Revive tables → refused, unchanged.
- [x] 2.5 Create `src/deploy/scheduler.py` (15-minute real-time refresh, daily 02:30 UTC reloads, failures logged and loop continues); verify with `tests/unit/test_scheduler.py` using a fake clock and fake jobs (due times, a raising job doesn't stop the next).

## 3. Image and deployment bundle

- [x] 3.1 Bake the embedding model into the Dockerfile and run offline; verify by building the image and running the knowledge-base model load with `docker run --network none` (script in `tests/live/test_image.py`, skipped when Docker or the image is absent).
- [x] 3.2 Add `deploy/docker-compose.yml` (`api` with 2 workers on 127.0.0.1 and proxy headers from 127.0.0.1, `scheduler`, `setup` under a profile; host networking; `data` volume; no published ports), `deploy/.env.example` (placeholders only), `deploy/mysql-setup.sql`, `deploy/nginx-copilot.conf`, `deploy/apache-copilot.conf`, and ignore `deploy/.env`; verify with `tests/unit/test_deploy_files.py` (compose settings, empty secrets, no root user variable, `git check-ignore deploy/.env`).
- [x] 3.3 Run the deployment locally end to end: local MySQL `copilot_revive` with the two users from `mysql-setup.sql`, local ClickHouse, `setup`, `up -d`; verify `/health` is ok on 127.0.0.1, an account made with `manage_users add` signs in, a Revive and an Exchange question are answered, and the scheduler logs its first refresh. Remove the local test users and database afterwards.

## 4. Docs

- [x] 4.1 Write `deploy/README.md` (the runbook in design.md's migration plan, rotating the shared passwords first, the ClickHouse and firewall recommendation, rollback) and a README "Deploying" section pointing to it; verify the full suite passes with `.venv/bin/pytest`.
