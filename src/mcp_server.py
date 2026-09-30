"""
The MCP server behind the API: 19 tools total, but at most 16 ever reach the
LLM in one conversation - 11 core tools (shared, always loaded) + either
Revive's 5 domain tools or Exchange's 3, chosen by conversation mode.

The MCP protocol itself has no native concept of "modes" - all @_tool()
functions are always registered. The token savings come from FILTERING at
the orchestrator layer (see orchestrator.py's `mode` parameter), using the
TOOL_DOMAIN map (src/semantic/tool_domains.py) to know which tools belong
to which mode. This file just registers everything; orchestrator.py does
the actual scoping.

The API runs it in-process (src/api/main.py). Run standalone over stdio:
python -m src.mcp_server
"""
from __future__ import annotations

import functools
import logging

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from src.config import get_settings
from src.rag.vector_store import KnowledgeBaseStore
from src.semantic import core_tools as ct
from src.semantic import realtime_exchange as rt
from src.semantic import report_tools as rp
from src.semantic.analytics_client import AnalyticsClient
from src.semantic.core_models import (
    AnomalyReport, EntityListResult, FreshnessInfo, KpiResult,
    MetricChangeExplanation, MetricDefinition, MetricInfo, PeriodComparison,
    RankingResult, TrendSummary,
)
from src.semantic.realtime_exchange import RealtimeExchangeHealth
from src.semantic.report_tools import DomainReport

from src.semantic.cross_analysis import BannerZoneMapping, SupplyDemandCrossAnalysis, get_banner_zone_mapping as _get_banner_zone_mapping
from src.semantic.cross_analysis import get_supply_demand_cross_analysis as _get_supply_demand_cross
from src.semantic import revive_admin as ra
from src.semantic.revive_admin import AuditLogResult, CheckOverview, CheckResult, InspectResult
from src.semantic.access import Scope
from src.semantic.metric_registry import REVIVE


logging.basicConfig(level=get_settings().log_level)
logger = logging.getLogger(__name__)

mcp = MCPServer("ai-analytics-copilot")


def _tool():
    """mcp.tool(), except that EXPECTED errors - a bad argument (ValueError)
    or no access (PermissionError) - reach the LLM with their message, so it
    can correct itself or explain the refusal. The SDK otherwise replaces
    any non-ToolError exception with a generic "Error executing tool X";
    genuine crashes still get that treatment."""
    register = mcp.tool()

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except (ValueError, PermissionError) as exc:
                raise ToolError(str(exc)) from exc
        return register(wrapper)
    return decorator
_settings = get_settings()
_analytics = AnalyticsClient(_settings)
_kb = KnowledgeBaseStore(_settings)


def _client(ctx: Context, domain: str) -> AnalyticsClient:
    """The data client for this call. Revive data is limited to the caller's
    scope, read from MCP request metadata the orchestrator attaches (never
    from tool arguments); no scope means no Revive data. Exchange data
    isn't partitioned by manager, so it's unscoped."""
    if domain != REVIVE:
        return _analytics
    try:
        scope = Scope.from_meta(ctx.request_context.meta)
    except PermissionError as exc:
        # ToolError (not a crash): the refusal reaches the model as-is.
        raise ToolError(str(exc)) from exc
    return _analytics.scoped(scope.revive_agency_id)

# ---------------------------------------------------------------------
# Which mode each tool belongs to. None = core (always loaded).
# orchestrator.py filters mcp.list_tools() against this before building
# the provider's tool schema - this is where the actual token savings
# happen, not in the MCP server itself.
# ---------------------------------------------------------------------
from src.semantic.tool_domains import TOOL_DOMAIN


# ---------------------------------------------------------------------
# Core tools (11) - thin wrappers handing off to src.semantic.core_tools,
# whose logic is already verified in tests/unit/test_core_tools.py.
# ---------------------------------------------------------------------
@_tool()
def list_available_metrics(domain: str) -> list[MetricInfo]:
    """List every metric available in a domain ('revive' or 'exchange'),
    with its formula and description. Call this before calculate_kpi if
    you're not sure a metric exists or what domain it belongs to."""
    return ct.list_available_metrics(domain)


@_tool()
def get_metric_definition(domain: str, metric: str) -> MetricDefinition:
    """Get the exact formula and description for one metric. Use this to
    explain a number to the user rather than guessing at a formula -
    especially for metrics like fill_rate that mean different things in
    'revive' vs 'exchange'."""
    return ct.get_metric_definition(domain, metric)


