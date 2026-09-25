"""Verifies the metric registry and the two query builders (ClickHouse for
exchange, MySQL for revive) produce correct, safe SQL."""
from __future__ import annotations

import sys
sys.path.insert(0, ".")

from src.semantic import mysql_query_builder as mysql_qb
from src.semantic import query_builder as qb
from src.semantic.metric_registry import EXCHANGE, REVIVE, get_metric, list_metrics


def main() -> None:
    print("=" * 70)
    print("TEST 1: both domains registered, no cross-contamination")
    print("=" * 70)
    revive_metrics = [m.name for m in list_metrics(REVIVE)]
    exchange_metrics = [m.name for m in list_metrics(EXCHANGE)]
    print(f"Revive   ({len(revive_metrics)}): {', '.join(revive_metrics)}")
    print(f"Exchange ({len(exchange_metrics)}): {', '.join(exchange_metrics)}")
    assert "win_rate" in exchange_metrics and "win_rate" not in revive_metrics
    assert "conversions" in revive_metrics and "conversions" not in exchange_metrics
    print("PASS: domain-specific metrics stay in their own domain\n")

    print("=" * 70)
    print("TEST 2: same metric name, genuinely different formula per domain")
    print("=" * 70)
    revive_fill = get_metric(REVIVE, "fill_rate")
    exchange_fill = get_metric(EXCHANGE, "fill_rate")
    print(f"revive.fill_rate   = {revive_fill.formula_text}")
    print(f"exchange.fill_rate = {exchange_fill.formula_text}")
    assert revive_fill.formula_text != exchange_fill.formula_text
    assert "impressions" in revive_fill.numerator and "wins" in exchange_fill.numerator
    print("PASS: each domain keeps its own correct definition\n")

    print("=" * 70)
    print("TEST 3: ratio metrics guard against divide-by-zero")
    print("=" * 70)
    expr = get_metric(REVIVE, "ctr").sql_expression()
    print(f"revive.ctr SQL -> {expr}")
    assert "NULLIF" in expr, "FAILED: no divide-by-zero guard"
    print("PASS: NULLIF() guard present (works identically in MySQL and ClickHouse)\n")

    print("=" * 70)
    print("TEST 4: Revive campaign/client queries generate the required joins (MySQL builder)")
    print("=" * 70)
    sql_zone, _ = mysql_qb.build_timeseries_query("fill_rate", days=30, entity_type="zone")
    sql_client, _ = mysql_qb.build_timeseries_query("ctr", days=30, entity_type="client")
    print(f"zone   -> {sql_zone}\n")
    print(f"client -> {sql_client}\n")
    assert "JOIN" not in sql_zone, "FAILED: zone should need no join"
    assert sql_client.count("LEFT JOIN") == 2, "FAILED: client needs banner + campaign joins"
    assert "c.clientid" in sql_client
    print("PASS: joins resolved only where the hierarchy requires them\n")

    print("=" * 70)
    print("TEST 5: entity IDs are bound parameters, never string-formatted (exchange/ClickHouse)")
    print("=" * 70)
    sql, params = qb.build_timeseries_query(EXCHANGE, "win_rate", days=14, entity_type="dsp_campaign")
    print(f"SQL    -> {sql}")
    print(f"params -> {params}")
    assert "{entity_id:UInt32}" in sql, "FAILED: entity_id not parameterized"
    assert "{days:UInt32}" in sql, "FAILED: days not parameterized"
    print("PASS: no SQL injection surface - values bound by the driver\n")

    print("=" * 70)
    print("TEST 5b: same guarantee for revive/MySQL, with its own bind style")
    print("=" * 70)
    sql, params = mysql_qb.build_timeseries_query("ctr", days=14, entity_type="campaign")
    print(f"SQL    -> {sql}")
    print(f"params -> {params}")
    assert ":entity_id" in sql, "FAILED: entity_id not parameterized"
    assert ":days" in sql, "FAILED: days not parameterized"
    print("PASS: no SQL injection surface - values bound by SQLAlchemy\n")

    print("=" * 70)
    print("TEST 6: ranking query supports a volume guard (revive/MySQL)")
    print("=" * 70)
    sql, params = mysql_qb.build_ranking_query("ctr", "zone", days=30, limit=5,
                                                min_volume_metric="impressions")
    print(f"SQL -> {sql}")
    assert "AS volume" in sql, "FAILED: volume column missing"
    assert "LIMIT :limit" in sql
    print("PASS: rankings can expose the volume behind each rate\n")

    print("=" * 70)
    print("TEST 7: unknown metric/entity fails loudly with a useful message")
    print("=" * 70)
    try:
        get_metric(REVIVE, "win_rate")   # exchange-only metric, wrong domain
        raise AssertionError("FAILED: should have rejected an out-of-domain metric")
    except ValueError as e:
        print(f"Correctly rejected: {e}")
    try:
        qb.build_timeseries_query(EXCHANGE, "win_rate", days=7, entity_type="zone")  # revive entity
        raise AssertionError("FAILED: should have rejected an out-of-domain entity")
    except ValueError as e:
        print(f"Correctly rejected: {e}")
    print("PASS: cross-domain mistakes caught at the registry, not in SQL\n")

    print("=" * 70)
    print("TEST 8: aggregate + entity list queries")
    print("=" * 70)
    sql, _ = qb.build_aggregate_query(EXCHANGE, ["bid_requests", "wins", "win_rate", "ecpm"], days=7)
    print(f"aggregate -> {sql}\n")
    assert "AS win_rate" in sql and "AS ecpm" in sql
    print(f"entity types (revive):   {mysql_qb.list_entity_types()}")
    print(f"entity types (exchange): {qb.list_entity_types(EXCHANGE)}")
    print(f"list query -> {mysql_qb.build_entity_list_query('zone')}")
    print("PASS\n")

    print("=" * 70)
    print("ALL SEMANTIC LAYER CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
