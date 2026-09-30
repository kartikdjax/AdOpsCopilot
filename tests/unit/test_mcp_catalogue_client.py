"""The catalogue's command-line client, run as a real process over stdio."""
from __future__ import annotations

import json
import os
import subprocess
import sys


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "src.mcp_catalogue.client", *args],
                          capture_output=True, text=True, cwd=os.getcwd(), timeout=120)


def test_definition_prints_json_and_exits_zero():
    done = _run("get_metric_definition", "revive", "ctr")
    assert done.returncode == 0, done.stderr
    definition = json.loads(done.stdout)
    assert definition["name"] == "ctr" and definition["domain"] == "revive" and definition["formula"]


def test_list_prints_the_list_itself():
    done = _run("list_domains")
    assert done.returncode == 0, done.stderr
    assert [d["name"] for d in json.loads(done.stdout)] == ["revive", "exchange"]


def test_unknown_metric_prints_message_and_exits_non_zero():
    done = _run("get_metric_definition", "revive", "nope")
    assert done.returncode != 0
    assert "Unknown metric 'nope'" in done.stderr
    assert done.stdout == ""