@_tool()
def list_entities(domain: str, entity_type: str, search: str | None = None,
                  parent_type: str | None = None, parent_id: int | None = None,
                  limit: int = 50, *, ctx: Context) -> EntityListResult:
    """Resolve entity names to the IDs other tools need. entity_type is one
    of: revive -> zone, banner, campaign, client, affiliate (website/
    publisher), manager; exchange -> supply_partner, ad_unit,
    demand_partner, dsp_campaign.
    `search` matches part of the name, case-insensitive - prefer it over
    listing everything. Revive only: parent_type + parent_id list one
    parent's direct children (zone<-affiliate, banner<-campaign,
    campaign<-client, client<-manager, affiliate<-manager).
    If `truncated` is true, narrow the search."""
    return ct.list_entities(_client(ctx, domain), domain, entity_type, search, parent_type, parent_id, limit)


@_tool()
def get_data_freshness(domain: str, *, ctx: Context) -> FreshnessInfo:
    """Check how current the data is before reporting on it - avoids
    silently presenting stale numbers as if they were live. For 'revive'
    it also returns `system`: Revive version, plugins, and whether the
    hourly maintenance jobs (statistics, priority) are running - use it
    for 'is the ad server healthy / is maintenance running' questions."""
    return ct.get_data_freshness(_client(ctx, domain), domain)


@_tool()
def calculate_kpi(domain: str, metric: str, days: int = 30,
                   entity_type: str | None = None, entity_id: int | None = None, *, ctx: Context) -> KpiResult:
    """Get a single metric's total value over a period, optionally scoped
    to one entity. This is the general-purpose KPI lookup - use it for any
    single-number question."""
    return ct.calculate_kpi(_client(ctx, domain), domain, metric, days, entity_type, entity_id)


@_tool()
def compare_periods(domain: str, metric: str, days: int = 14,
                     entity_type: str | None = None, entity_id: int | None = None, *, ctx: Context) -> PeriodComparison:
    """Compare the last N days to the N days before that - two clean,
    non-overlapping windows. Use for 'how does this week compare to last
    week' style questions."""
    return ct.compare_periods(_client(ctx, domain), domain, metric, days, entity_type, entity_id)


@_tool()
def rank_entities(domain: str, metric: str, entity_type: str, days: int = 30,
                   limit: int = 10, ascending: bool = False,
                   min_volume_metric: str | None = None, *, ctx: Context) -> RankingResult:
    """Rank entities by a metric - top performers (ascending=False) or
    worst/underperformers (ascending=True). Pass min_volume_metric (e.g.
    'impressions') to also see the volume behind each rank, so a high rate
    on trivial volume isn't mistaken for a meaningful result."""
    return ct.rank_entities(_client(ctx, domain), domain, metric, entity_type, days, limit,
                             ascending, min_volume_metric)


@_tool()
def analyze_trend(domain: str, metric: str, days: int = 30,
                   entity_type: str | None = None, entity_id: int | None = None, *, ctx: Context) -> TrendSummary:
    """Determine whether a metric is trending up, down, or stable over
    time, comparing the first half to the second half of the window."""
    return ct.analyze_trend(_client(ctx, domain), domain, metric, days, entity_type, entity_id)


@_tool()
def detect_anomalies(domain: str, metric: str, days: int = 30,
                      entity_type: str | None = None, entity_id: int | None = None,
                      sensitivity: str = "normal", *, ctx: Context) -> AnomalyReport:
    """Find days where a metric deviated unusually from its recent
    baseline. sensitivity='normal' (recommended) only flags genuinely
    unusual days; 'high' also catches minor blips."""
    return ct.detect_anomalies(_client(ctx, domain), domain, metric, days, entity_type, entity_id, sensitivity)


@_tool()
def explain_metric_change(domain: str, metric: str, days: int = 14,
                           entity_type: str | None = None, entity_id: int | None = None,
                           top_n: int = 5, *, ctx: Context) -> MetricChangeExplanation:
    """Root-cause a metric change: compares the current period to the
    previous one, then breaks it down by the natural child dimension
    (e.g. campaigns within a client) to find which specific entities drove
    the change - ranked by absolute impact, not percentage, to avoid being
    misled by a huge swing on trivial volume. This is usually the right
    first tool for 'why did X change' questions."""
    return ct.explain_metric_change(_client(ctx, domain), domain, metric, days, entity_type, entity_id, top_n)


@_tool()
def search_knowledge_base(query: str, top_k: int = 3) -> dict:
    """Search internal policies and playbooks for context a data query
    alone can't answer - e.g. 'what should I check before escalating a
    timeout spike'. Combine with a data tool when a question needs both."""
    return ct.search_knowledge_base(_kb, query, top_k)


# ---------------------------------------------------------------------
# Domain tools (8) - only loaded in their matching mode
# ---------------------------------------------------------------------
@_tool()
def generate_revive_report(entity_type: str, entity_id: int, days: int = 30, *, ctx: Context) -> DomainReport:
    """[Revive mode] Full picture for a zone, banner, campaign, client,
    affiliate or manager in one call:
    requests/impressions/fill rate/CTR/CVR/revenue/margin/eCPM, plus
    fill-rate trend and anomalies. Use for broad 'how is this doing' questions."""
    return rp.generate_revive_report(_client(ctx, REVIVE), entity_type, entity_id, days)


