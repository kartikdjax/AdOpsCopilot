"""The deployment bundle: compose settings, placeholders only, secrets ignored."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((DEPLOY / "docker-compose.yml").read_text())


def test_project_name_differs_from_dev_compose(compose):
    assert compose["name"] == "ai-analytics-copilot-deploy"


def test_services(compose):
    assert set(compose["services"]) == {"api", "scheduler", "setup"}
    assert compose["services"]["setup"]["profiles"] == ["setup"]


def test_host_network_and_no_published_ports(compose):
    for name, service in compose["services"].items():
        assert service["network_mode"] == "host", name
        assert "ports" not in service and "expose" not in service, name


def test_api_is_local_only_with_two_workers(compose):
    command = " ".join(compose["services"]["api"]["command"])
    assert "exec AdOps-Copilot -m uvicorn" in command  # shows as AdOps-Copilot in netstat/ps
    assert "--host 127.0.0.1" in command
    assert "--workers 2" in command
    assert "--proxy-headers" in command and "--forwarded-allow-ips 127.0.0.1" in command


def test_processes_are_named(compose):
    assert compose["services"]["scheduler"]["command"][0] == "AdOps-Scheduler"
    dockerfile = (ROOT / "Dockerfile").read_text()
    for name in ("AdOps-Copilot", "AdOps-Scheduler"):
        assert f"ln -s /usr/local/bin/python3.10 /usr/local/bin/{name}" in dockerfile


def test_no_database_containers(compose):
    images = {s.get("image", "") for s in compose["services"].values()}
    assert images == {"ai-analytics-copilot:latest"}


def test_env_example_has_only_placeholders():
    values = dict(line.split("=", 1) for line in (DEPLOY / ".env.example").read_text().splitlines()
                  if line and not line.startswith("#"))
    secrets = {k: v for k, v in values.items() if re.search(r"PASSWORD|API_KEY|SECRET|TOKEN", k)}
    assert secrets and all(v == "" for v in secrets.values()), secrets
    assert "root" not in {v.lower() for v in values.values()}
    assert values["ALLOW_SIGNUP"] == "false" and values["COOKIE_SECURE"] == "true"
    assert "COOKIE_PATH" not in values  # the proxy reports the path (X-Forwarded-Prefix)


@pytest.mark.parametrize("snippet, header", [
    ("nginx-copilot.conf", "proxy_set_header X-Forwarded-Prefix /copilot;"),
    ("apache-copilot.conf", 'RequestHeader set X-Forwarded-Prefix "/copilot"'),
])
def test_proxy_snippets_send_the_prefix(snippet, header):
    assert header in (DEPLOY / snippet).read_text()


def test_mysql_setup_uses_placeholders_and_least_privilege():
    sql = (DEPLOY / "mysql-setup.sql").read_text()
    passwords = re.findall(r"IDENTIFIED BY '([^']*)'", sql)
    assert passwords and all(p.startswith("CHANGE_ME") for p in passwords)
    assert re.search(r"GRANT SELECT ON copilot_revive\.\* TO 'copilot_app'", sql)
    assert "ON *.*" not in sql


def test_real_env_file_is_git_ignored():
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    done = subprocess.run(["git", "check-ignore", "-q", "deploy/.env"], cwd=ROOT)
    assert done.returncode == 0


def test_compose_file_is_valid(tmp_path):
    if shutil.which("docker") is None:
        pytest.skip("docker not installed")
    # Validate a copy beside the example settings, so a real deploy/.env is
    # never read or touched (it may belong to root on a server).
    shutil.copy(DEPLOY / "docker-compose.yml", tmp_path / "docker-compose.yml")
    shutil.copy(DEPLOY / ".env.example", tmp_path / ".env")
    done = subprocess.run(["docker", "compose", "-f", str(tmp_path / "docker-compose.yml"), "config", "-q"],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_apache_snippet_has_no_trailing_comments():
    # Apache treats "# ..." after a directive as extra arguments and refuses to start.
    for number, line in enumerate((DEPLOY / "apache-copilot.conf").read_text().splitlines(), 1):
        code = line.strip()
        if code and not code.startswith("#"):
            assert " #" not in code, f"line {number}: move the comment onto its own line"


def test_apache_snippet_passes_configtest(tmp_path):
    """Load the snippet into a stock Apache (Docker) and run its config test."""
    if shutil.which("docker") is None:
        pytest.skip("docker not installed")
    if subprocess.run(["docker", "image", "inspect", "httpd:2.4-alpine"], capture_output=True).returncode != 0:
        pytest.skip("httpd:2.4-alpine image not pulled")
    modules = ["mpm_event", "authz_core", "unixd", "alias", "proxy", "proxy_http", "headers"]
    conf = "\n".join(['ServerRoot "/usr/local/apache2"', "Listen 8089",
                      *[f"LoadModule {m}_module modules/mod_{m}.so" for m in modules],
                      "<VirtualHost *:8089>", (DEPLOY / "apache-copilot.conf").read_text(), "</VirtualHost>"])
    (tmp_path / "httpd.conf").write_text(conf)
    done = subprocess.run(["docker", "run", "--rm", "-v", f"{tmp_path / 'httpd.conf'}:/usr/local/apache2/conf/httpd.conf:ro",
                           "httpd:2.4-alpine", "httpd", "-t"], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and "Syntax OK" in done.stderr, done.stderr
