"""
Command-line client for the metric catalogue. Over stdio it starts the
server itself; with --url it connects to one already running over HTTP.

Run: python -m src.mcp_catalogue.client list_domains
     python -m src.mcp_catalogue.client list_metrics revive
     python -m src.mcp_catalogue.client get_metric_definition revive ctr
     python -m src.mcp_catalogue.client --url http://127.0.0.1:8765/mcp list_domains
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters

REPO_ROOT = Path(__file__).resolve().parents[2]


def stdio_server() -> StdioServerParameters:
    """The catalogue server as a subprocess of this Python, run from the repo root."""
    return StdioServerParameters(command=sys.executable, args=["-m", "src.mcp_catalogue.server"],
                                 cwd=str(REPO_ROOT))


def _text(content: list[Any]) -> str:
    return "\n".join(getattr(c, "text", str(c)) for c in content)


async def call(target: Any, tool: str, arguments: dict[str, Any]) -> tuple[bool, Any]:
    """Call one tool. Returns (is_error, result): the structured result, or
    the error text."""
    async with Client(target) as client:
        result = await client.call_tool(tool, arguments)
    if result.is_error:
        return True, _text(result.content)
    data = result.structured_content
    # The SDK wraps list results as {"result": [...]}; print the list itself.
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
    return False, data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Call the Copilot metric catalogue MCP server")
    parser.add_argument("--url", help="HTTP endpoint of a running server (default: start one over stdio)")
    tools = parser.add_subparsers(dest="tool", required=True)
    tools.add_parser("list_domains")
    tools.add_parser("list_metrics").add_argument("domain")
    definition = tools.add_parser("get_metric_definition")
    definition.add_argument("domain")
    definition.add_argument("metric")
    args = parser.parse_args(argv)

    arguments = {k: v for k, v in vars(args).items() if k not in ("url", "tool")}
    is_error, data = asyncio.run(call(args.url or stdio_server(), args.tool, arguments))
    if is_error:
        print(data, file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
