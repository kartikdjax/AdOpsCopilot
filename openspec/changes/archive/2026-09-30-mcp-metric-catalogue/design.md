# Design

## Context

- The Copilot's MCP server (`src/mcp_server.py`, 19 tools) is used only in-memory by the API. Importing it creates an `AnalyticsClient`, which connects to ClickHouse, so it can't be imported where databases are absent.
- The metric catalogue data already exists: `list_available_metrics` and `get_metric_definition` in `src/semantic/core_tools.py`, built on `src/semantic/metric_registry.py`. Importing `core_tools` opens no connection and doesn't load torch or Chroma (checked: 12 revive and 14 exchange metrics, neither heavy module imported).
- MCP SDK 2.1.1: `MCPServer.run()` supports `stdio` and `streamable-http` (`host`, `port`, `streamable_http_path`). One `mcp.Client` connects to an `MCPServer` instance (in-memory), a `StdioServerParameters` (subprocess) or a URL string (streamable HTTP), so the compatibility test drives all three with the same client code.
- `metric_registry.list_metrics("billing")` returns an empty list rather than an error, and `get_metric` raises `ValueError` naming the available metrics.

## Goals / Non-Goals

**Goals:**
- Exercise the two real MCP transports end to end, from this repo's tests, with no databases.
- Protect the existing server with a test, not just a promise.

**Non-Goals:**
- Exposing the 19 Copilot tools, or any customer data, to outside clients. That needs a decision on how an outside client proves its user scope.
- Authentication on the HTTP endpoint. It binds to localhost by default and serves only public metric definitions.
- A Docker service for the catalogue.

## Decisions

**Package `src/mcp_catalogue/` with `server.py` and `client.py`.** `server.py` builds its own `MCPServer("copilot-metric-catalogue")` and a `main()` taking `--transport stdio|http`, `--host`, `--port`; run as `python -m src.mcp_catalogue.server`. It imports `core_tools` for the data and never imports `src.mcp_server`. Alternative: add the tools to `src/mcp_server.py` behind a flag. Rejected: that changes the existing server and drags in its ClickHouse connection.

**Reuse `core_tools` functions rather than read `metric_registry` directly.** The results are then equal to the Copilot tools' by construction, and the spec's "same as the Copilot's tools" scenarios test that. The catalogue adds only `list_domains` (a two-entry constant with descriptions).

**Domains typed as `Literal["revive", "exchange"]`.** The SDK puts the two values in the JSON schema, so clients see them, and rejects anything else before the tool runs. This also closes the empty-list case from `list_metrics("billing")`. Alternative: validate inside the tool. Rejected: the schema wouldn't show the allowed values.

**Unknown metrics raise `ToolError` with the registry's message.** `MCPServer` replaces other exceptions with a generic "Error executing tool" text; `ToolError` passes the message through, as the Copilot server's `_tool()` wrapper does. The catalogue catches `ValueError` from `get_metric_definition` and re-raises it as `ToolError`, without importing that wrapper.

**Default HTTP address `127.0.0.1:8765/mcp`.** 8000 is the API. Localhost keeps it private unless someone passes `--host 0.0.0.0`.

**Compatibility test runs transports as real processes.** In-memory: `Client(server.mcp)`. stdio: `Client(StdioServerParameters(command=sys.executable, args=["-m", "src.mcp_catalogue.server"], cwd=<repo root>))`. HTTP: start `server --transport http --port <free port>` with `subprocess.Popen`, poll until the port accepts connections (up to 15 s), connect to the URL, and terminate the process in a fixture finalizer. The test records `(tool names, input schemas, each call's structured result or error flag)` per transport and asserts all three are equal. It lives in `tests/unit/` since it needs no database.

**Guard for the existing server in `tests/live/`.** It lists the Copilot server's tools through `Client(mcp)` and compares names and input schemas with `tests/live/fixtures/copilot_mcp_tools.json`, recorded from today's code before any change. It has to be live because importing the server connects to ClickHouse. The file is regenerated only deliberately, by a documented command, when a change intends to alter the tools.

**`.mcp.json` at the repo root** registers the catalogue for Claude Code over stdio, using `.venv/bin/python -m src.mcp_catalogue.server`. Claude Code asks the user to approve project servers, so nothing runs without consent.

## Risks / Trade-offs

- [Subprocess tests are slower and can flake on a busy machine] → Free port chosen by the OS, readiness poll with a timeout, process always terminated in the finalizer.
- [The recorded tool list can go stale when a later change intends to alter the tools] → The test's failure message names the regenerate command, and that change updates the fixture in its own diff, where review sees it.
- [SDK schema output may differ slightly between versions] → The compatibility test compares transports against each other, not against a fixed schema, so an SDK upgrade only fails it if transports disagree.
- [`.mcp.json` points at `.venv/bin/python`] → Works for this repo's documented setup; the README gives the command to adjust for other setups.
