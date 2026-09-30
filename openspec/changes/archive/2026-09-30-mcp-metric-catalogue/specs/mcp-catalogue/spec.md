# Spec Delta

## Purpose

A standalone, read-only MCP server that lets any MCP client look up the Copilot's metric definitions over stdio or HTTP, and proves those transports work, without touching customer data or the Copilot's own MCP tools.

## ADDED Requirements

### Requirement: The catalogue lists domains and metrics
The catalogue SHALL offer exactly three tools: `list_domains`, `list_metrics` and `get_metric_definition`. `list_domains` SHALL return `revive` and `exchange`, each with a one-line description. `list_metrics` SHALL take a domain and return every metric in it with its name, kind, unit and description. `get_metric_definition` SHALL take a domain and a metric name and return the metric's formula, unit and description. Results SHALL match the definitions the Copilot's own `list_available_metrics` and `get_metric_definition` tools return.

#### Scenario: Domains
- **WHEN** a client calls `list_domains`
- **THEN** it receives `revive` and `exchange`

#### Scenario: Metrics in a domain
- **WHEN** a client calls `list_metrics` for `exchange`
- **THEN** it receives the same metric names, kinds, units and descriptions as the Copilot's `list_available_metrics` for `exchange`, including `win_rate`

#### Scenario: One definition
- **WHEN** a client asks for `fill_rate` in `revive`
- **THEN** it receives a formula computed from impressions, and the same formula the Copilot's `get_metric_definition` gives

### Requirement: Invalid requests return tool errors
A domain other than `revive` or `exchange` SHALL be rejected, and the tools' input schemas SHALL list the two allowed domains. An unknown metric SHALL return an MCP tool error whose message names the domain's available metrics. Errors SHALL NOT end the session.

#### Scenario: Unknown metric
- **WHEN** a client asks for `win_rate` in `revive`
- **THEN** the call returns a tool error listing the revive metrics, and the next call on the same session succeeds

#### Scenario: Unknown domain
- **WHEN** a client calls `list_metrics` for `billing`
- **THEN** the call is rejected with an error and returns no metrics

#### Scenario: Schema lists allowed domains
- **WHEN** a client lists the tools
- **THEN** the `domain` parameter of `list_metrics` and `get_metric_definition` allows only `revive` and `exchange`

### Requirement: The catalogue runs over stdio and streamable HTTP
The catalogue SHALL run over stdio, started by a client as a subprocess, or over streamable HTTP. In HTTP mode it SHALL listen on `127.0.0.1` port 8765 at path `/mcp` unless another host or port is given. It SHALL start without any database, LLM credentials or `.env` values.

#### Scenario: stdio
- **WHEN** a client starts the catalogue as a subprocess and calls `list_domains`
- **THEN** it receives `revive` and `exchange`

#### Scenario: HTTP
- **WHEN** the catalogue runs in HTTP mode on a free local port and a client connects to its `/mcp` URL
- **THEN** the client can list and call its tools

#### Scenario: No databases
- **WHEN** the catalogue starts while MySQL and ClickHouse are unreachable
- **THEN** every catalogue tool still answers

### Requirement: Transports give identical answers
The same calls made in-memory, over stdio and over HTTP SHALL return the same tool names, input schemas, results and error outcomes.

#### Scenario: Compatibility run
- **WHEN** the compatibility test runs every tool, including an unknown-metric call, over all three transports
- **THEN** the three sets of tool lists, schemas, results and error flags are equal

### Requirement: A command-line client calls the catalogue
A command-line client SHALL call any catalogue tool over stdio (starting the server itself) or over HTTP (given a URL), print the result as JSON, and exit non-zero with the error message when the tool returns an error.

#### Scenario: Definition from the command line
- **WHEN** a user runs the client over stdio asking for `ctr` in `revive`
- **THEN** it prints the definition as JSON and exits with status 0

#### Scenario: Error from the command line
- **WHEN** a user runs the client asking for an unknown metric
- **THEN** it prints the error message and exits non-zero

### Requirement: The Copilot's own MCP server is unchanged
The catalogue SHALL be a separate MCP server. It SHALL NOT be loaded by the Copilot API, SHALL NOT appear in the Copilot's mode filtering, and SHALL NOT change the Copilot MCP server's tools, their input schemas, or how user scope reaches them.

#### Scenario: Copilot tools unchanged
- **WHEN** the Copilot MCP server's tool names and input schemas are compared with the recorded list
- **THEN** there are still 19 tools and every name and schema matches

#### Scenario: Not offered in chat
- **WHEN** the orchestrator builds the tool list for a Revive or Exchange conversation
- **THEN** no catalogue tool is included
