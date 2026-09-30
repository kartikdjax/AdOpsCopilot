# Tasks

## 1. Guard the existing server first

- [x] 1.1 Record the Copilot MCP server's 19 tool names and input schemas to `tests/live/fixtures/copilot_mcp_tools.json` from the current code, and add `tests/live/test_copilot_mcp_tools_unchanged.py` comparing a fresh listing with it (failure message names the regenerate command); verify it passes before any other code is written.

## 2. Catalogue server

- [x] 2.1 Create `src/mcp_catalogue/server.py` with its own `MCPServer`, tools `list_domains`, `list_metrics(domain)` and `get_metric_definition(domain, metric)` built on `core_tools`, domains typed as `Literal["revive", "exchange"]`, and unknown metrics raised as `ToolError`; verify with `tests/unit/test_mcp_catalogue.py` (in-memory client): exactly three tools, results equal to `core_tools` output, the domain schema lists only the two values, an unknown metric returns a tool error naming available metrics and the next call succeeds, and an unknown domain is rejected.
- [x] 2.2 Add `main()` with `--transport stdio|http`, `--host` (default `127.0.0.1`), `--port` (default 8765), path `/mcp`; verify in the same test file that the module imports without `src.mcp_server` in `sys.modules` and with MySQL and ClickHouse settings pointed at closed ports.

## 3. Client

- [x] 3.1 Create `src/mcp_catalogue/client.py`, a CLI that calls a named tool over stdio (starting the server) or HTTP (`--url`), prints the result as JSON, and exits non-zero with the message on a tool error; verify with `tests/unit/test_mcp_catalogue_client.py` running it as a subprocess for `get_metric_definition revive ctr` (exit 0, JSON with a formula) and an unknown metric (non-zero exit, message printed).

## 4. Compatibility

- [x] 4.1 Add `tests/unit/test_mcp_transports.py` that runs every tool plus an unknown-metric call in-memory, over stdio and over HTTP (server subprocess on a free port, readiness poll, always terminated), and asserts equal tool names, input schemas, results and error flags across the three; verify it passes and leaves no server process running.

## 5. Outside clients and docs

- [x] 5.1 Add `.mcp.json` registering the catalogue for Claude Code over stdio; verify `claude mcp list` (or the JSON loaded by a unit test) shows the `copilot-metric-catalogue` entry with the expected command.
- [x] 5.3 (Found while verifying 5.2) Make `tests/unit/test_revive_data.py::test_seasonal_growth_zone_grows` independent of the time of day it runs: it summed requests per calendar day, so partial first/last days and the planted campaign-6 stop dragged recent totals down. Compare mean requests per hourly row in the first and second half of the time range instead; verify it passes at the current hour and at simulated load times across a whole day.
- [x] 5.2 Document the catalogue in README.md (what it is, the stdio and HTTP commands, the client, the Claude Code entry, and that it's separate from the Copilot's own MCP server), and verify the full suite passes with `.venv/bin/pytest`.
