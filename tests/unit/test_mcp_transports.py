"""Compatibility: the metric catalogue gives the same tool list, input
schemas, results and error outcomes in-memory, over stdio (a subprocess)
and over streamable HTTP (a server process on a free local port)."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import pytest
from mcp import Client

from src.mcp_catalogue import server
from src.mcp_catalogue.client import stdio_server

CALLS = [
    ("list_domains", {}),
    ("list_metrics", {"domain": "revive"}),
    ("list_metrics", {"domain": "exchange"}),
    ("get_metric_definition", {"domain": "revive", "metric": "fill_rate"}),
    ("get_metric_definition", {"domain": "exchange", "metric": "fill_rate"}),
    ("get_metric_definition", {"domain": "revive", "metric": "win_rate"}),  # unknown in revive
    ("list_metrics", {"domain": "billing"}),                                 # unknown domain
]
READY_TIMEOUT_SECONDS = 15


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def http_url():
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "src.mcp_catalogue.server", "--transport", "http", "--port", str(port)],
        cwd=os.getcwd(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + READY_TIMEOUT_SECONDS
        while True:
            if process.poll() is not None:
                pytest.fail(f"catalogue HTTP server exited: {process.stderr.read().decode()[-1000:]}")
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                if time.monotonic() > deadline:
                    pytest.fail("catalogue HTTP server didn't start listening in time")
                time.sleep(0.2)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stderr.close()


async def _observe(target) -> dict:
    """Everything a client can see: tools with schemas, then each call's
    error flag and result (structured data, or the error text)."""
    async with Client(target) as client:
        tools = sorted(((t.name, t.input_schema) for t in (await client.list_tools()).tools),
                       key=lambda t: t[0])
        calls = []
        for name, args in CALLS:
            result = await client.call_tool(name, args)
            outcome = ([getattr(c, "text", None) for c in result.content] if result.is_error
                       else result.structured_content)
            calls.append((name, args, result.is_error, outcome))
    return {"tools": tools, "calls": calls}


async def test_transports_agree(http_url):
    in_memory = await _observe(server.mcp)
    over_stdio = await _observe(stdio_server())
    over_http = await _observe(http_url)

    assert [n for n, _ in in_memory["tools"]] == ["get_metric_definition", "list_domains", "list_metrics"]
    assert [c[2] for c in in_memory["calls"]] == [False] * 5 + [True, True]
    assert over_stdio == in_memory
    assert over_http == in_memory
