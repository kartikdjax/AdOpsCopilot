"""Deployment settings: safe defaults, and overrides from the environment."""
from __future__ import annotations

from src.config import Settings


def test_defaults(monkeypatch):
    for name in ("ALLOW_SIGNUP", "COOKIE_SECURE", "ENABLE_API_DOCS",
                 "MYSQL_LOADER_USERNAME", "MYSQL_LOADER_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert s.allow_signup is False
    assert s.cookie_secure is False
    assert s.enable_api_docs is False
    assert s.mysql_loader_username == "" and s.mysql_loader_password == ""


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("ALLOW_SIGNUP", "true")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.setenv("ENABLE_API_DOCS", "true")
    s = Settings(_env_file=None)
    assert s.allow_signup and s.cookie_secure and s.enable_api_docs


def test_loader_credentials_fall_back_to_app_user(monkeypatch):
    monkeypatch.delenv("MYSQL_LOADER_USERNAME", raising=False)
    monkeypatch.setenv("MYSQL_USERNAME", "copilot_app")
    monkeypatch.setenv("MYSQL_PASSWORD", "app-secret")
    assert Settings(_env_file=None).loader_mysql_credentials == ("copilot_app", "app-secret")


def test_loader_credentials_when_set(monkeypatch):
    monkeypatch.setenv("MYSQL_USERNAME", "copilot_app")
    monkeypatch.setenv("MYSQL_LOADER_USERNAME", "copilot_loader")
    monkeypatch.setenv("MYSQL_LOADER_PASSWORD", "loader-secret")
    assert Settings(_env_file=None).loader_mysql_credentials == ("copilot_loader", "loader-secret")
