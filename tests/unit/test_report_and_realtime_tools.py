"""The two report-bundling tools and the real-time exchange health tool."""
from __future__ import annotations

import pandas as pd
import pytest

from src.semantic.metric_registry import EXCHANGE, REVIVE
from src.semantic.realtime_exchange import get_realtime_exchange_health
from src.semantic.report_tools import generate_exchange_report, generate_revive_report


class FakeReportClient:
    """Enough canned data to exercise every metric a report touches."""

    def aggregate(self, domain, metrics, days, entity_type=None, entity_id=None):
        return {m: 100.0 for m in metrics}

    def timeseries(self, domain, metric, days, entity_type=None, entity_id=None, grain="day"):
        dates = pd.date_range("2026-08-01", periods=days, freq="D")
        return pd.DataFrame({"period": dates, "value": [50.0 + 0.1 * i for i in range(days)]})


class FakeRealtimeClient:
    def raw_query(self, sql, params, domain=None):
        if "ax_bid_requests" in sql:
            return pd.DataFrame({"requests": [9000]})  # 15 min window -> 10 QPS
        return pd.DataFrame({"responses": [8500], "bids": [6000], "timeouts": [450],
                              "avg_latency_ms": [62.3]})


def test_revive_report_bundles_kpis_trend_and_anomalies():
    report = generate_revive_report(FakeReportClient(), "zone", entity_id=1, days=30)
    assert report.domain == REVIVE
    assert len(report.kpis) == 8
    assert report.trend is not None and report.anomalies is not None


def test_exchange_report_leads_with_win_rate():
    report = generate_exchange_report(FakeReportClient(), "supply_partner", entity_id=5000, days=30)
    assert report.domain == EXCHANGE
    assert report.primary_metric == "win_rate"
    assert len(report.kpis) == 7


def test_realtime_health_rates():
    health = get_realtime_exchange_health(FakeRealtimeClient(), minutes=15)
    assert health.qps == round(9000 / (15 * 60), 3)
    assert health.bid_rate_pct == round(6000 / 8500 * 100, 2)
    assert health.timeout_rate_pct == round(450 / 9000 * 100, 2)


def test_realtime_health_rejects_long_window():
    with pytest.raises(ValueError):
        get_realtime_exchange_health(FakeRealtimeClient(), minutes=500)
