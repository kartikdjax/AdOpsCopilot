"""A manager-scoped client sees only its own manager's data in every Revive
tool, the MCP server refuses Revive calls without a scope, and the API keeps
pending users out of Revive.

Manager 2 owns: advertiser 2001 (campaigns 3, 4; banners 5-8), website
4001 (zones 3001, 3004, 3007), users 100, 103, 106.
"""
from __future__ import annotations

import pytest
from mcp import Client

from src.semantic import core_tools as ct
from src.semantic import revive_admin as ra
from src.semantic.access import ADMIN, Scope
from src.semantic.cross_analysis import get_banner_zone_mapping

MANAGER_2_OWNS = {
    "client": {2001}, "campaign": {3, 4}, "banner": {5, 6, 7, 8},
    "affiliate": {4001}, "zone": {3001, 3004, 3007}, "manager": {2},
}


def _ids(result) -> set[int]:
    return {e.entity_id for e in result.entities}


@pytest.fixture(scope="module")
def m1(admin):
    return admin.scoped(1)


@pytest.fixture(scope="module")
def m2(admin):
    return admin.scoped(2)


@pytest.mark.parametrize("entity_type", sorted(MANAGER_2_OWNS))
def test_manager_lists_only_own_objects(m2, entity_type):
    assert _ids(ct.list_entities(m2, "revive", entity_type)) == MANAGER_2_OWNS[entity_type]


def test_admin_sees_everything(admin):
    assert _ids(ct.list_entities(admin, "revive", "zone")) > MANAGER_2_OWNS["zone"]


def test_manager_totals_partition_platform_total(admin, m1, m2):
    total = ct.calculate_kpi(admin, "revive", "revenue").value
    per_manager = sum(ct.calculate_kpi(c, "revive", "revenue").value for c in (m1, m2))
    assert total == pytest.approx(per_manager, abs=0.01)


def test_rankings_drilldowns_and_mappings_stay_scoped(m2):
    ranked = {r.entity_id for r in ct.rank_entities(m2, "revive", "impressions", "zone").results}
    assert ranked <= MANAGER_2_OWNS["zone"]
    explained = ct.explain_metric_change(m2, "revive", "revenue", days=14)
    assert {c.entity_id for c in explained.top_contributors} <= MANAGER_2_OWNS["campaign"]
    # Zone 3000 belongs to manager 1.
    assert not ct.calculate_kpi(m2, "revive", "impressions", entity_type="zone", entity_id=3000).value
    pairs = get_banner_zone_mapping(m2).pairs
    assert pairs and {p.zone_id for p in pairs} <= MANAGER_2_OWNS["zone"]


def test_health_checks_are_scoped(m1, m2):
    assert [r["campaign_id"] for r in ra.run_revive_check(m2, "campaigns_behind_pace").rows] == [3]
    assert ra.run_revive_check(m2, "unlinked_zones").rows == []  # zone 3006 is manager 1's
    assert {r["user_id"] for r in ra.run_revive_check(m2, "inactive_users").rows} == {103, 106}
    assert ra.run_revive_check(m1, "active_no_delivery").rows[0]["campaign_id"] == 6


def test_inspect_is_scoped(m2):
    with pytest.raises(ValueError):
        ra.inspect_revive_object(m2, "campaign", 1)
    access = ra.inspect_revive_object(m2, "client", 2001).links["users_with_access"]
    assert access and all(u["via"] != "ADMIN" for u in access)


def test_audit_log_is_scoped(m2):
    assert {e.user for e in ra.get_revive_audit_log(m2, days=30).events} == {"mgr2_ops"}


async def test_mcp_server_takes_scope_from_metadata_only(admin):
    from src.mcp_server import mcp

    async with Client(mcp) as client:
        tools = (await client.list_tools()).tools
        assert not [t.name for t in tools
                    if {"ctx", "scope", "agency_id"} & set(t.input_schema.get("properties", {}))]

        args = {"domain": "revive", "metric": "revenue"}
        unscoped = await client.call_tool("calculate_kpi", args)
        assert unscoped.is_error and "no user scope" in str(unscoped.content)

        manager = await client.call_tool("calculate_kpi", args, meta=Scope("manager", 2).to_meta())
        full = await client.call_tool("calculate_kpi", args, meta=ADMIN.to_meta())
        m_value = manager.structured_content["value"]
        assert m_value < full.structured_content["value"]

        forged = await client.call_tool("calculate_kpi", {**args, "agency_id": None},
                                        meta=Scope("manager", 2).to_meta())
        assert forged.is_error or forged.structured_content["value"] == m_value

        metrics = await client.call_tool("list_available_metrics", {"domain": "revive"})
        assert not metrics.is_error  # definitions hold no data and need no scope


def test_api_keeps_pending_users_out_of_revive(admin):
    from fastapi.testclient import TestClient

    from src.api.auth import user_scope
    from src.api.db import get_db
    from src.api.main import app

    web = TestClient(app)  # no lifespan: these requests must be refused before any LLM or MCP call
    signup = web.post("/auth/signup", json={"email": "new@example.com", "password": "correct-horse",
                                            "display_name": "New User"})
    assert signup.json()["user"]["role"] == "pending"
    denied = web.post("/chat", json={"session_id": "s1", "message": "revenue?", "mode": "revive"})
    assert denied.status_code == 403

    db = get_db()
    db.execute("UPDATE users SET role = 'manager', agency_id = 2 WHERE email = 'new@example.com'")
    db.commit()
    db.close()
    # A role change applies on the next request.
    assert user_scope(web.get("/auth/me").json()["user"]) == Scope("manager", 2)
