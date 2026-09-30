"""
The metric catalogue as its own MCP server: which metrics the Copilot
knows and how each is calculated. Read-only, no customer data, no
database or LLM - so outside MCP clients (Claude Code, Claude Desktop,
a remote deployment) can use it, and it exercises the stdio and
streamable HTTP transports end to end.

It reuses core_tools for its answers, so they match the Copilot's own
list_available_metrics / get_metric_definition tools, and never imports
src.mcp_server (which connects to ClickHouse at import time).

Run: python -m src.mcp_catalogue.server                          # stdio
     python -m src.mcp_catalogue.server --transport http          # http://127.0.0.1:8765/mcp
"""
from __future__ import annotations

import argparse
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from src.semantic import core_tools as ct
from src.semantic.core_models import MetricDefinition, MetricInfo
from src.semantic.metric_registry import EXCHANGE, REVIVE

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
HTTP_PATH = "/mcp"

# Typed as a Literal so the two values appear in each tool's input schema
# and anything else is rejected before the tool runs.
Domain = Literal["revive", "exchange"]

_DOMAIN_DESCRIPTIONS = {
    REVIVE: "Revive Adserver: delivery, revenue and setup by zone, banner, campaign, advertiser and website.",
    EXCHANGE: "Ad exchange auctions: bids, wins, prices, timeouts and supply/demand partners.",
}

# WARNING: a bad metric name is an ordinary user error; its INFO notice would
# land in the terminal of every stdio client.
mcp = MCPServer("copilot-metric-catalogue", log_level="WARNING")


class DomainInfo(BaseModel):
    name: str
    description: str


@mcp.tool()
def list_domains() -> list[DomainInfo]:
    """List the data domains the Copilot has metrics for."""
    return [DomainInfo(name=name, description=text) for name, text in _DOMAIN_DESCRIPTIONS.items()]


@mcp.tool()
def list_metrics(domain: Domain) -> list[MetricInfo]:
    """List every metric in a domain with its kind, unit and description."""
    return ct.list_available_metrics(domain)


@mcp.tool()
def get_metric_definition(domain: Domain, metric: str) -> MetricDefinition:
    """Get one metric's formula, unit and description. The same name can
    mean different things per domain (fill_rate, for example)."""
    try:
        return ct.get_metric_definition(domain, metric)
    except ValueError as exc:
        # ToolError keeps the message (the available metrics); the SDK would
        # otherwise replace it with a generic "Error executing tool".
        raise ToolError(str(exc)) from exc


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Copilot metric catalogue MCP server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default=DEFAULT_HOST, help="http only (default: localhost only)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="http only")
    args = parser.parse_args(argv)
    if args.transport == "stdio":
        mcp.run("stdio")
    else:
        mcp.run("streamable-http", host=args.host, port=args.port, streamable_http_path=HTTP_PATH)


if __name__ == "__main__":
    main()