@_tool()
def generate_exchange_report(entity_type: str, entity_id: int, days: int = 30) -> DomainReport:
    """[Exchange mode] Full picture for a supply_partner, ad_unit,
    demand_partner, or dsp_campaign in one call: bid funnel, win rate,
    timeout rate, eCPM, latency, plus win-rate trend and anomalies."""
    return rp.generate_exchange_report(_analytics, entity_type, entity_id, days)


@_tool()
def get_realtime_exchange_health(minutes: int = 15, ad_unit_id: int | None = None,
                                  demand_partner_id: int | None = None) -> RealtimeExchangeHealth:
    """[Exchange mode] Live operational snapshot (QPS, bid rate, timeout
    rate, latency) from the last few minutes of raw auction data. Use for
    'what's happening right now' questions; use analyze_trend/calculate_kpi
    for anything beyond a few hours."""
    return rt.get_realtime_exchange_health(_analytics, minutes, ad_unit_id, demand_partner_id)

@_tool()
def get_banner_zone_mapping(banner_id: int | None = None, zone_id: int | None = None,
                             days: int = 30, *, ctx: Context) -> BannerZoneMapping:
    """[Revive mode] Which zones a banner runs in, or which banners run in a zone.
    Provide banner_id OR zone_id to scope to one entity (use list_entities first
    to resolve a name to an ID). To answer a question about the FULL mapping
    across every banner/zone, call this ONCE with neither ID set - it returns
    the top pairs account-wide by impression volume - rather than calling it
    once per banner or zone."""
    return _get_banner_zone_mapping(_client(ctx, REVIVE), banner_id, zone_id, days)

@_tool()
def get_supply_demand_cross_analysis(metric: str = "win_rate", supply_partner_id: int | None = None,
                                      demand_partner_id: int | None = None,
                                      days: int = 30) -> SupplyDemandCrossAnalysis:
    """[Exchange mode] Cross-tab a metric by both supply and demand partner.
    Provide exactly one ID to hold that side fixed and see it vary across the other."""
    return _get_supply_demand_cross(_analytics, metric, supply_partner_id, demand_partner_id, days)

@_tool()
def inspect_revive_object(object_type: str, object_id: int, *, ctx: Context) -> InspectResult:
    """[Revive mode] Configuration of ONE object and what it's linked to -
    use for setup questions, not performance. object_type is one of:
    campaign (dates, priority, weight, booked vs delivered, pricing, caps,
    banners, linked zones), banner (size, click URL, caps, linked zones,
    targeting rules), zone (size, website, payout, linked banners and
    campaigns, last-7-day requests), affiliate (website: zones, users with
    access), client (campaigns, users with access), manager (advertisers,
    websites, users), user (accounts, last login). Use list_entities first
    to resolve a name to an ID."""
    return ra.inspect_revive_object(_client(ctx, REVIVE), object_type, object_id)


@_tool()
def run_revive_check(check_name: str, days: int | None = None, hours: int | None = None,
                     threshold_pct: int | None = None, min_requests: int | None = None, *, ctx: Context) -> CheckResult | CheckOverview:
    """[Revive mode] Find setup problems across the whole ad server. check_name:
    'all' (count of problems per check - start here for 'what's wrong?'),
    campaigns_expiring (days=7), campaigns_behind_pace (threshold_pct=90),
    active_no_delivery (hours=24), campaigns_not_running, unlinked_zones,
    size_mismatch, zero_fill_zones (days=7, min_requests=1000),
    inactive_users (days=90). Only pass the parameters a check lists;
    leave them out to use its defaults. Each result states its rule."""
    return ra.run_revive_check(_client(ctx, REVIVE), check_name, days=days, hours=hours,
                               threshold_pct=threshold_pct, min_requests=min_requests)


@_tool()
def get_revive_audit_log(object_type: str | None = None, object_id: int | None = None,
                         username: str | None = None, action: str | None = None,
                         days: int = 7, *, ctx: Context) -> AuditLogResult:
    """[Revive mode] Who changed what, and when - newest first, each change
    shown as field: was -> now. Filter by object (object_type: campaign,
    banner, zone, client, affiliate, manager, user + object_id; a banner or
    zone also includes its link and targeting changes), by username, and by
    action ('created', 'changed', 'deleted'). When explaining why a metric
    moved, check this for the same entity around the date of the change."""
    return ra.get_revive_audit_log(_client(ctx, REVIVE), object_type, object_id, username, action, days)


if __name__ == "__main__":
    mcp.run()
