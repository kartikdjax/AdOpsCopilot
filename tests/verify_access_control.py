"""Verifies Phase 5 access control against the live revive608 data:
a manager-scoped client sees only its own manager's data in every Revive
tool, the MCP server refuses Revive calls that carry no scope, and the API
keeps pending users out of Revive.

Manager 2 owns: advertiser 2001 (campaigns 3, 4; banners 5-8), website
4001 (zones 3001, 3004, 3007), users 100, 103, 106.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, ".")
# The API test below must not touch the real Copilot user database.
os.environ["COPILOT_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "copilot_test.db")

from mcp import Client

from src.config import get_settings
from src.semantic import core_tools as ct
from src.semantic import revive_admin as ra
from src.semantic.access import ADMIN, Scope
from src.semantic.analytics_client import AnalyticsClient
from src.semantic.cross_analysis import get_banner_zone_mapping

MANAGER_2_OWNS = {
    "client": {2001}, "campaign": {3, 4}, "banner": {5, 6, 7, 8},
    "affiliate": {4001}, "zone": {3001, 3004, 3007}, "manager": {2},
}


def _ids(result) -> set[int]:
    return {e.entity_id for e in result.entities}


def main() -> None:
    admin = AnalyticsClient(get_settings())
    m1, m2 = admin.scoped(1), admin.scoped(2)

    print("=" * 70)
    print("TEST 1: a manager lists only its own objects")
    print("=" * 70)
    for entity_type, owned in MANAGER_2_OWNS.items():
        seen = _ids(ct.list_entities(m2, "revive", entity_type))
        print(f"  {entity_type:9s} manager 2 sees {sorted(seen)}")
        assert seen == owned, f"FAILED: {entity_type} expected {owned}, got {seen}"
    assert _ids(ct.list_entities(admin, "revive", "zone")) > MANAGER_2_OWNS["zone"], "admin should see everything"
    print("PASS\n")

    print("=" * 70)
    print("TEST 2: stats, rankings and drill-downs stay inside the manager")
    print("=" * 70)
    total = ct.calculate_kpi(admin, "revive", "revenue").value
    per_manager = [ct.calculate_kpi(c, "revive", "revenue").value for c in (m1, m2)]
    print(f"  revenue: admin {total:,.2f} = manager 1 {per_manager[0]:,.2f} + manager 2 {per_manager[1]:,.2f}")
    assert abs(total - sum(per_manager)) < 0.01, "FAILED: manager totals don't partition the platform total"
    ranked = {r.entity_id for r in ct.rank_entities(m2, "revive", "impressions", "zone").results}
    assert ranked <= MANAGER_2_OWNS["zone"], f"FAILED: ranking leaked zones {ranked - MANAGER_2_OWNS['zone']}"
    explained = ct.explain_metric_change(m2, "revive", "revenue", days=14)
    leaked = {c.entity_id for c in explained.top_contributors} - MANAGER_2_OWNS["campaign"]
    assert not leaked, f"FAILED: drill-down leaked campaigns {leaked}"
    other = ct.calculate_kpi(m2, "revive", "impressions", entity_type="zone", entity_id=3000).value
    assert not other, "FAILED: manager 2 got numbers for manager 1's zone"
    pairs = get_banner_zone_mapping(m2).pairs
    assert pairs and {p.zone_id for p in pairs} <= MANAGER_2_OWNS["zone"]
    print(f"  rankings, drill-down, another manager's zone ({other}) and banner-zone pairs all scoped")
    print("PASS\n")

    print("=" * 70)
    print("TEST 3: health checks, inspect and audit are scoped too")
    print("=" * 70)
    counts = ra.run_revive_check(m2, "all").counts
    print(f"  manager 2 checks: {counts}")
    assert [r["campaign_id"] for r in ra.run_revive_check(m2, "campaigns_behind_pace").rows] == [3]
    assert ra.run_revive_check(m2, "unlinked_zones").rows == [], "zone 3006 belongs to manager 1"
    assert {r["user_id"] for r in ra.run_revive_check(m2, "inactive_users").rows} == {103, 106}
    assert ra.run_revive_check(m1, "active_no_delivery").rows[0]["campaign_id"] == 6

    try:
        ra.inspect_revive_object(m2, "campaign", 1)
        raise AssertionError("FAILED: manager 2 inspected manager 1's campaign")
    except ValueError as e:
        print(f"  Correctly hidden: {e}")
    access = ra.inspect_revive_object(m2, "client", 2001).links["users_with_access"]
    assert access and all(u["via"] != "ADMIN" for u in access), "platform admins shown to a manager"

    audit_users = {e.user for e in ra.get_revive_audit_log(m2, days=30).events}
    print(f"  manager 2 audit authors (30 days): {audit_users}")
    assert audit_users == {"mgr2_ops"}, f"FAILED: audit leaked {audit_users}"
    print("PASS\n")

    print("=" * 70)
    print("TEST 4: scope is validated and can't be forged into something else")
    print("=" * 70)
    for bad in [lambda: Scope("manager"), lambda: Scope("superuser"), lambda: Scope("admin", 2),
                lambda: Scope.from_meta(None), lambda: Scope.from_meta({"copilot_scope": {"role": "root"}})]:
        try:
            bad()
            raise AssertionError("FAILED: invalid scope accepted")
        except PermissionError as e:
            print(f"  Correctly rejected: {e}")
    print("PASS\n")

    print("=" * 70)
    print("TEST 5: the MCP server enforces scope from request metadata only")
    print("=" * 70)
    asyncio.run(_mcp_checks())
    print("PASS\n")

    print("=" * 70)
    print("TEST 6: the API keeps pending users out of Revive")
    print("=" * 70)
    _api_checks()
    print("PASS\n")

    print("=" * 70)
    print("ALL ACCESS CONTROL CHECKS PASSED")
    print("=" * 70)


async def _mcp_checks() -> None:
    from src.mcp_server_v2 import mcp

    async with Client(mcp) as client:
        tools = (await client.list_tools()).tools
        leaked = [t.name for t in tools if {"ctx", "scope", "agency_id"} & set(t.input_schema.get("properties", {}))]
        assert not leaked, f"FAILED: scope-related parameters exposed to the LLM in {leaked}"

        args = {"domain": "revive", "metric": "revenue"}
        unscoped = await client.call_tool("calculate_kpi", args)
        assert unscoped.is_error and "no user scope" in str(unscoped.content), "FAILED: unscoped Revive call ran"
        print("  no metadata          -> refused")

        manager = await client.call_tool("calculate_kpi", args, meta=Scope("manager", 2).to_meta())
        admin = await client.call_tool("calculate_kpi", args, meta=ADMIN.to_meta())
        m_value, a_value = manager.structured_content["value"], admin.structured_content["value"]
        assert m_value < a_value, "FAILED: manager scope not applied through MCP"
        print(f"  manager 2 metadata   -> {m_value:,.2f} (admin: {a_value:,.2f})")

        forged = await client.call_tool("calculate_kpi", {**args, "agency_id": None},
                                        meta=Scope("manager", 2).to_meta())
        assert forged.is_error or forged.structured_content["value"] == m_value, "FAILED: argument widened scope"
        print("  agency_id argument   -> can't widen scope")

        metrics = await client.call_tool("list_available_metrics", {"domain": "revive"})
        assert not metrics.is_error, "metric definitions hold no data and need no scope"


def _api_checks() -> None:
    from fastapi.testclient import TestClient

    from src.api.auth import user_scope
    from src.api.db import get_db
    from src.api.main import app

    web = TestClient(app)  # no lifespan: the checks below must reject before any LLM or MCP call
    signup = web.post("/auth/signup", json={"email": "new@example.com", "password": "correct-horse",
                                            "display_name": "New User"})
    assert signup.json()["user"]["role"] == "pending"
    denied = web.post("/chat", json={"session_id": "s1", "message": "revenue?", "mode": "revive"})
    assert denied.status_code == 403, f"FAILED: pending user reached Revive ({denied.status_code})"
    print(f"  pending user, Revive -> {denied.status_code}: {denied.json()['detail'][:60]}...")

    db = get_db()
    db.execute("UPDATE users SET role = 'manager', agency_id = 2 WHERE email = 'new@example.com'")
    db.commit()
    db.close()
    me = web.get("/auth/me").json()["user"]
    assert user_scope(me) == Scope("manager", 2), "role change should apply on the next request"
    assert user_scope({"role": "manager", "agency_id": None}) is None
    assert user_scope({"role": "admin", "agency_id": None}) == ADMIN
    print(f"  after promotion      -> scope {user_scope(me)}")


if __name__ == "__main__":
    main()
