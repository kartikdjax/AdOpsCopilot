"""
Golden question set for Revive mode - the admin question map from the
Revive Admin Copilot plan, run end to end through the real LLM, the MCP
server (mcp_server) and the live revive608 data.

This is an INTEGRATION eval, not a pytest test: it checks that the model
picks a suitable tool and that the answer names what the planted data
says it should (admin_fixtures.PLANTED and the zone scenarios). A failure
means "look at this question", not necessarily a code bug - LLM tool
choice varies run to run.

Requires: LLM credentials in .env, revive608 loaded
(python -m src.revive_data.load_revive_data --days 30) and the knowledge
base seeded (python -m src.rag.load_seed_documents).

Run: python -m evals.revive_scenarios                 # everything
     python -m evals.revive_scenarios --only C D      # some areas
     python -m evals.revive_scenarios --delay 5       # gentler on rate limits
"""
from __future__ import annotations

import argparse
import asyncio

from mcp import Client

from src.config import get_settings
from src.mcp_server import mcp
from src.orchestrator import answer_question
from src.provider_factory import build_provider
from src.semantic.access import ADMIN, Scope

MANAGER_2 = Scope("manager", 2)
# Everything manager 1 owns - must never appear in a manager 2 answer.
MANAGER_1_NAMES = ["Zone_1", "Zone_3", "Zone_4", "Zone_6", "Zone_7", "Website_1", "Website_3",
                   "Advertiser_1", "Advertiser_3", "default_mgr_analyst", "web1_owner"]

# id, question, tools (any of), also (any of, optional), keywords (any of), scope, forbidden
SCENARIOS = [
    # A. Delivery and performance
    ("A1", "How did the platform do over the last 7 days compared with the 7 days before?",
     ["compare_periods"], None, ["%", "impression", "revenue", "request"], ADMIN, []),
    ("A2", "Which zones have the lowest fill rate this month?",
     ["rank_entities"], None, ["Zone_8", "Zone_2", "Zone_6"], ADMIN, []),
    ("A3", "Why did Zone_3_fill_rate_decline's fill rate drop?",
     ["explain_metric_change", "analyze_trend", "detect_anomalies", "generate_revive_report"],
     ["get_revive_audit_log"], ["capping", "cap"], ADMIN, []),
    ("A4", "Were there any unusual days for impressions in the last 30 days?",
     ["detect_anomalies"], None, ["anomal", "unusual", "spike", "drop"], ADMIN, []),
    ("A5", "Show the top 5 banners by CTR, ignoring low-volume ones.",
     ["rank_entities"], None, ["Banner", "CTR"], ADMIN, []),
    ("A7", "How is each website performing?",
     ["rank_entities", "generate_revive_report", "calculate_kpi"], None, ["Website_1", "Website_2"], ADMIN, []),
    ("A8", "Which manager delivers the most impressions?",
     ["rank_entities"], None, ["Manager_2", "Default manager"], ADMIN, []),
    # B. Revenue and margin
    ("B1", "What were revenue, cost and margin over the last 30 days?",
     ["calculate_kpi", "generate_revive_report"], None, ["margin"], ADMIN, []),
    ("B2", "What's the eCPM by website?",
     ["rank_entities", "calculate_kpi"], None, ["Website"], ADMIN, []),
    ("B3", "Which advertiser earns us the most revenue?",
     ["rank_entities"], None, ["Advertiser_"], ADMIN, []),
    ("B4", "Which zones cost more than they earn?",
     ["rank_entities", "calculate_kpi"], None, ["Zone_6"], ADMIN, []),
    # C. Campaigns and pacing
    ("C1", "Which campaigns expire in the next 7 days?",
     ["run_revive_check"], None, ["Advertiser_3_Campaign_1"], ADMIN, []),
    ("C2", "Which campaigns are behind on their booked impressions?",
     ["run_revive_check"], None, ["Advertiser_2_Campaign_1"], ADMIN, []),
    ("C3", "Which campaigns are running but delivered nothing in the last day?",
     ["run_revive_check"], None, ["Advertiser_3_Campaign_2"], ADMIN, []),
    ("C4", "What's the priority, weight and capping on Advertiser_2_Campaign_1, and which zones is it linked to?",
     ["inspect_revive_object"], None, ["weight"], ADMIN, []),
    ("C5", "Which campaigns are paused or waiting to start?",
     ["run_revive_check"], None, ["Advertiser_2_Campaign_2", "Advertiser_3_Campaign_3"], ADMIN, []),
    # D. Inventory and setup problems
    ("D1", "Which banners run in Zone_2_under_monetized?",
     ["get_banner_zone_mapping", "inspect_revive_object"], None, ["Banner"], ADMIN, []),
    ("D2", "Which zones have no banners or campaigns linked?",
     ["run_revive_check"], None, ["Zone_7"], ADMIN, []),
    ("D3", "Are any banners linked to zones of the wrong size?",
     ["run_revive_check"], None, ["728", "Leaderboard"], ADMIN, []),
    ("D4", "Which zones get requests but never fill?",
     ["run_revive_check", "rank_entities"], None, ["Zone_8"], ADMIN, []),
    ("D5", "What targeting rules are on the banner Advertiser_1_Campaign_1_Leaderboard?",
     ["inspect_revive_object"], None, ["IN", "India", "country"], ADMIN, []),
    ("D6", "What's wrong with the ad server right now?",
     ["run_revive_check"], None, ["Zone_7", "behind", "expir", "unlinked"], ADMIN, []),
    # E. Accounts, users and access
    ("E1", "List the managers with their advertisers and websites.",
     ["list_entities", "inspect_revive_object"], None, ["Manager_2"], ADMIN, []),
    ("E2", "Who has access to Advertiser_1?",
     ["inspect_revive_object"], None, ["adv1_owner", "agency_buyer"], ADMIN, []),
    ("E3", "Which users haven't logged in for 90 days?",
     ["run_revive_check"], None, ["adv2_owner", "web2_owner", "adv3_owner"], ADMIN, []),
    # F. Change history
    ("F1", "What changed in the ad server in the last 2 days?",
     ["get_revive_audit_log"], None, ["Advertiser_3_Campaign_3", "weight", "created"], ADMIN, []),
    ("F2", "Who paused Advertiser_2_Campaign_2, and when?",
     ["get_revive_audit_log"], None, ["mgr2_ops"], ADMIN, []),
    ("F3", "Did anyone change Zone_3_fill_rate_decline before its fill rate dropped?",
     ["get_revive_audit_log"], None, ["capping", "default_mgr_analyst"], ADMIN, []),
    # G. System health
    ("G1", "Is Revive's maintenance running, and how fresh is the data?",
     ["get_data_freshness"], None, ["never", "maintenance"], ADMIN, []),
    ("G2", "Which Revive version and plugins are installed?",
     ["get_data_freshness"], None, ["6.0.8"], ADMIN, []),
    # H. Policy
    ("H1", "What should I check before changing a campaign's priority?",
     ["search_knowledge_base"], None, ["booked", "pacing", "maintenance", "zone"], ADMIN, []),
    # Manager scope: answers must stay inside manager 2's accounts.
    ("M1", "Which zones have the lowest fill rate this month?",
     ["rank_entities"], None, ["Zone_8", "Zone_2", "Zone_5"], MANAGER_2, MANAGER_1_NAMES),
    ("M2", "What changed in the last 30 days, and who changed it?",
     ["get_revive_audit_log"], None, ["mgr2_ops"], MANAGER_2, MANAGER_1_NAMES),
    ("M3", "Which websites and advertisers do I manage, and how much revenue did they make?",
     ["list_entities", "rank_entities", "calculate_kpi", "inspect_revive_object"], None,
     ["Website_2", "Advertiser_2"], MANAGER_2, MANAGER_1_NAMES),
]


