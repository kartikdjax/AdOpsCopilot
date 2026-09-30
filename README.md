# AI Analytics Copilot

Conversational analytics for AdTech data: natural-language Q&A, KPI
summaries, trend analysis, anomaly explanations, health checks and
reports, delivered as a standalone web app backed by MCP tools.

Single-tenant deployment: one instance per customer, on-prem or in their
own cloud.

## How it fits together

- **Web UI** (`static/`) and **FastAPI backend** (`src/api/`): sign-up and
  sign-in, per-user chat history (SQLite in `data/`), and `/chat`.
- **Orchestrator** (`src/orchestrator.py`): the LLM tool-use loop. Groq by
  default, Anthropic optional (`LLM_PROVIDER`).
- **MCP server** (`src/mcp_server.py`): 19 tools, run in-process by the API.
  A conversation runs in one mode and sees only the 11 core tools plus that
  mode's tools (`src/semantic/tool_domains.py`).
- **Semantic layer** (`src/semantic/`): metric definitions and query builders,
  so the LLM picks metrics and entities, never SQL.
- **Knowledge base** (`src/rag/`): Chroma store of playbooks for
  `search_knowledge_base`.

Two modes, two data sources:

| Mode | Data | Where |
|---|---|---|
| `revive` | Revive Adserver ad-server data: delivery and revenue by zone, banner, campaign, advertiser, website or manager; setup inspection and health checks; audit log; maintenance status | Revive's MySQL database (`revive608` locally) |
| `exchange` | Ad exchange auctions: win rate, bid prices, timeouts, supply/demand partners, real-time health | ClickHouse `adexchange` database |

The question map and plan for Revive mode are in `docs/`.

## Run it locally

```bash
docker compose up -d                                 # ClickHouse, adexchange schema applied on first start
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                                 # fill in GROQ_API_KEY and MYSQL_*

python -m src.adexchange_data.load_adexchange_data   # synthetic exchange data
python -m src.revive_data.load_revive_data --claim revive608 --days 30   # first time only; see below
python -m src.rag.load_seed_documents                # playbooks for search_knowledge_base
uvicorn src.api.main:app --port 8000
```

Revive's MySQL stays outside compose: point `MYSQL_*` at a Revive 6.0.x
install whose database the Copilot owns.

To run the API in a container too: `docker compose --profile app up -d`.
Inside the container, `MYSQL_HOST=host.docker.internal` reaches a MySQL on
the host (it must listen on more than 127.0.0.1).

### Health check

`GET /health` needs no sign-in and reports whether each data source answers:

```json
{"status": "degraded", "provider": "groq", "active_sessions": 3,
 "dependencies": {"revive": "up", "exchange": "down"}}
```

`status` is `ok` only when every dependency is `up`. Each check gives up after
2 seconds, so the endpoint answers within about 2 seconds even when a database
hangs. It returns 200 when degraded too: the API itself is alive, and a
liveness probe restarting it wouldn't fix a database. Why a check failed goes
to the server log, never into the response. The API can't start while
ClickHouse is down (it connects at startup), so `exchange: down` means
ClickHouse failed after startup.

### Synthetic Revive data and the loader guard

`load_revive_data` replaces every advertiser, campaign, banner, zone, website
and stats row in its target database, and plants known problems for the
health checks and audit log to find. It refuses to run unless:

- the database has been claimed once with `--claim <database>` (the name must
  match the target), which creates a `copilot_synthetic_marker` table; and
- every row in the tables it replaces looks like one the generator wrote.

So a wrong `MYSQL_DATABASE` can't wipe a real install, and a row someone adds
through Revive's UI is reported instead of silently deleted. The loader never
touches Revive's own admin login, the Default manager, or Revive's own audit
history.

The planted problems are relative to load time (a campaign "ends in 3 days"),
so reload before running the live tests if the data is more than a day old:
`python -m src.revive_data.load_revive_data --days 30`.

## Metric catalogue MCP server

A separate, read-only MCP server (`src/mcp_catalogue/`) that tells any MCP
client which metrics the Copilot knows and how each is calculated. It has
three tools: `list_domains`, `list_metrics(domain)` and
`get_metric_definition(domain, metric)`, with answers identical to the
Copilot's own metric tools. It needs no database, LLM or `.env`.

It is not the Copilot's MCP server: the API never loads it, it never appears
in a chat, and the Copilot's 19 tools stay in-process only.
`tests/live/test_copilot_mcp_tools_unchanged.py` fails if those tools change.

```bash
python -m src.mcp_catalogue.server                     # stdio (a client starts it)
python -m src.mcp_catalogue.server --transport http    # http://127.0.0.1:8765/mcp
python -m src.mcp_catalogue.server --transport http --host 0.0.0.0 --port 9000   # reachable from other machines

python -m src.mcp_catalogue.client list_domains                          # starts the server over stdio
python -m src.mcp_catalogue.client get_metric_definition revive ctr
python -m src.mcp_catalogue.client --url http://127.0.0.1:8765/mcp list_metrics exchange
```

`.mcp.json` registers it for Claude Code over stdio as
`copilot-metric-catalogue`; Claude Code asks you to approve it the first time.
It runs `.venv/bin/python`, so edit the command there if your environment
lives elsewhere.

`tests/unit/test_mcp_transports.py` checks that the same calls give identical
tool lists, schemas, results and errors in-memory, over stdio and over HTTP.

## Access

Every new sign-up is `pending` and can't use Revive until an admin grants a
role from the server (there's no web endpoint for this on purpose):

```bash
python -m src.api.manage_users list
python -m src.api.manage_users set-role you@example.com admin
python -m src.api.manage_users set-role ops@example.com manager --agency-id 2
```

An `admin` sees all of Revive. A `manager` sees only that Revive manager's
advertisers, websites, campaigns, zones, users and audit events. The scope
travels to the MCP tools as request metadata, so the LLM can't see or widen it.

## Tests

```bash
pytest                    # everything
pytest tests/unit         # no databases needed
pytest -m live            # only the tests that read revive608 and ClickHouse
```

- `tests/unit/`: generators, analytics, semantic layer, core tools, mode
  filtering, access scopes and the loader guard, using fake clients or
  in-memory SQLite.
- `tests/live/`: access control, Revive health checks, inspect and audit log
  against the loaded `revive608` and ClickHouse. They skip, with the reason,
  when a database is unreachable, unclaimed or loaded more than 24 hours ago.
- `evals/revive_scenarios.py`: the Revive question map run through the real
  LLM (`python -m evals.revive_scenarios`). Not part of pytest: the model's
  tool choice varies from run to run, so read its pass count as a signal, not
  a gate.
- `scripts/chat_demo.py`: interactive CLI chat (`python -m scripts.chat_demo`).
