"""The metric registry and the two query builders (ClickHouse for exchange,
MySQL for revive) produce correct, parameterized SQL."""
from __future__ import annotations

import pytest

from src.semantic import mysql_query_builder as mysql_qb
from src.semantic import query_builder as qb
from src.semantic.metric_registry import EXCHANGE, REVIVE, get_metric, list_metrics


def test_domain_metrics_stay_in_their_domain():
    revive = {m.name for m in list_metrics(REVIVE)}
    exchange = {m.name for m in list_metrics(EXCHANGE)}
    assert "win_rate" in exchange and "win_rate" not in revive
    assert "conversions" in revive and "conversions" not in exchange


def test_same_metric_name_has_per_domain_formula():
    revive_fill, exchange_fill = get_metric(REVIVE, "fill_rate"), get_metric(EXCHANGE, "fill_rate")
    assert revive_fill.formula_text != exchange_fill.formula_text
    assert "impressions" in revive_fill.numerator and "wins" in exchange_fill.numerator


def test_ratio_metrics_guard_divide_by_zero():
    assert "NULLIF" in get_metric(REVIVE, "ctr").sql_expression()


def test_revive_joins_only_where_hierarchy_needs_them():
    sql_zone, _ = mysql_qb.build_timeseries_query("fill_rate", days=30, entity_type="zone")
    sql_client, _ = mysql_qb.build_timeseries_query("ctr", days=30, entity_type="client")
    assert "JOIN" not in sql_zone
    assert sql_client.count("LEFT JOIN") == 2
    assert "c.clientid" in sql_client


def test_clickhouse_values_are_bound_parameters():
    sql, _ = qb.build_timeseries_query(EXCHANGE, "win_rate", days=14, entity_type="dsp_campaign")
    assert "{entity_id:UInt32}" in sql and "{days:UInt32}" in sql


def test_mysql_values_are_bound_parameters():
    sql, _ = mysql_qb.build_timeseries_query("ctr", days=14, entity_type="campaign")
    assert ":entity_id" in sql and ":days" in sql


def test_ranking_exposes_volume():
    sql, _ = mysql_qb.build_ranking_query("ctr", "zone", days=30, limit=5, min_volume_metric="impressions")
    assert "AS volume" in sql and "LIMIT :limit" in sql


def test_cross_domain_mistakes_fail_at_registry():
    with pytest.raises(ValueError):
        get_metric(REVIVE, "win_rate")
    with pytest.raises(ValueError):
        qb.build_timeseries_query(EXCHANGE, "win_rate", days=7, entity_type="zone")


def test_aggregate_and_entity_list_queries():
    sql, _ = qb.build_aggregate_query(EXCHANGE, ["bid_requests", "wins", "win_rate", "ecpm"], days=7)
    assert "AS win_rate" in sql and "AS ecpm" in sql
    assert "zone" in mysql_qb.list_entity_types()
    assert mysql_qb.build_entity_list_query("zone")
