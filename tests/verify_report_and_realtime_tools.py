"""Verifies the two report-bundling tools and the real-time exchange tool."""
from __future__ import annotations

import sys
sys.path.insert(0, ".")

import pandas as pd

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


def main() -> None:
    print("=" * 70)
    print("TEST 1: generate_revive_report bundles KPIs + trend + anomalies in one call")
    print("=" * 70)
    report = generate_revive_report(FakeReportClient(), "zone", entity_id=1, days=30)
    print(f"Domain: {report.domain}, primary metric: {report.primary_metric}")
    print(f"KPIs returned: {[k.metric for k in report.kpis]}")
    assert report.domain == REVIVE
    assert len(report.kpis) == 8, f"FAILED: expected 8 KPIs, got {len(report.kpis)}"
    assert report.trend is not None and report.anomalies is not None
    print("PASS: one tool call produced KPIs + trend + anomalies\n")

    print("=" * 70)
    print("TEST 2: generate_exchange_report uses win_rate as its primary metric")
    print("=" * 70)
    report = generate_exchange_report(FakeReportClient(), "supply_partner", entity_id=5000, days=30)
    print(f"Domain: {report.domain}, primary metric: {report.primary_metric}")
    assert report.domain == EXCHANGE
    assert report.primary_metric == "win_rate"
    assert len(report.kpis) == 7
    print("PASS\n")

    print("=" * 70)
    print("TEST 3: get_realtime_exchange_health computes QPS/rates correctly from raw counts")
    print("=" * 70)
    health = get_realtime_exchange_health(FakeRealtimeClient(), minutes=15)
    print(f"bid_requests={health.bid_requests}, qps={health.qps}")
    print(f"bid_rate={health.bid_rate_pct}%, timeout_rate={health.timeout_rate_pct}%, "
          f"avg_latency={health.avg_latency_ms}ms")
    assert health.qps == round(9000 / (15 * 60), 3), f"FAILED: QPS math wrong, got {health.qps}"
    assert health.bid_rate_pct == round(6000 / 8500 * 100, 2)
    assert health.timeout_rate_pct == round(450 / 9000 * 100, 2)
    print("PASS: QPS, bid rate, and timeout rate all computed correctly\n")

    print("=" * 70)
    print("TEST 4: get_realtime_exchange_health rejects an unreasonably large window")
    print("=" * 70)
    try:
        get_realtime_exchange_health(FakeRealtimeClient(), minutes=500)
        raise AssertionError("FAILED: should have rejected minutes=500")
    except ValueError as e:
        print(f"Correctly rejected: {e}")
    print("PASS: guards against being misused as a long-range trend tool\n")

    print("=" * 70)
    print("ALL REPORT + REALTIME TOOL CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
