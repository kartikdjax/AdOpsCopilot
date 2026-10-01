"""The Revive loader connects as the loader user when one is configured."""
from __future__ import annotations

import pytest

from src.config import get_settings
from src.revive_data.load_revive_data import connection_defaults


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch):
    for name in ("MYSQL_LOADER_USERNAME", "MYSQL_LOADER_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MYSQL_USERNAME", "copilot_app")
    monkeypatch.setenv("MYSQL_PASSWORD", "app-secret")
    monkeypatch.setenv("MYSQL_DATABASE", "copilot_revive")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_uses_app_user_without_loader_settings():
    d = connection_defaults()
    assert (d["username"], d["password"], d["database"]) == ("copilot_app", "app-secret", "copilot_revive")


def test_uses_loader_user_when_set(monkeypatch):
    monkeypatch.setenv("MYSQL_LOADER_USERNAME", "copilot_loader")
    monkeypatch.setenv("MYSQL_LOADER_PASSWORD", "loader-secret")
    get_settings.cache_clear()
    d = connection_defaults()
    assert (d["username"], d["password"], d["database"]) == ("copilot_loader", "loader-secret", "copilot_revive")
