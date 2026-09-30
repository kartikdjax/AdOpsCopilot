"""core_tools logic (period math, ranking, trend and anomaly wrappers, the
absolute-delta contributor ranking) against a fake client with canned data.
test_semantic_layer.py covers the SQL; this covers what happens to the results."""
from __future__ import annotations

import pandas as pd
import pytest

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


@pytest.fixture
def client():
    return FakeAnalyticsClient()


def test_metric_catalog_needs_no_client():
    assert any(m.name == "win_rate" for m in ct.list_available_metrics(EXCHANGE))
    assert "wins" in ct.get_metric_definition(EXCHANGE, "fill_rate").formula


def test_data_freshness(client):
    assert ct.get_data_freshness(client, EXCHANGE).status == "healthy"


def test_calculate_kpi(client):
    assert ct.calculate_kpi(client, EXCHANGE, "win_rate", days=30).value == 24.5


def test_compare_periods_flags_real_decline_not_flat_metric(client):
    assert ct.compare_periods(client, EXCHANGE, "win_rate", days=7).direction == "decreasing"
    assert ct.compare_periods(client, EXCHANGE, "fill_rate", days=7).direction == "stable"


def test_rank_entities_resolves_names_and_keeps_volume(client):
    ranking = ct.rank_entities(client, EXCHANGE, "ctr", "supply_partner", min_volume_metric="impressions")
    assert ranking.results[0].name == "ZoneA"
    # The low-volume entity's volume stays visible so the ranking trap is explainable.
    assert ranking.results[2].volume == 40


def test_trend_and_anomaly_wrappers(client):
    assert ct.analyze_trend(client, REVIVE, "ctr", days=30).direction == "increasing"
    assert ct.detect_anomalies(client, REVIVE, "ctr", days=30).anomalies_found >= 1


def test_explain_metric_change_ranks_by_absolute_delta(client):
    explanation = ct.explain_metric_change(client, EXCHANGE, "win_rate", days=14,
                                           entity_type="supply_partner", entity_id=5000)
    # Campaign_10 lost ~80,000 units; Campaign_11 went 8 -> 2 (-75%) on tiny volume
    # and must not outrank it.
    assert explanation.top_contributors[0].name == "Campaign_10"
