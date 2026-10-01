"""GET /health against the running databases."""
from __future__ import annotations


def test_both_domains_ping(admin):
    admin.ping("revive")
    admin.ping("exchange")


def _health_client():
    from fastapi.testclient import TestClient

    from src.api.main import app
    return TestClient(app)  # no lifespan and no cookie: /health must need neither


def test_health_all_up_without_sign_in(admin):
    response = _health_client().get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"] == {"revive": "up", "exchange": "up"}


def test_health_degraded_hides_connection_details(admin, monkeypatch):
    from src.config import get_settings
    from src.semantic.analytics_client import AnalyticsClient

    real_ping = AnalyticsClient.ping

    def ping(self, domain):
        if domain == "exchange":
            # A real connection attempt to a closed port, so the error is the
            # driver's own text, host and port included.
            import clickhouse_connect
            clickhouse_connect.get_client(host="localhost", port=1, database="adexchange")
        return real_ping(self, domain)

    monkeypatch.setattr(AnalyticsClient, "ping", ping)
    response = _health_client().get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"] == {"revive": "up", "exchange": "down"}

    settings = get_settings()
    for secret in {settings.mysql_host, str(settings.mysql_port), settings.mysql_database,
                   settings.mysql_username, settings.clickhouse_host, str(settings.clickhouse_port),
                   "adexchange", "localhost", "port=1", "refused"}:
        assert secret not in response.text, secret


def test_api_docs_off_by_default(admin):
    client = _health_client()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path
