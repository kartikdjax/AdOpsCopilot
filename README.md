# AI Analytics Copilot

Conversational analytics for AdTech data: natural-language Q&A, KPI
summaries, trend analysis, anomaly explanations, and automated report
generation — delivered as a standalone web app backed by MCP tools.

Single-tenant deployment: one instance per customer, on-prem or in their
own cloud. Data lives in ClickHouse (analytics) + Redis (cache).

## Status: Phase 1 complete — synthetic data foundation

Since there's no live data source yet, Phase 1 builds a realistic,
labeled synthetic dataset so every later feature has real signal to work
against, instead of being demoed on noise.

### What's in this phase

- **`src/data/clickhouse_schema.sql`** — fact table (`ad_events`) +
  auto-aggregating materialized view (`daily_campaign_stats`) for fast
  KPI queries.
- **`src/data/generate_synthetic_data.py`** — generates campaigns with
  five DELIBERATE scenarios, verified to produce the intended pattern:
  - `stable` — baseline, noise only
  - `ctr_improvement` — a step-change in CTR at the midpoint (mirrors a
    real "targeting update" story)
  - `budget_exhaustion` — delivery gets capped once spend would exceed
    daily budget
  - `ctr_anomaly_drop` — a single-day CTR crash, isolated and recoverable
  - `seasonal_spend_growth` — gradual, compounding spend growth
- **`src/data/load_to_clickhouse.py`** — writes the generated dataset
  into a real ClickHouse instance, chunked for large volumes.
- **`docker-compose.yml`** — local ClickHouse + Redis, schema auto-applied
  on first start.

### Run it

```bash
docker compose up -d                    # starts ClickHouse + Redis, applies schema
pip install -r requirements.txt

# Fast local test (small volume, ~10 seconds)
python -m src.data.load_to_clickhouse --days 30 --scale 0.05

# Full-scale demo dataset (~5M events, 60 days)
python -m src.data.load_to_clickhouse --days 60 --scale 1.0
```

Verify: `clickhouse-client --query "SELECT scenario_hint, count() FROM adtech.ad_events GROUP BY campaign_id"` or just run the generator standalone first (no ClickHouse needed):
```bash
python src/data/generate_synthetic_data.py --days 60 --scale 0.05
```
This prints verification output proving the CTR step-change and anomaly
day are actually present in the generated data before you ever touch
ClickHouse.

## Revive admin copilot

Revive mode answers ad-server questions from a real Revive Adserver MySQL
database (`revive608`): delivery and revenue by zone, banner, campaign,
advertiser, website or manager; setup inspection and health checks; the
audit log; and maintenance status. The full question map and plan live in
`docs/`.

### Set up and run

```bash
cp .env.example .env                               # fill in GROQ_API_KEY and MYSQL_*
python -m src.revive_data.load_revive_data --days 30   # synthetic data + planted problems
python -m src.rag.load_seed_documents              # playbooks for search_knowledge_base
uvicorn src.api.main:app --port 8000
```

The loader only replaces synthetic rows. It never touches Revive's own
admin login, the Default manager, or Revive's own audit history.

### Access

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

### Tests

```bash
python -m tests.verify_access_control      # plus the other tests/verify_*.py scripts
python -m tests.test_revive_scenarios      # LLM eval over the admin question map
```

The `verify_*` scripts are deterministic. `test_revive_scenarios` calls the
real LLM, so expect some run-to-run variation in its pass count.

## Roadmap

- [x] Phase 1: ClickHouse schema + synthetic data generator
- [ ] Phase 2: MCP tools — KPI summary, trend analysis, anomaly detection, report generation
- [ ] Phase 3: RAG knowledge base (policies, historical explanations) alongside structured tools
- [ ] Phase 4: Agent orchestrator — Claude tool-use loop
- [ ] Phase 5: Web chat frontend
- [ ] Phase 6: Packaging for sale — per-customer config, auth, licensing hooks