def _norm(text: str) -> str:
    """Lowercase, and treat '_' and any Unicode space (models like U+202F) as a
    plain space - models often write Zone_7 as 'Zone 7' or 'Zone\u202f7'."""
    return " ".join(text.lower().replace("_", " ").split())


async def run_scenario(scenario: tuple, mcp_client: Client, provider) -> tuple[bool, list[str]]:
    sid, question, tools, also, keywords, scope, forbidden = scenario
    result = await answer_question(question, mcp_client, provider, mode="revive", scope=scope)
    used = set(result["tool_calls_made"])
    answer = _norm(result["answer"])

    failures = []
    if not used & set(tools):
        failures.append(f"expected one of {tools}, used {sorted(used) or 'no tools'}")
    if also and not used & set(also):
        failures.append(f"expected also one of {also}")
    if not any(_norm(k) in answer for k in keywords):
        failures.append(f"none of {keywords} in the answer")
    leaked = [f for f in forbidden if _norm(f) in answer]
    if leaked:
        failures.append(f"LEAKED other manager's data: {leaked}")

    who = "admin" if scope.role == "admin" else f"manager {scope.agency_id}"
    print(f"[{'PASS' if not failures else 'FAIL'}] {sid} ({who}) {question}")
    print(f"       tools: {sorted(used)}")
    for f in failures:
        print(f"       - {f}")
    if failures:
        print(f"       answer: {result['answer'][:300]!r}")
    return not failures, failures


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="scenario ids or area letters, e.g. C D M1")
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between questions (rate limits)")
    args = parser.parse_args()

    selected = [s for s in SCENARIOS
                if not args.only or any(s[0] == o or s[0].startswith(o) for o in args.only)]
    provider = build_provider(get_settings())

    results = []
    async with Client(mcp) as mcp_client:
        for i, scenario in enumerate(selected):
            if i:
                await asyncio.sleep(args.delay)
            try:
                passed, _ = await run_scenario(scenario, mcp_client, provider)
            except Exception as exc:  # noqa: BLE001 - one broken question shouldn't stop the eval
                print(f"[ERROR] {scenario[0]} {type(exc).__name__}: {exc}")
                passed = False
            results.append((scenario[0], passed))

    passed = [sid for sid, ok in results if ok]
    failed = [sid for sid, ok in results if not ok]
    print("=" * 70)
    print(f"{len(passed)}/{len(results)} scenarios passed" + (f"; failed: {' '.join(failed)}" if failed else ""))


if __name__ == "__main__":
    asyncio.run(main())
