"""The metric catalogue MCP server, in-memory: its tools, their schemas,
results equal to core_tools, errors, and that it needs no database."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest
from mcp import Client

from src.mcp_catalogue import server
from src.semantic import core_tools as ct


def _client() -> Client:
    # Opened inside each test: an async fixture would close the client in a
    # different task than it opened it in, which the SDK's anyio scopes refuse.
    return Client(server.mcp)


async def test_exactly_three_tools():
    async with _client() as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert names == {"list_domains", "list_metrics", "get_metric_definition"}


async def test_domain_schema_lists_only_the_two_domains():
    async with _client() as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        for name in ("list_metrics", "get_metric_definition"):
            assert tools[name].input_schema["properties"]["domain"]["enum"] == ["revive", "exchange"]


async def test_list_domains():
    async with _client() as client:
        result = await client.call_tool("list_domains", {})
        assert not result.is_error
        assert [d["name"] for d in result.structured_content["result"]] == ["revive", "exchange"]


@pytest.mark.parametrize("domain", ["revive", "exchange"])
async def test_list_metrics_matches_core_tools(domain):
    async with _client() as client:
        result = await client.call_tool("list_metrics", {"domain": domain})
        expected = [m.model_dump() for m in ct.list_available_metrics(domain)]
        assert result.structured_content["result"] == expected


async def test_exchange_metrics_include_win_rate():
    async with _client() as client:
        result = await client.call_tool("list_metrics", {"domain": "exchange"})
        assert "win_rate" in {m["name"] for m in result.structured_content["result"]}


async def test_definition_matches_core_tools():
    async with _client() as client:
        result = await client.call_tool("get_metric_definition", {"domain": "revive", "metric": "fill_rate"})
        assert result.structured_content == ct.get_metric_definition("revive", "fill_rate").model_dump()
        assert "impressions" in result.structured_content["formula"]


async def test_unknown_metric_is_a_tool_error_and_session_continues():
    async with _client() as client:
        result = await client.call_tool("get_metric_definition", {"domain": "revive", "metric": "win_rate"})
        assert result.is_error
        text = str(result.content)
        assert "Unknown metric 'win_rate'" in text and "Available:" in text and "ctr" in text
        follow_up = await client.call_tool("list_domains", {})
        assert not follow_up.is_error


async def test_unknown_domain_is_rejected():
    async with _client() as client:
        result = await client.call_tool("list_metrics", {"domain": "billing"})
        assert result.is_error
        assert result.structured_content is None


def test_main_defaults_and_http_options(monkeypatch):
    calls = []
    monkeypatch.setattr(server.mcp, "run", lambda *a, **kw: calls.append((a, kw)))
    server.main([])
    server.main(["--transport", "http"])
    server.main(["--transport", "http", "--host", "0.0.0.0", "--port", "9001"])
    assert calls == [
        (("stdio",), {}),
        (("streamable-http",), {"host": "127.0.0.1", "port": 8765, "streamable_http_path": "/mcp"}),
        (("streamable-http",), {"host": "0.0.0.0", "port": 9001, "streamable_http_path": "/mcp"}),
    ]


def test_runs_without_databases_or_copilot_server():
    """In a fresh process with both databases pointed at closed ports, the
    catalogue still answers and never loads the Copilot's MCP server."""
    script = textwrap.dedent("""
        import asyncio, sys
        from mcp import Client
        from src.mcp_catalogue.server import mcp

        async def main():
            async with Client(mcp) as c:
                for name, args in [("list_domains", {}), ("list_metrics", {"domain": "revive"}),
                                   ("get_metric_definition", {"domain": "exchange", "metric": "win_rate"})]:
                    assert not (await c.call_tool(name, args)).is_error, name

        asyncio.run(main())
        assert "src.mcp_server" not in sys.modules
        print("ok")
    """)
    env = {**os.environ, "MYSQL_PORT": "1", "CLICKHOUSE_PORT": "1", "MYSQL_HOST": "127.0.0.1",
           "CLICKHOUSE_HOST": "127.0.0.1"}
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env,
                          cwd=os.getcwd(), timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().endswith("ok")
