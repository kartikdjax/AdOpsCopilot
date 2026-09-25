"""
Revive admin tools: inspect one object's configuration, and run named
health checks. Both are about how the ad server is SET UP, where every
other Revive tool is about how it PERFORMED.

Same safety model as cross_analysis.py: every SQL string is fixed in this
file and executed through AnalyticsClient.raw_query. The LLM only picks an
object type / check name from a registry and supplies typed integers -
never SQL text, never a column name. The field lists below are the
allowlist: anything not selected here (passwords, session data) can't be
returned, whatever the question.

Also: get_revive_audit_log (who changed what, from rv_audit) and
get_system_status (Revive version, plugins, maintenance health), which
get_data_freshness attaches for the revive domain.

Manager scoping: a scoped AnalyticsClient (client.agency_id set) limits
every result here to that manager's own objects, accounts and audit
events, reusing mysql_query_builder.OWNED_IDS.

Times compare against UTC_TIMESTAMP() because Revive stores UTC.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import phpserialize
from pydantic import BaseModel

from src.semantic.analytics_client import AnalyticsClient
from src.semantic.metric_registry import REVIVE
from src.semantic.mysql_query_builder import OWNED_ACCOUNTS, OWNED_IDS, apply_scope

MAX_ROWS = 50

# Real Revive code values (OA_ENTITY_STATUS_*, MAX_FINANCE_*), decoded so
# the LLM never has to guess what status=2 means.
_STATUS = {0: "running", 1: "paused", 2: "awaiting start", 3: "expired", 4: "inactive",
           21: "awaiting approval", 22: "rejected"}
_FINANCE = {1: "CPM", 2: "CPC", 3: "CPA", 4: "monthly tenancy", 5: "revenue share %",
            6: "basket value %", 7: "items count", 8: "any variable", 9: "variable sum"}
_DECODERS = {"status": _STATUS, "revenue_type": _FINANCE, "cost_type": _FINANCE}
# Revive stores "no goal" as -1 (or 0) in the booked_* columns.
_BOOKED = ("booked_impressions", "booked_clicks", "booked_conversions")


def _clean(value: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ")
    if hasattr(value, "item"):  # numpy scalar -> plain Python
        return value.item()
    return value


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for raw in df.to_dict("records"):
        row = {k: _clean(v) for k, v in raw.items()}
        for key, codes in _DECODERS.items():
            if row.get(key) is not None:
                row[f"{key}_label"] = codes.get(int(row[key]), "unknown")
        for key in _BOOKED:
            if key in row and row[key] is not None and row[key] <= 0:
                row[key] = "unlimited"
        rows.append(row)
    return rows


# ---------------------------------------------------------------------
# inspect_revive_object
# ---------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ObjectDef:
    fields_sql: str                                   # one row, bound to :id
    extra_fields_sql: tuple[str, ...] = ()            # one row each, merged into fields
    links: dict[str, str] = field(default_factory=dict)  # name -> many rows, bound to :id


_DELIVERED_SINCE_START = (
    "SELECT SUM(f.impressions) AS delivered_impressions, SUM(f.clicks) AS delivered_clicks, "
    "ROUND(SUM(f.total_revenue), 2) AS revenue_to_date, MAX(IF(f.impressions > 0, f.date_time, NULL)) AS last_delivery "
    "FROM rv_data_summary_ad_hourly f JOIN rv_banners b ON b.bannerid = f.ad_id "
    "JOIN rv_campaigns c ON c.campaignid = b.campaignid "
    "WHERE b.campaignid = :id AND f.date_time >= c.activate_time"
)

# Who can see an advertiser/website: its own account, its manager's
# account, and admin accounts.
_ACCESS_SQL = (
    "SELECT u.user_id, u.username, u.contact_name, u.active, u.date_last_login, a.account_type AS via "
    "FROM rv_account_user_assoc aua JOIN rv_users u ON u.user_id = aua.user_id "
    "JOIN rv_accounts a ON a.account_id = aua.account_id "
    "WHERE aua.account_id IN ({own}, {manager}) OR a.account_type = 'ADMIN' "
    "ORDER BY FIELD(a.account_type, '{own_type}', 'MANAGER', 'ADMIN'), u.user_id"
)

OBJECTS: dict[str, ObjectDef] = {
    "campaign": ObjectDef(
        fields_sql=(
            "SELECT c.campaignid AS id, c.campaignname AS name, c.clientid AS client_id, "
            "cl.clientname AS client_name, cl.agencyid AS manager_id, ag.name AS manager_name, "
            "c.status, c.priority, c.weight, c.activate_time, c.expire_time, "
            "c.views AS booked_impressions, c.clicks AS booked_clicks, c.conversions AS booked_conversions, "
            "c.revenue, c.revenue_type, c.capping, c.session_capping, c.block AS block_seconds, c.updated "
            "FROM rv_campaigns c LEFT JOIN rv_clients cl ON cl.clientid = c.clientid "
            "LEFT JOIN rv_agency ag ON ag.agencyid = cl.agencyid WHERE c.campaignid = :id"
        ),
        extra_fields_sql=(_DELIVERED_SINCE_START,),
        links={
            "banners": "SELECT bannerid AS banner_id, description AS name, status, width, height "
                       "FROM rv_banners WHERE campaignid = :id ORDER BY bannerid",
            "linked_zones": "SELECT z.zoneid AS zone_id, z.zonename AS name, z.width, z.height "
                            "FROM rv_placement_zone_assoc p JOIN rv_zones z ON z.zoneid = p.zone_id "
                            "WHERE p.placement_id = :id ORDER BY z.zoneid",
        },
    ),
    "banner": ObjectDef(
        fields_sql=(
            "SELECT b.bannerid AS id, b.description AS name, b.campaignid AS campaign_id, "
            "c.campaignname AS campaign_name, b.status, b.storagetype, b.contenttype, b.width, b.height, "
            "b.url AS click_url, b.weight, b.capping, b.session_capping, b.block AS block_seconds, b.updated "
            "FROM rv_banners b LEFT JOIN rv_campaigns c ON c.campaignid = b.campaignid WHERE b.bannerid = :id"
        ),
        extra_fields_sql=(
            "SELECT MAX(date_time) AS last_delivery FROM rv_data_summary_ad_hourly "
            "WHERE ad_id = :id AND impressions > 0",
        ),
        links={
            "linked_zones": "SELECT z.zoneid AS zone_id, z.zonename AS name, z.width, z.height "
                            "FROM rv_ad_zone_assoc az JOIN rv_zones z ON z.zoneid = az.zone_id "
                            "WHERE az.ad_id = :id ORDER BY z.zoneid",
            "targeting_rules": "SELECT executionorder AS rule_order, logical, type, comparison, data "
                               "FROM rv_acls WHERE bannerid = :id ORDER BY executionorder",
        },
    ),
    "zone": ObjectDef(
        fields_sql=(
            "SELECT z.zoneid AS id, z.zonename AS name, z.affiliateid AS website_id, a.name AS website_name, "
            "a.agencyid AS manager_id, ag.name AS manager_name, z.zonetype, z.delivery, z.width, z.height, "
            "z.cost, z.cost_type, z.capping, z.session_capping, z.block AS block_seconds, z.updated "
            "FROM rv_zones z LEFT JOIN rv_affiliates a ON a.affiliateid = z.affiliateid "
            "LEFT JOIN rv_agency ag ON ag.agencyid = a.agencyid WHERE z.zoneid = :id"
        ),
        extra_fields_sql=(
            "SELECT SUM(requests) AS requests_last_7d, SUM(impressions) AS impressions_last_7d "
            "FROM rv_data_summary_ad_hourly WHERE zone_id = :id "
            "AND date_time >= UTC_TIMESTAMP() - INTERVAL 7 DAY",
        ),
        links={
            "linked_banners": "SELECT b.bannerid AS banner_id, b.description AS name, b.width, b.height, "
                              "b.campaignid AS campaign_id "
                              "FROM rv_ad_zone_assoc az JOIN rv_banners b ON b.bannerid = az.ad_id "
                              "WHERE az.zone_id = :id ORDER BY b.bannerid",
            "linked_campaigns": "SELECT c.campaignid AS campaign_id, c.campaignname AS name, c.status "
                                "FROM rv_placement_zone_assoc p JOIN rv_campaigns c ON c.campaignid = p.placement_id "
                                "WHERE p.zone_id = :id ORDER BY c.campaignid",
        },
    ),
    "affiliate": ObjectDef(
        fields_sql=(
            "SELECT a.affiliateid AS id, a.name, a.website, a.contact, a.email, a.agencyid AS manager_id, "
            "ag.name AS manager_name, a.updated "
            "FROM rv_affiliates a LEFT JOIN rv_agency ag ON ag.agencyid = a.agencyid WHERE a.affiliateid = :id"
        ),
        links={
            "zones": "SELECT zoneid AS zone_id, zonename AS name, width, height "
                     "FROM rv_zones WHERE affiliateid = :id ORDER BY zoneid",
            "users_with_access": _ACCESS_SQL.format(
                own="(SELECT account_id FROM rv_affiliates WHERE affiliateid = :id)",
                manager="(SELECT ag.account_id FROM rv_affiliates a JOIN rv_agency ag "
                        "ON ag.agencyid = a.agencyid WHERE a.affiliateid = :id)",
                own_type="TRAFFICKER"),
        },
    ),
    "client": ObjectDef(
        fields_sql=(
            "SELECT cl.clientid AS id, cl.clientname AS name, cl.contact, cl.email, cl.agencyid AS manager_id, "
            "ag.name AS manager_name, cl.updated "
            "FROM rv_clients cl LEFT JOIN rv_agency ag ON ag.agencyid = cl.agencyid WHERE cl.clientid = :id"
        ),
        links={
            "campaigns": "SELECT campaignid AS campaign_id, campaignname AS name, status, activate_time, "
                         "expire_time FROM rv_campaigns WHERE clientid = :id ORDER BY campaignid",
            "users_with_access": _ACCESS_SQL.format(
                own="(SELECT account_id FROM rv_clients WHERE clientid = :id)",
                manager="(SELECT ag.account_id FROM rv_clients cl JOIN rv_agency ag "
                        "ON ag.agencyid = cl.agencyid WHERE cl.clientid = :id)",
                own_type="ADVERTISER"),
        },
    ),
    "manager": ObjectDef(
        fields_sql="SELECT agencyid AS id, name, contact, email, status, updated FROM rv_agency WHERE agencyid = :id",
        links={
            "advertisers": "SELECT clientid AS client_id, clientname AS name FROM rv_clients "
                           "WHERE agencyid = :id ORDER BY clientid",
            "websites": "SELECT affiliateid AS website_id, name, website FROM rv_affiliates "
                        "WHERE agencyid = :id ORDER BY affiliateid",
            "users": "SELECT u.user_id, u.username, u.contact_name, u.active, u.date_last_login "
                     "FROM rv_agency ag JOIN rv_account_user_assoc aua ON aua.account_id = ag.account_id "
                     "JOIN rv_users u ON u.user_id = aua.user_id WHERE ag.agencyid = :id ORDER BY u.user_id",
        },
    ),
    "user": ObjectDef(
        # Deliberately no password, sso_user_id or comments.
        fields_sql=(
            "SELECT user_id AS id, username AS name, contact_name, email_address, active, language, "
            "date_created, date_last_login FROM rv_users WHERE user_id = :id"
        ),
        links={
            "accounts": "SELECT a.account_id, a.account_type, a.account_name, aua.linked "
                        "FROM rv_account_user_assoc aua JOIN rv_accounts a ON a.account_id = aua.account_id "
                        "WHERE aua.user_id = :id ORDER BY a.account_id",
        },
    ),
}


def _owns(client: AnalyticsClient, object_type: str, object_id: int) -> bool:
    if client.agency_id is None:
        return True
    params = {"id": object_id, "scope_agency_id": client.agency_id}
    df = client.raw_query(f"SELECT :id IN ({OWNED_IDS[object_type]}) AS owned", params, domain=REVIVE)
    return bool(df.iloc[0]["owned"])


class InspectResult(BaseModel):
    object_type: str
    object_id: int
    fields: dict[str, Any]
    links: dict[str, list[dict[str, Any]]]


def inspect_revive_object(client: AnalyticsClient, object_type: str, object_id: int) -> InspectResult:
    obj = OBJECTS.get(object_type)
    if obj is None:
        raise ValueError(f"Unknown object_type {object_type!r}. Available: {', '.join(OBJECTS)}")
    params = {"id": object_id}
    rows = _records(client.raw_query(obj.fields_sql, params, domain=REVIVE)) if _owns(client, object_type,
                                                                                      object_id) else []
    if not rows:  # same message whether missing or someone else's - existence isn't leaked
        raise ValueError(f"No {object_type} with id {object_id}. Use list_entities to find the right ID.")
    fields = rows[0]
    for sql in obj.extra_fields_sql:
        extra = _records(client.raw_query(sql, params, domain=REVIVE))
        if extra:
            fields.update(extra[0])
    links = {name: _records(client.raw_query(sql, params, domain=REVIVE))[:MAX_ROWS]
             for name, sql in obj.links.items()}
    if client.agency_id is not None:  # a manager sees their own people, not the platform admins
        links = {name: [r for r in rows if r.get("via") != "ADMIN"] for name, rows in links.items()}
    return InspectResult(object_type=object_type, object_id=object_id, fields=fields, links=links)


# ---------------------------------------------------------------------
# run_revive_check
# ---------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CheckDef:
    description: str             # the rule in words - returned with every result
    sql: str                     # no ORDER BY / LIMIT - run_revive_check wraps it
    order_by: str                # over the check's output columns
    scope: tuple[str, str]       # (owned object type, output column) for manager scoping
    defaults: dict[str, int] = field(default_factory=dict)


_CAMPAIGN_ADVERTISER = "FROM rv_campaigns c LEFT JOIN rv_clients cl ON cl.clientid = c.clientid "

CHECKS: dict[str, CheckDef] = {
    "campaigns_expiring": CheckDef(
        description="Running campaigns whose end date falls within the next `days` days.",
        defaults={"days": 7},
        sql=("SELECT c.campaignid AS campaign_id, c.campaignname AS campaign_name, cl.clientname AS advertiser, "
             "c.expire_time, ROUND(TIMESTAMPDIFF(HOUR, UTC_TIMESTAMP(), c.expire_time) / 24, 1) AS days_left "
             + _CAMPAIGN_ADVERTISER +
             "WHERE c.status = 0 AND c.expire_time > UTC_TIMESTAMP() "
             "AND c.expire_time <= UTC_TIMESTAMP() + INTERVAL :days DAY"),
        order_by="expire_time", scope=("campaign", "campaign_id"),
    ),
    "campaigns_behind_pace": CheckDef(
        description=("Running campaigns with booked impressions whose delivery so far is below "
                     "`threshold_pct`% of the expected amount (booked x time elapsed / total run time). "
                     "required_daily_impressions is what it must deliver per day to finish."),
        defaults={"threshold_pct": 90},
        sql=("SELECT campaign_id, campaign_name, booked_impressions, delivered, expected_by_now, "
             "ROUND(delivered / NULLIF(expected_by_now, 0) * 100, 1) AS pace_pct, "
             "ROUND(GREATEST(booked_impressions - delivered, 0) / days_left) AS required_daily_impressions, "
             "expire_time FROM ("
             "  SELECT c.campaignid AS campaign_id, c.campaignname AS campaign_name, c.views AS booked_impressions, "
             "  c.expire_time, COALESCE(SUM(f.impressions), 0) AS delivered, "
             "  ROUND(c.views * TIMESTAMPDIFF(SECOND, c.activate_time, UTC_TIMESTAMP()) "
             "        / TIMESTAMPDIFF(SECOND, c.activate_time, c.expire_time)) AS expected_by_now, "
             "  GREATEST(TIMESTAMPDIFF(HOUR, UTC_TIMESTAMP(), c.expire_time) / 24, 1) AS days_left "
             "  FROM rv_campaigns c LEFT JOIN rv_banners b ON b.campaignid = c.campaignid "
             "  LEFT JOIN rv_data_summary_ad_hourly f ON f.ad_id = b.bannerid AND f.date_time >= c.activate_time "
             "  WHERE c.status = 0 AND c.views > 0 AND c.activate_time <= UTC_TIMESTAMP() "
             "  AND c.expire_time > UTC_TIMESTAMP() "
             "  GROUP BY c.campaignid, c.campaignname, c.views, c.activate_time, c.expire_time"
             ") t WHERE delivered < expected_by_now * :threshold_pct / 100"),
        order_by="pace_pct", scope=("campaign", "campaign_id"),
    ),
    "active_no_delivery": CheckDef(
        description=("Running campaigns, started more than `hours` hours ago and not yet ended, "
                     "with zero impressions in the last `hours` hours."),
        defaults={"hours": 24},
        sql=("SELECT c.campaignid AS campaign_id, c.campaignname AS campaign_name, cl.clientname AS advertiser, "
             "(SELECT MAX(f.date_time) FROM rv_data_summary_ad_hourly f JOIN rv_banners b ON b.bannerid = f.ad_id "
             " WHERE b.campaignid = c.campaignid AND f.impressions > 0) AS last_delivery "
             + _CAMPAIGN_ADVERTISER +
             "WHERE c.status = 0 AND c.activate_time <= UTC_TIMESTAMP() - INTERVAL :hours HOUR "
             "AND (c.expire_time IS NULL OR c.expire_time > UTC_TIMESTAMP()) "
             "AND NOT EXISTS (SELECT 1 FROM rv_data_summary_ad_hourly f JOIN rv_banners b ON b.bannerid = f.ad_id "
             " WHERE b.campaignid = c.campaignid AND f.impressions > 0 "
             " AND f.date_time >= UTC_TIMESTAMP() - INTERVAL :hours HOUR)"),
        order_by="campaign_id", scope=("campaign", "campaign_id"),
    ),
    "campaigns_not_running": CheckDef(
        description="Campaigns that are paused, awaiting start, expired or otherwise not running now.",
        sql=("SELECT c.campaignid AS campaign_id, c.campaignname AS campaign_name, cl.clientname AS advertiser, "
             "c.status, c.activate_time, c.expire_time "
             + _CAMPAIGN_ADVERTISER +
             "WHERE c.status <> 0 OR c.activate_time > UTC_TIMESTAMP() OR c.expire_time <= UTC_TIMESTAMP()"),
        order_by="campaign_id", scope=("campaign", "campaign_id"),
    ),
    "unlinked_zones": CheckDef(
        description="Zones with no banner and no campaign linked - they can't serve anything.",
        sql=("SELECT z.zoneid AS zone_id, z.zonename AS zone_name, a.name AS website, ag.name AS manager "
             "FROM rv_zones z LEFT JOIN rv_affiliates a ON a.affiliateid = z.affiliateid "
             "LEFT JOIN rv_agency ag ON ag.agencyid = a.agencyid "
             "WHERE NOT EXISTS (SELECT 1 FROM rv_ad_zone_assoc az WHERE az.zone_id = z.zoneid AND az.ad_id > 0) "
             "AND NOT EXISTS (SELECT 1 FROM rv_placement_zone_assoc p WHERE p.zone_id = z.zoneid)"),
        order_by="zone_id", scope=("zone", "zone_id"),
    ),
    "size_mismatch": CheckDef(
        description="Banners linked to a fixed-size zone whose width x height differs from the banner's.",
        sql=("SELECT b.bannerid AS banner_id, b.description AS banner_name, "
             "CONCAT(b.width, 'x', b.height) AS banner_size, z.zoneid AS zone_id, z.zonename AS zone_name, "
             "CONCAT(z.width, 'x', z.height) AS zone_size "
             "FROM rv_ad_zone_assoc az JOIN rv_banners b ON b.bannerid = az.ad_id "
             "JOIN rv_zones z ON z.zoneid = az.zone_id "
             "WHERE z.width > 0 AND z.height > 0 AND b.width > 0 AND b.height > 0 "
             "AND (b.width <> z.width OR b.height <> z.height)"),
        order_by="banner_id, zone_id", scope=("banner", "banner_id"),
    ),
    "zero_fill_zones": CheckDef(
        description=("Zones with at least `min_requests` ad requests but zero impressions "
                     "over the last `days` days."),
        defaults={"days": 7, "min_requests": 1000},
        sql=("SELECT f.zone_id, z.zonename AS zone_name, SUM(f.requests) AS requests, "
             "SUM(f.impressions) AS impressions "
             "FROM rv_data_summary_ad_hourly f LEFT JOIN rv_zones z ON z.zoneid = f.zone_id "
             "WHERE f.date_time >= UTC_TIMESTAMP() - INTERVAL :days DAY "
             "GROUP BY f.zone_id, z.zonename "
             "HAVING SUM(f.requests) >= :min_requests AND SUM(f.impressions) = 0"),
        order_by="requests DESC", scope=("zone", "zone_id"),
    ),
    "inactive_users": CheckDef(
        description="Active users who haven't logged in for `days` days, or have never logged in.",
        defaults={"days": 90},
        sql=("SELECT u.user_id, u.username, u.contact_name, u.date_created, u.date_last_login, "
             "GROUP_CONCAT(DISTINCT a.account_name ORDER BY a.account_name SEPARATOR ', ') AS accounts "
             "FROM rv_users u LEFT JOIN rv_account_user_assoc aua ON aua.user_id = u.user_id "
             "LEFT JOIN rv_accounts a ON a.account_id = aua.account_id "
             "WHERE u.active = 1 AND (u.date_last_login IS NULL "
             "OR u.date_last_login < UTC_TIMESTAMP() - INTERVAL :days DAY) "
             "GROUP BY u.user_id, u.username, u.contact_name, u.date_created, u.date_last_login"),
        order_by="date_last_login IS NOT NULL, date_last_login", scope=("user", "user_id"),
    ),
}


class CheckResult(BaseModel):
    check: str
    description: str
    params: dict[str, int]
    rows: list[dict[str, Any]]
    truncated: bool


class CheckOverview(BaseModel):
    """check_name='all': how many problems each check finds, at its defaults."""
    counts: dict[str, int]
    descriptions: dict[str, str]


def _resolve_params(check_name: str, check: CheckDef, overrides: dict[str, int | None]) -> dict[str, int]:
    given = {k: v for k, v in overrides.items() if v is not None}
    unknown = set(given) - set(check.defaults)
    if unknown:
        allowed = ", ".join(check.defaults) or "none"
        raise ValueError(f"{check_name!r} doesn't take {', '.join(sorted(unknown))}. Allowed: {allowed}")
    if any(v < 0 for v in given.values()):
        raise ValueError("Check parameters must be zero or positive")
    return {**check.defaults, **given}


def _scoped_check(client: AnalyticsClient, check: CheckDef, params: dict) -> tuple[str, dict]:
    """The check's rows, limited to the manager's own objects when scoped."""
    where: list[str] = []
    params = dict(params)
    object_type, column = check.scope
    apply_scope(where, params, client.agency_id, f"t.{column} IN ({OWNED_IDS[object_type]})")
    sql = f"SELECT * FROM ({check.sql}) t" + (f" WHERE {' AND '.join(where)}" if where else "")
    return sql, params


def run_revive_check(client: AnalyticsClient, check_name: str, **overrides: int | None) -> CheckResult | CheckOverview:
    if check_name == "all":
        counts = {}
        for name, check in CHECKS.items():
            sql, params = _scoped_check(client, check, check.defaults)
            counts[name] = int(client.raw_query(f"SELECT COUNT(*) AS n FROM ({sql}) c", params,
                                                domain=REVIVE).iloc[0]["n"])
        return CheckOverview(counts=counts, descriptions={n: c.description for n, c in CHECKS.items()})

    check = CHECKS.get(check_name)
    if check is None:
        raise ValueError(f"Unknown check {check_name!r}. Available: all, {', '.join(CHECKS)}")
    params = _resolve_params(check_name, check, overrides)
    sql, bound = _scoped_check(client, check, params)
    df = client.raw_query(f"{sql} ORDER BY {check.order_by} LIMIT :row_limit",
                          {**bound, "row_limit": MAX_ROWS + 1}, domain=REVIVE)
    rows = _records(df)
    return CheckResult(check=check_name, description=check.description, params=params,
                       rows=rows[:MAX_ROWS], truncated=len(rows) > MAX_ROWS)


# ---------------------------------------------------------------------
# get_revive_audit_log
# ---------------------------------------------------------------------
_AUDIT_ACTIONS = {1: "created", 2: "changed", 3: "deleted"}
_AUDIT_CONTEXTS = {  # Revive's rv_audit.context -> the names every other tool uses
    "campaigns": "campaign", "banners": "banner", "zones": "zone", "clients": "client",
    "affiliates": "affiliate", "agency": "manager", "users": "user", "accounts": "account",
    "ad_zone_assoc": "banner-zone link", "placement_zone_assoc": "campaign-zone link",
    "acls": "targeting rule", "channel": "channel", "trackers": "tracker",
    "preferences": "preference", "account_preference_assoc": "account preference",
    "account_user_assoc": "user access",
}
# object_type -> its own audit context, plus link contexts that belong to
# it (matched on a key inside the audit details, since a link row's
# contextid is the link's own ID).
_AUDIT_OBJECTS: dict[str, tuple[str, dict[str, str]]] = {
    "campaign": ("campaigns", {"placement_zone_assoc": "placement_id"}),
    "banner": ("banners", {"ad_zone_assoc": "ad_id", "acls": "bannerid"}),
    "zone": ("zones", {"ad_zone_assoc": "zone_id", "placement_zone_assoc": "zone_id"}),
    "client": ("clients", {}),
    "affiliate": ("affiliates", {}),
    "manager": ("agency", {}),
    "user": ("users", {}),
}
# Campaign columns whose raw names mislead: they're goals, not delivery.
_AUDIT_FIELD_NAMES = {"campaigns": {"views": "booked_impressions", "clicks": "booked_clicks",
                                    "conversions": "booked_conversions"}}
_AUDIT_SCAN_LIMIT = 2000  # rows read before the object filter narrows to MAX_ROWS


class AuditChange(BaseModel):
    field: str
    was: Any = None
    now: Any = None


class AuditEvent(BaseModel):
    audit_id: int
    time_utc: str
    user: str | None
    action: str
    object_type: str
    object_id: int | None
    object_name: str | None
    changes: list[AuditChange]


class AuditLogResult(BaseModel):
    days: int
    filters: dict[str, Any]
    events: list[AuditEvent]
    truncated: bool


def _decode_value(field_name: str, value: Any) -> Any:
    codes = _DECODERS.get(field_name)
    if codes is not None and isinstance(value, int):
        return f"{value} ({codes.get(value, 'unknown')})"
    return value


def _parse_details(raw: str) -> dict[str, Any]:
    try:
        parsed = phpserialize.loads(raw.encode("utf-8"), decode_strings=True)
    except (ValueError, TypeError):
        return {"unparsed": raw[:500]}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _audit_changes(details: dict[str, Any], action: str, context: str) -> list[AuditChange]:
    changes = []
    renames = _AUDIT_FIELD_NAMES.get(context, {})
    for raw_key, value in details.items():
        if raw_key == "key_desc" or "password" in str(raw_key).lower():
            continue
        key = renames.get(raw_key, raw_key)
        if isinstance(value, dict) and {"was", "is"} <= set(value):
            changes.append(AuditChange(field=key, was=_decode_value(key, value["was"]),
                                       now=_decode_value(key, value["is"])))
        elif action == "deleted":
            changes.append(AuditChange(field=key, was=_decode_value(key, value)))
        else:
            changes.append(AuditChange(field=key, now=_decode_value(key, value)))
    return changes


def get_revive_audit_log(client: AnalyticsClient, object_type: str | None = None, object_id: int | None = None,
                         username: str | None = None, action: str | None = None,
                         days: int = 7) -> AuditLogResult:
    if object_id is not None and object_type is None:
        raise ValueError("object_id needs object_type too")
    if object_type is not None and object_type not in _AUDIT_OBJECTS:
        raise ValueError(f"Unknown object_type {object_type!r}. Available: {', '.join(_AUDIT_OBJECTS)}")
    action_ids = {v: k for k, v in _AUDIT_ACTIONS.items()}
    if action is not None and action not in action_ids:
        raise ValueError(f"Unknown action {action!r}. Available: {', '.join(action_ids)}")
    if days < 0:
        raise ValueError("days must be zero or positive")

    where = ["updated >= UTC_TIMESTAMP() - INTERVAL :days DAY"]
    params: dict[str, Any] = {"days": days, "scan_limit": _AUDIT_SCAN_LIMIT}
    own_context, link_keys = _AUDIT_OBJECTS[object_type] if object_type else (None, {})
    if object_type:
        contexts = (own_context, *link_keys)
        where.append(f"context IN ({', '.join(f':ctx{i}' for i in range(len(contexts)))})")
        params.update({f"ctx{i}": c for i, c in enumerate(contexts)})
    if username:
        where.append("username = :username")
        params["username"] = username
    if action:
        where.append("actionid = :action_id")
        params["action_id"] = action_ids[action]
    apply_scope(where, params, client.agency_id,
                f"(account_id IN ({OWNED_ACCOUNTS}) OR advertiser_account_id IN ({OWNED_ACCOUNTS}) "
                f"OR website_account_id IN ({OWNED_ACCOUNTS}))")
    sql = (f"SELECT auditid, actionid, context, contextid, details, username, updated FROM rv_audit "
           f"WHERE {' AND '.join(where)} ORDER BY updated DESC, auditid DESC LIMIT :scan_limit")
    df = client.raw_query(sql, params, domain=REVIVE)

    events = []
    for row in _records(df):
        details = _parse_details(row["details"] or "")
        if object_id is not None:
            if row["context"] == own_context:
                if row["contextid"] != object_id:
                    continue
            elif details.get(link_keys[row["context"]]) != object_id:
                continue
        action_name = _AUDIT_ACTIONS.get(row["actionid"], "unknown")
        events.append(AuditEvent(
            audit_id=row["auditid"], time_utc=row["updated"], user=row["username"], action=action_name,
            object_type=_AUDIT_CONTEXTS.get(row["context"], row["context"]),
            object_id=row["contextid"] or None, object_name=details.get("key_desc"),
            changes=_audit_changes(details, action_name, row["context"]),
        ))
    filters = {k: v for k, v in {"object_type": object_type, "object_id": object_id, "username": username,
                                 "action": action}.items() if v is not None}
    return AuditLogResult(days=days, filters=filters, events=events[:MAX_ROWS],
                          truncated=len(events) > MAX_ROWS or len(df) == _AUDIT_SCAN_LIMIT)


# ---------------------------------------------------------------------
# System status (attached to get_data_freshness for revive)
# ---------------------------------------------------------------------
MAINTENANCE_OVERDUE_MINUTES = 120  # Revive maintenance runs hourly


class MaintenanceRun(BaseModel):
    last_run_utc: str | None
    minutes_ago: float | None
    status: str  # "ok" | "overdue" | "never_run"


class SystemStatus(BaseModel):
    revive_version: str | None
    plugins: dict[str, str]
    statistics_maintenance: MaintenanceRun
    priority_maintenance: MaintenanceRun
    warnings: list[str]


def _maintenance_run(client: AnalyticsClient, table: str) -> MaintenanceRun:
    df = client.raw_query(f"SELECT MAX(end_run) AS last_run, "
                          f"TIMESTAMPDIFF(MINUTE, MAX(end_run), UTC_TIMESTAMP()) AS minutes_ago FROM {table}",
                          {}, domain=REVIVE)
    row = _records(df)[0] if not df.empty else {}
    if row.get("last_run") is None:
        return MaintenanceRun(last_run_utc=None, minutes_ago=None, status="never_run")
    minutes = float(row["minutes_ago"])
    return MaintenanceRun(last_run_utc=row["last_run"], minutes_ago=minutes,
                          status="overdue" if minutes > MAINTENANCE_OVERDUE_MINUTES else "ok")


def get_system_status(client: AnalyticsClient) -> SystemStatus:
    variables = client.raw_query("SELECT name, value FROM rv_application_variable", {}, domain=REVIVE)
    values = dict(zip(variables["name"], variables["value"]))
    plugins = {name.removesuffix("_version"): str(version) for name, version in values.items()
               if name.endswith("_version") and name != "oa_version"}
    stats_run = _maintenance_run(client, "rv_log_maintenance_statistics")
    priority_run = _maintenance_run(client, "rv_log_maintenance_priority")

    warnings = []
    effect = {"Statistics": "new delivery isn't being summarised into the stats tables",
              "Priority": "campaign priorities (pacing toward booked goals) aren't being recalculated"}
    for label, run in (("Statistics", stats_run), ("Priority", priority_run)):
        if run.status == "never_run":
            warnings.append(f"{label} maintenance has never run, so {effect[label]}. "
                            f"Schedule Revive's maintenance job (hourly cron).")
        elif run.status == "overdue":
            warnings.append(f"{label} maintenance last ran {run.minutes_ago:.0f} minutes ago "
                            f"(expected hourly).")
    return SystemStatus(revive_version=values.get("oa_version"), plugins=dict(sorted(plugins.items())),
                        statistics_maintenance=stats_run, priority_maintenance=priority_run, warnings=warnings)
