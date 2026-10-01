# Deploying the Copilot

The Copilot runs as two containers on the server: the API (2 workers) and a
scheduler that keeps the synthetic data current. It reuses the server's own
MySQL and ClickHouse, and sits behind the server's existing nginx or Apache
at `https://<domain>/copilot/`.

```
browser ──HTTPS──> nginx/Apache ──/copilot/ → 127.0.0.1:8000──> api container ──> MySQL  (127.0.0.1:3306, copilot_revive)
                                                                 scheduler      ──> ClickHouse (127.0.0.1:8123, adexchange)
```

The containers use host networking: they reach the databases on
`127.0.0.1`, and the API listens on `127.0.0.1` only. No ports are
published, so the proxy is the only way in.

## Before you start

- **Set new passwords first.** If any database password has been shared in
  chat, email or a ticket, change it on the database and use the new one
  below.
- **ClickHouse.** The app only needs the `adexchange` database. Prefer a
  dedicated ClickHouse user limited to it over `default`, and make sure
  ports 8123 and 9000 aren't reachable from the internet.
- **Server needs:** Docker with the compose plugin, about 2 GB of free RAM
  (each API worker loads the embedding model), and a checkout of this repo.

## First deployment

Run from the repo root on the server.

1. **MySQL (once, as root).** Edit a copy of `deploy/mysql-setup.sql`,
   replacing the two `CHANGE_ME` passwords, then:
   ```bash
   mysql -u root -p < mysql-setup.local.sql && rm mysql-setup.local.sql
   ```
   This creates the empty database `copilot_revive`, a read-only user
   `copilot_app` for the API, and `copilot_loader` with rights on that
   database only. Root's password never goes into the app's settings.

2. **Settings.**
   ```bash
   cp deploy/.env.example deploy/.env && chmod 600 deploy/.env
   ```
   Fill in `GROQ_API_KEY`, the two MySQL passwords from step 1, and the
   ClickHouse user and password. `deploy/.env` is git-ignored and never
   copied into the image. Keep `COOKIE_SECURE=true` and `ALLOW_SIGNUP=false`.

3. **Build, load the data, start.**
   ```bash
   docker compose -f deploy/docker-compose.yml build
   docker compose -f deploy/docker-compose.yml run --rm setup
   docker compose -f deploy/docker-compose.yml up -d
   ```
   `setup` creates the Revive tables and base rows in `copilot_revive` and
   the `adexchange` database in ClickHouse, marks both as Copilot-owned,
   loads synthetic data and seeds the knowledge base. It stops without
   changing anything if either database already exists and isn't
   Copilot-owned. It is safe to run again.

4. **Proxy.** Add `deploy/nginx-copilot.conf` (or `deploy/apache-copilot.conf`)
   inside the existing HTTPS server block for the domain, change the port
   if `COPILOT_PORT` isn't 8000, then reload. The snippet also sends
   `X-Forwarded-Prefix: /copilot`, which scopes the session cookie to that
   path; change both places together if you use another path.
   ```bash
   sudo nginx -t && sudo systemctl reload nginx        # or: sudo systemctl reload apache2
   curl https://<domain>/copilot/health
   ```
   Expect `"status":"ok"` with `revive` and `exchange` both `up`.

5. **Accounts.** Sign-up is off; create each person's account:
   ```bash
   docker compose -f deploy/docker-compose.yml exec api \
     python -m src.api.manage_users add someone@example.com --name "Their Name" --role admin
   ```
   It prints a generated password once; share it privately. Roles: `admin`
   (all Revive data), `manager --agency-id N` (one Revive manager), `pending`
   (Exchange mode only). `list` and `set-role` work the same way.

## Running it

- **Start order and reboots:** MySQL and ClickHouse must be running for the
  API to start; enable them at boot (`sudo systemctl enable mysql
  clickhouse-server`). If ClickHouse is down when the API starts, its workers
  keep retrying and the API comes up by itself once ClickHouse answers; until
  then `/copilot/` is unavailable (502/503) and the container shows `unhealthy`.

- **Data refresh:** the scheduler regenerates the real-time auction window
  every 15 minutes and reloads the Revive and exchange history daily at
  02:30 UTC. For about 30 seconds during the daily reload, answers can see
  partial data.
- **Logs:** `docker compose -f deploy/docker-compose.yml logs -f api scheduler`
- **Update to a new version:** `git pull`, then `build` and `up -d` again.
  Users, sessions, chat history and the knowledge base live in the
  `copilot_data` volume and survive rebuilds.
- **Health:** `/copilot/health` (no sign-in) reports each database as
  `up`/`down`; the container health check uses it too.

## Rollback

```bash
docker compose -f deploy/docker-compose.yml down        # add -v to also delete users and chat history
```
Remove the proxy block and reload the proxy. The `copilot_revive` MySQL
database, the two MySQL users and the ClickHouse `adexchange` database hold
only synthetic data and can be dropped.
