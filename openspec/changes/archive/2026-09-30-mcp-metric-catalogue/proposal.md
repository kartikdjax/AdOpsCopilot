# Proposal

## Why

The Copilot uses MCP only inside its own process, so nothing proves its MCP tools work for outside clients such as Claude Code, Claude Desktop or a remote deployment. A small, data-free server lets us test the real transports (stdio and streamable HTTP) end to end, and gives outside tools a way to read the Copilot's metric definitions, without touching customer data or the existing tools.

## What Changes

- A new standalone MCP server, the **metric catalogue**, with three read-only tools: `list_domains`, `list_metrics(domain)` and `get_metric_definition(domain, metric)`. Its answers come from the same metric definitions the Copilot's own tools use.
- It runs over **stdio** (a client starts it as a subprocess) or **streamable HTTP** (it listens on a port, `127.0.0.1` only by default).
- A small **command-line client** that calls the catalogue over either transport and prints the result.
- A **compatibility test** that makes the same calls in-memory, over stdio and over HTTP, and checks that tool lists, input schemas, results and errors are identical.
- A project-level **Claude Code MCP entry** (`.mcp.json`), so Claude Code can call the catalogue directly.
- A **guard test** that records the existing Copilot MCP server's tool names and input schemas and fails if they change.
- No change to the existing 19-tool MCP server, its mode filtering or its scope handling. No database or LLM needed.

## Capabilities

### New Capabilities
- `mcp-catalogue`: the standalone metric-catalogue MCP server, its tools, its transports, its client, and its separation from the Copilot's own MCP server.

### Modified Capabilities
None. The existing `analytics-tools` and `conversation-modes` requirements stay as they are; the guard test only protects them.

## Impact

- New code: a catalogue package under `src/` (server and client), with no changes to existing modules.
- New files: `.mcp.json` at the repo root; tests under `tests/unit/` (catalogue and transports) and `tests/live/` (guard for the existing server, which needs ClickHouse to import).
- Runtime: the HTTP mode opens a port only while someone runs it; the API and web UI are unaffected.
- No new dependencies: the MCP SDK already installed (2.1.1) provides both transports and the client.
