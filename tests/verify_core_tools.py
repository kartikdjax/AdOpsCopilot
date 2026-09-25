"""
Verifies core_tools.py's LOGIC (period math, ranking, trend/anomaly
integration, the abs-delta contributor ranking) using a fake client with
canned data - no live ClickHouse needed. verify_semantic_layer.py already
proves the SQL is correct; this proves what happens with the results.
"""
from __future__ import annotations

import sys
sys.path.insert(0, ".")

import pandas as pd

from src.semantic import core_tools as ct
from src.semantic.metric_registry import EXCHANGE, REVIVE


class FakeAnalyticsClient:
    """Duck-types AnalyticsClient's public methods with canned, hand-crafted
    data - deliberately shaped to make specific assertions checkable."""

    def aggregate(self, domain, metrics, days, entity_type=None, entity_id=None):
        return {"win_rate": 24.5, "ctr": 3.1}

    def period_aggregate(self, domain, metrics, start_days_ago, end_days_ago,
                          entity_type=None, entity_id=None):
        # "current" window (end_days_ago=0) is worse than "previous" -
        # a genuine decline, used to test compare_periods + explain_metric_change.
        if end_days_ago == 0:
            return {"win_rate": 18.0, "fill_rate": 40.0}
        return {"win_rate": 24.0, "fill_rate": 40.0}  # fill_rate deliberately UNCHANGED

    def ranking(self, domain, metric, entity_type, days, limit=10, ascending=False,
                min_volume_metric=None):
        return pd.DataFrame({
            "entity_id": [1, 2, 3],
            "value": [45.2, 38.1, 12.0],
            "volume": [500000, 300000, 40],  # entity 3 has tiny volume - a ranking trap
        })

    def entity_list(self, domain, entity_type):
        return pd.DataFrame({"entity_id": [1, 2, 3], "name": ["ZoneA", "ZoneB", "ZoneC"]})

    def timeseries(self, domain, metric, days, entity_type=None, entity_id=None, grain="day"):
        dates = pd.date_range("2026-08-01", periods=30, freq="D")
        values = [3.0 + 0.05 * i for i in range(30)]  # steady increase
        values[25] = 0.5  # one clear anomaly near the end
        return pd.DataFrame({"period": dates, "value": values})

    def child_breakdown(self, domain, metric, child_entity_type, start_days_ago, end_days_ago,
                         parent_entity_type=None, parent_entity_id=None, limit=8):
        # current period (end_days_ago=0): campaign 10 collapsed in ABSOLUTE
        # terms (huge volume drop); campaign 11 has a bigger PERCENTAGE
        # swing but on tiny volume - this is the exact trap explain_metric_change
        # must avoid falling into.
        if end_days_ago == 0:
            return pd.DataFrame({"entity_id": [10, 11], "name": ["Campaign_10", "Campaign_11"],
                                  "value": [100_000, 8]})
        return pd.DataFrame({"entity_id": [10, 11], "name": ["Campaign_10", "Campaign_11"],
                              "value": [180_000, 2]})

    def data_freshness(self, domain):
        return {"last_event": "2026-09-14T16:45:00", "lag_minutes": 5.0, "status": "healthy"}


