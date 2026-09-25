"""
Executes queries against two backends, chosen by domain: exchange goes to
ClickHouse via src.semantic.query_builder; revive goes to the real local
Revive Adserver MySQL database via src.semantic.mysql_query_builder.

Kept deliberately thin and separate from the query builders: the builders
decide query SHAPE (pure functions, fully unit-testable without a database
- see verify_semantic_layer.py), this class handles the two things that
need a live connection - picking the right backend for the domain, and
binding the entity_id runtime value before running it.
"""
from __future__ import annotations

import copy

import clickhouse_connect
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from src.config import Settings
from src.semantic import mysql_query_builder as mysql_qb
from src.semantic import query_builder as qb
from src.semantic.metric_registry import REVIVE


class AnalyticsClient:
    def __init__(self, settings: Settings) -> None:
        # database="default" because every ClickHouse query builder function
        # fully qualifies tables as "adexchange.xxx" - one client can serve
        # the exchange domain without switching connections.
        self._client = clickhouse_connect.get_client(
            host=settings.clickhouse_host, port=settings.clickhouse_port,
            database="default", username=settings.clickhouse_username,
            password=settings.clickhouse_password,
        )
        # Revive domain: real local Revive Adserver MySQL database, already
        # scoped to `mysql_database` - mysql_query_builder's table names are
        # deliberately unqualified. URL.create (not an f-string) because the
        # password can contain characters like "@" that would otherwise be
        # misparsed as the userinfo/host separator.
        mysql_url = URL.create(
            "mysql+pymysql", username=settings.mysql_username, password=settings.mysql_password,
            host=settings.mysql_host, port=settings.mysql_port, database=settings.mysql_database,
        )
        self._mysql_engine = create_engine(mysql_url)
        # None = admin (all of Revive). Set only through scoped(); see
        # mysql_query_builder.apply_scope for how it narrows each query.
        self._agency_id: int | None = None

    @property
    def agency_id(self) -> int | None:
        return self._agency_id

    def scoped(self, agency_id: int | None) -> AnalyticsClient:
        """A copy limited to one Revive manager's data (None = unrestricted).
        Shares this client's connections - it's cheap to make per request."""
        clone = copy.copy(self)
        clone._agency_id = agency_id
        return clone

    def _bind_entity(self, params: dict, entity_type: str | None, entity_id: int | None) -> dict:
        if entity_type and entity_id is None:
            raise ValueError(f"entity_id is required when entity_type={entity_type!r} is given")
        if entity_type and entity_id is not None:
            params = {**params, "entity_id": entity_id}
        return params

    def _mysql_query_df(self, sql: str, params: dict) -> pd.DataFrame:
        return pd.read_sql_query(text(sql), self._mysql_engine, params=params)

    def timeseries(self, domain: str, metric: str, days: int,
                    entity_type: str | None = None, entity_id: int | None = None,
                    grain: str = "day") -> pd.DataFrame:
        if domain == REVIVE:
            sql, params = mysql_qb.build_timeseries_query(metric, days, entity_type, grain, self._agency_id)
            params = self._bind_entity(params, entity_type, entity_id)
            return self._mysql_query_df(sql, params)
        sql, params = qb.build_timeseries_query(domain, metric, days, entity_type, grain)
        params = self._bind_entity(params, entity_type, entity_id)
        return self._client.query_df(sql, parameters=params)

    def aggregate(self, domain: str, metrics: list[str], days: int,
                  entity_type: str | None = None, entity_id: int | None = None) -> dict:
        if domain == REVIVE:
            sql, params = mysql_qb.build_aggregate_query(metrics, days, entity_type, agency_id=self._agency_id)
            params = self._bind_entity(params, entity_type, entity_id)
            df = self._mysql_query_df(sql, params)
        else:
            sql, params = qb.build_aggregate_query(domain, metrics, days, entity_type)
            params = self._bind_entity(params, entity_type, entity_id)
            df = self._client.query_df(sql, parameters=params)
        return df.iloc[0].to_dict() if not df.empty else {m: None for m in metrics}

    def period_aggregate(self, domain: str, metrics: list[str], start_days_ago: int, end_days_ago: int,
                          entity_type: str | None = None, entity_id: int | None = None) -> dict:
        if domain == REVIVE:
            sql, params = mysql_qb.build_period_aggregate_query(metrics, start_days_ago, end_days_ago, entity_type,
                                                                self._agency_id)
            params = self._bind_entity(params, entity_type, entity_id)
            df = self._mysql_query_df(sql, params)
        else:
            sql, params = qb.build_period_aggregate_query(domain, metrics, start_days_ago, end_days_ago, entity_type)
            params = self._bind_entity(params, entity_type, entity_id)
            df = self._client.query_df(sql, parameters=params)
        return df.iloc[0].to_dict() if not df.empty else {m: None for m in metrics}

    def ranking(self, domain: str, metric: str, entity_type: str, days: int,
                limit: int = 10, ascending: bool = False, min_volume_metric: str | None = None) -> pd.DataFrame:
        if domain == REVIVE:
            sql, params = mysql_qb.build_ranking_query(metric, entity_type, days, limit, ascending, min_volume_metric,
                                                       self._agency_id)
            return self._mysql_query_df(sql, params)
        sql, params = qb.build_ranking_query(domain, metric, entity_type, days, limit, ascending, min_volume_metric)
        return self._client.query_df(sql, parameters=params)

    def child_breakdown(self, domain: str, metric: str, child_entity_type: str,
                         start_days_ago: int, end_days_ago: int,
                         parent_entity_type: str | None = None, parent_entity_id: int | None = None,
                         limit: int = 50) -> pd.DataFrame:
        if domain == REVIVE:
            sql, params = mysql_qb.build_child_breakdown_query(
                metric, child_entity_type, start_days_ago, end_days_ago, parent_entity_type, limit, self._agency_id
            )
            params = self._bind_entity(params, parent_entity_type, parent_entity_id)
            return self._mysql_query_df(sql, params)
        sql, params = qb.build_child_breakdown_query(
            domain, metric, child_entity_type, start_days_ago, end_days_ago, parent_entity_type, limit
        )
        params = self._bind_entity(params, parent_entity_type, parent_entity_id)
        return self._client.query_df(sql, parameters=params)

    def entity_list(self, domain: str, entity_type: str, search: str | None = None,
                    parent_type: str | None = None, parent_id: int | None = None,
                    limit: int | None = None) -> pd.DataFrame:
        if parent_type and parent_id is None:
            raise ValueError(f"parent_id is required when parent_type={parent_type!r} is given")
        if domain == REVIVE:
            sql, params = mysql_qb.build_entity_list_query(entity_type, search, parent_type, limit, self._agency_id)
            if parent_type:
                params = {**params, "parent_id": parent_id}
            return self._mysql_query_df(sql, params)
        if parent_type:
            raise ValueError(f"parent filtering isn't supported for domain {domain!r}")
        sql = qb.build_entity_list_query(domain, entity_type)
        df = self._client.query_df(sql)
        if search:
            df = df[df["name"].str.contains(search, case=False, regex=False)]
        return df.head(limit) if limit is not None else df

    def raw_query(self, sql: str, params: dict, domain: str) -> pd.DataFrame:
        """Thin execution primitive for query strings built by OUR OWN code
        (see cross_analysis.py, realtime_exchange.py) - not a general
        execute_sql escape hatch. The LLM only ever supplies typed
        parameters (minutes, ad_unit_id), never SQL text; the query shape
        itself is fixed in this codebase. `domain` picks which backend the
        caller's own SQL was written for."""
        if domain == REVIVE:
            return self._mysql_query_df(sql, params)
        return self._client.query_df(sql, parameters=params)

    def data_freshness(self, domain: str) -> dict:
        if domain == REVIVE:
            fact_table, time_col = mysql_qb.FACT_TABLE
            sql = f"SELECT MAX({time_col}) AS last_event, UTC_TIMESTAMP() AS now FROM {fact_table}"
            df = self._mysql_query_df(sql, {})
        else:
            fact_table, time_col = qb.FACT_TABLES[domain]
            sql = f"SELECT max({time_col}) AS last_event, now() AS now FROM {fact_table}"
            df = self._client.query_df(sql)
        if df.empty or pd.isna(df.iloc[0]["last_event"]):
            return {"last_event": None, "lag_minutes": None, "status": "no_data"}
        last_event = df.iloc[0]["last_event"]
        now = df.iloc[0]["now"]
        lag_minutes = (now - last_event).total_seconds() / 60
        status = "healthy" if lag_minutes < 180 else "stale"  # hourly-rollup domains: >3h old is stale
        return {"last_event": str(last_event), "lag_minutes": round(lag_minutes, 1), "status": status}