def main() -> None:
    client = FakeAnalyticsClient()

    print("=" * 70)
    print("TEST 1: list_available_metrics / get_metric_definition (no client needed)")
    print("=" * 70)
    metrics = ct.list_available_metrics(EXCHANGE)
    assert any(m.name == "win_rate" for m in metrics)
    defn = ct.get_metric_definition(EXCHANGE, "fill_rate")
    print(f"exchange.fill_rate formula: {defn.formula}")
    assert "wins" in defn.formula
    print("PASS\n")

    print("=" * 70)
    print("TEST 2: get_data_freshness")
    print("=" * 70)
    fresh = ct.get_data_freshness(client, EXCHANGE)
    print(f"status={fresh.status}, lag={fresh.lag_minutes}min")
    assert fresh.status == "healthy"
    print("PASS\n")

    print("=" * 70)
    print("TEST 3: calculate_kpi")
    print("=" * 70)
    kpi = ct.calculate_kpi(client, EXCHANGE, "win_rate", days=30)
    print(f"win_rate = {kpi.value}{kpi.unit}")
    assert kpi.value == 24.5
    print("PASS\n")

    print("=" * 70)
    print("TEST 4: compare_periods - correctly flags a real decline, ignores a flat metric")
    print("=" * 70)
    cmp_declining = ct.compare_periods(client, EXCHANGE, "win_rate", days=7)
    cmp_flat = ct.compare_periods(client, EXCHANGE, "fill_rate", days=7)
    print(f"win_rate:  {cmp_declining.previous_value} -> {cmp_declining.current_value} "
          f"({cmp_declining.pct_change}%, {cmp_declining.direction})")
    print(f"fill_rate: {cmp_flat.previous_value} -> {cmp_flat.current_value} "
          f"({cmp_flat.pct_change}%, {cmp_flat.direction})")
    assert cmp_declining.direction == "decreasing"
    assert cmp_flat.direction == "stable"
    print("PASS: correctly distinguishes a real move from a flat metric\n")

    print("=" * 70)
    print("TEST 5: rank_entities resolves names and preserves volume for the ranking trap")
    print("=" * 70)
    ranking = ct.rank_entities(client, EXCHANGE, "ctr", "supply_partner", min_volume_metric="impressions")
    for r in ranking.results:
        print(f"  {r.name}: value={r.value}, volume={r.volume}")
    assert ranking.results[0].name == "ZoneA"
    assert ranking.results[2].volume == 40, "FAILED: low-volume entity's volume should be visible, not hidden"
    print("PASS: names resolved correctly, low-volume entity clearly flagged by its volume field\n")

    print("=" * 70)
    print("TEST 6: analyze_trend and detect_anomalies reuse Phase 2's real algorithms")
    print("=" * 70)
    trend = ct.analyze_trend(client, REVIVE, "ctr", days=30)
    print(f"trend: {trend.direction}, {trend.pct_change}%")
    assert trend.direction == "increasing"

    anomalies = ct.detect_anomalies(client, REVIVE, "ctr", days=30)
    print(f"anomalies found: {anomalies.anomalies_found}")
    for a in anomalies.anomalies:
        print(f"  {a.date}: actual={a.actual} expected={a.expected} z={a.z_score}")
    assert anomalies.anomalies_found >= 1, "FAILED: should have found the injected anomaly"
    print("PASS: both algorithms work correctly through the generic wrapper\n")

    print("=" * 70)
    print("TEST 7: explain_metric_change avoids the percentage-on-tiny-volume trap")
    print("=" * 70)
    explanation = ct.explain_metric_change(client, EXCHANGE, "win_rate", days=14,
                                            entity_type="supply_partner", entity_id=5000)
    print(f"Overall: {explanation.previous_value} -> {explanation.current_value} "
          f"({explanation.pct_change}%, {explanation.direction})")
    print(f"Breakdown by: {explanation.breakdown_dimension}")
    for c in explanation.top_contributors:
        print(f"  {c.name}: {c.previous_value} -> {c.current_value} "
              f"(delta={c.delta}, pct={c.pct_change}%)")
    top_contributor = explanation.top_contributors[0]
    assert top_contributor.name == "Campaign_10", (
        f"FAILED: expected Campaign_10 (huge absolute drop) to rank first, got {top_contributor.name}. "
        f"This means the ranking used percentage instead of absolute delta - "
        f"Campaign_11's 8->2 (-75%!) would incorrectly outrank a real -80,000 unit collapse."
    )
    print("PASS: correctly ranked the real ~80,000-unit collapse above a "
          "-75%-but-tiny-volume swing\n")

    print("=" * 70)
    print("ALL CORE TOOL LOGIC CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
