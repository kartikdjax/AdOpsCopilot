"""
Synthetic data generator matching the REAL local Revive Adserver MySQL
schema (database `revive608`, imported from a real Revive install dump -
see rv_clients/rv_campaigns/rv_banners/rv_zones/rv_data_summary_ad_hourly
DESCRIBE output this was built against).

Only NOT-NULL columns that have no usable MySQL default are generated
here; everything else is left out of the DataFrame so MySQL applies its
own column default. Free-text columns with no default (htmltemplate,
url, category, etc.) get an empty string - no current tool reads them,
they exist only to satisfy the real schema's NOT NULL constraint.

Zones get a deliberate SCENARIO (like Phase 1's campaign scenarios) so
Phase 7's SSP tools (fill rate analysis, monetization opportunities) have
real, labeled patterns to find - not just noise.

Account hierarchy: every client (advertiser) and affiliate (website) is
owned by a manager (rv_agency). Manager 1 is the install's own "Default
manager" and is never generated or overwritten - only managers from
SYNTHETIC_MANAGER_START upward are. Money follows Revive's own model:
campaigns earn via revenue/revenue_type (CPM or CPC), zones pay the
website via cost/cost_type (revenue share or fixed CPM), and each stats
row carries the resulting total_revenue/total_cost.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from src.revive_data.admin_fixtures import apply_admin_fixtures

# Admin-only tables produced by admin_fixtures, loaded as-is.
ADMIN_TABLES = ["rv_ad_zone_assoc", "rv_placement_zone_assoc", "rv_acls",
                "rv_accounts", "rv_users", "rv_account_user_assoc", "rv_audit"]

ZONE_SCENARIOS = ["healthy", "under_monetized", "fill_rate_decline", "seasonal_growth"]

DEFAULT_MANAGER_ID = 1          # the real install's "Default manager" - never regenerated
SYNTHETIC_MANAGER_START = 2

# Real Revive finance constants (MAX_FINANCE_*): campaign revenue_type and zone cost_type.
FINANCE_CPM, FINANCE_CPC, FINANCE_RS = 1, 2, 5


@dataclass(frozen=True, slots=True)
class Manager:
    agencyid: int
    name: str
    email: str
    updated: datetime
    account_id: int | None = None


@dataclass(frozen=True, slots=True)
class Affiliate:
    affiliateid: int
    agencyid: int
    name: str
    mnemonic: str
    email: str
    website: str
    updated: datetime
    account_id: int | None = None


@dataclass(frozen=True, slots=True)
class Client:
    clientid: int
    agencyid: int
    clientname: str
    contact: str
    email: str
    updated: datetime
    reportlastdate: date
    account_id: int | None = None


@dataclass(frozen=True, slots=True)
class Campaign:
    campaignid: int
    clientid: int
    campaignname: str
    activate_time: datetime
    expire_time: datetime
    views: int
    clicks: int
    status: int
    revenue: float
    revenue_type: int
    updated: datetime


@dataclass(frozen=True, slots=True)
class Banner:
    bannerid: int
    campaignid: int
    description: str
    bannertype: int
    width: int
    height: int
    htmltemplate: str
    htmlcache: str
    url: str
    bannertext: str
    compiledlimitation: str
    append: str
    prepend: str
    updated: datetime
    acls_updated: datetime
    base_ctr: float  # not a real Revive column - kept here to drive generation only


@dataclass(frozen=True, slots=True)
class Zone:
    zoneid: int
    affiliateid: int
    zonename: str
    width: int
    height: int
    cost: float
    cost_type: int
    category: str
    ad_selection: str
    chain: str
    prepend: str
    append: str
    what: str
    updated: datetime
    scenario: str            # not a real Revive column - drives generation only
    base_fill_rate: float
    base_hourly_requests: int
    capping: int = 0         # real Revive column: impressions per visitor, 0 = no cap


_BANNER_TYPES = [0, 1, 2]  # real Revive bannertype tinyint - kept simple/generic


def _manager_ids(managers: list[Manager]) -> list[int]:
    return [DEFAULT_MANAGER_ID] + [m.agencyid for m in managers]


def generate_managers(n: int = 1) -> list[Manager]:
    """Extra managers beside the install's Default manager, so per-manager
    questions have more than one manager to compare."""
    now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    return [
        Manager(agencyid=SYNTHETIC_MANAGER_START + i, name=f"Manager_{SYNTHETIC_MANAGER_START + i}",
                email=f"manager{SYNTHETIC_MANAGER_START + i}@example.com", updated=now)
        for i in range(n)
    ]


def generate_affiliates(managers: list[Manager], n: int = 3) -> list[Affiliate]:
    """Websites (Revive's rv_affiliates). IDs 4000+ match the affiliateid
    that generate_zones assigns, so every zone has a real owning website."""
    now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    manager_ids = _manager_ids(managers)
    return [
        Affiliate(affiliateid=4000 + i, agencyid=manager_ids[i % len(manager_ids)],
                  name=f"Website_{i+1}", mnemonic=f"WS{i+1}", email=f"website{i+1}@example.com",
                  website=f"https://website{i+1}.example.com", updated=now)
        for i in range(n)
    ]


def generate_clients(managers: list[Manager], n: int = 3, seed: int = 7) -> list[Client]:
    now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    manager_ids = _manager_ids(managers)
    return [
        Client(clientid=2000 + i, agencyid=manager_ids[i % len(manager_ids)],
               clientname=f"Advertiser_{i+1}",
               contact=f"Contact_{i+1}", email=f"advertiser{i+1}@example.com",
               updated=now, reportlastdate=now.date())
        for i in range(n)
    ]


def generate_campaigns(clients: list[Client], per_client: int = 2, total_days: int = 14,
                        seed: int = 7) -> list[Campaign]:
    rng = np.random.default_rng(seed)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    campaigns, cid = [], 1
    for client in clients:
        for i in range(per_client):
            # Every other campaign is CPC so revenue isn't a pure function of impressions.
            is_cpc = cid % 2 == 0
            campaigns.append(Campaign(
                campaignid=cid, clientid=client.clientid,
                campaignname=f"{client.clientname}_Campaign_{i+1}",
                activate_time=now - timedelta(days=total_days),
                expire_time=now + timedelta(days=30),
                views=int(rng.integers(500_000, 2_000_000)),
                clicks=int(rng.integers(10_000, 50_000)),
                status=0,
                revenue=round(float(rng.uniform(0.10, 0.25) if is_cpc else rng.uniform(1.50, 4.00)), 4),
                revenue_type=FINANCE_CPC if is_cpc else FINANCE_CPM,
                updated=now,
            ))
            cid += 1
    return campaigns


def generate_banners(campaigns: list[Campaign], per_campaign: int = 2, seed: int = 7) -> list[Banner]:
    rng = np.random.default_rng(seed)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    banners, bid = [], 1
    for campaign in campaigns:
        for i in range(per_campaign):
            banners.append(Banner(
                bannerid=bid, campaignid=campaign.campaignid,
                description=f"{campaign.campaignname}_Banner_{i+1}",
                bannertype=_BANNER_TYPES[bid % len(_BANNER_TYPES)],
                width=300, height=250,
                htmltemplate="", htmlcache="", url="", bannertext="",
                compiledlimitation="", append="", prepend="",
                updated=now, acls_updated=now,
                base_ctr=float(rng.uniform(0.005, 0.025)),
            ))
            bid += 1
    return banners


def generate_zones(n: int = 6, seed: int = 7) -> list[Zone]:
    rng = np.random.default_rng(seed)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    zones = []
    for i in range(n):
        scenario = ZONE_SCENARIOS[i % len(ZONE_SCENARIOS)]
        # base_fill_rate varies deliberately by scenario so the story is
        # visible: healthy zones fill well, under-monetized ones don't.
        base_fill_rate = {
            "healthy": rng.uniform(0.65, 0.85),
            "under_monetized": rng.uniform(0.15, 0.35),
            "fill_rate_decline": rng.uniform(0.60, 0.75),  # starts healthy, declines over time
            "seasonal_growth": rng.uniform(0.50, 0.65),
        }[scenario]
        # Most zones pay the website a revenue share. The last zone pays a
        # fixed CPM above what its campaigns earn - a labeled negative-margin
        # zone for "which zones cost more than they earn" questions.
        negative_margin = i == n - 1
        zones.append(Zone(
            zoneid=3000 + i, affiliateid=4000 + (i % 3),
            zonename=f"Zone_{i+1}_{scenario}",
            width=300, height=250,
            cost=3.50 if negative_margin else round(float(rng.uniform(40, 70)), 4),
            cost_type=FINANCE_CPM if negative_margin else FINANCE_RS,
            category="", ad_selection="", chain="", prepend="", append="", what="",
            updated=now,
            scenario=scenario, base_fill_rate=float(base_fill_rate),
            base_hourly_requests=int(rng.integers(500, 3000)),
        ))
    return zones


def _hourly_fill_rate(zone: Zone, hour_index: int, total_hours: int) -> tuple[float, int]:
    """Returns (fill_rate, requests) for one zone-hour, shaped by scenario."""
    fill_rate = zone.base_fill_rate
    requests = zone.base_hourly_requests
    midpoint = total_hours // 2

    if zone.scenario == "fill_rate_decline":
        if hour_index >= midpoint:
            # Linear decline across the back half - a real, gradual monetization problem.
            progress = (hour_index - midpoint) / max(1, total_hours - midpoint)
            fill_rate = zone.base_fill_rate * (1 - 0.5 * progress)
    elif zone.scenario == "seasonal_growth":
        growth = 1.0 + (hour_index / total_hours) * 0.4
        requests = int(requests * growth)

    # Simple day/night traffic curve - requests dip overnight, everywhere.
    hour_of_day = hour_index % 24
    traffic_multiplier = 0.4 + 0.6 * np.sin(np.pi * (hour_of_day - 4) / 20) ** 2 if 4 <= hour_of_day <= 24 else 0.4
    requests = max(1, int(requests * traffic_multiplier))

    return fill_rate, requests


def _row_revenue(campaign: Campaign, impressions: int, clicks: int) -> float:
    if campaign.revenue_type == FINANCE_CPC:
        return clicks * campaign.revenue
    return impressions * campaign.revenue / 1000


def _row_cost(zone: Zone, revenue: float, impressions: int) -> float:
    if zone.cost_type == FINANCE_CPM:
        return impressions * zone.cost / 1000
    return revenue * zone.cost / 100


def generate_hourly_stats(banners: list[Banner], campaigns: list[Campaign], zones: list[Zone],
                           clients: list[Client], affiliates: list[Affiliate],
                           total_days: int, seed: int = 7) -> pd.DataFrame:
    total_hours = total_days * 24
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    start = now - timedelta(hours=total_hours)

    campaign_by_id = {c.campaignid: c for c in campaigns}
    # Revive only links a manager's banners to that same manager's zones.
    client_manager = {c.clientid: c.agencyid for c in clients}
    affiliate_manager = {a.affiliateid: a.agencyid for a in affiliates}
    banner_manager = {b.bannerid: client_manager[campaign_by_id[b.campaignid].clientid] for b in banners}
    rows = []
    for zone in zones:
        rng = np.random.default_rng(seed + zone.zoneid)
        # Each zone serves a rotating subset of banners, not all of them -
        # more realistic than every banner running in every zone.
        zone_manager = affiliate_manager[zone.affiliateid]
        served_banners = [b for i, b in enumerate(banners)
                          if (i + zone.zoneid) % 3 != 0 and banner_manager[b.bannerid] == zone_manager]

        for hour_index in range(total_hours):
            ts = start + timedelta(hours=hour_index)
            fill_rate, requests = _hourly_fill_rate(zone, hour_index, total_hours)
            if requests == 0 or not served_banners:
                continue

            impressions_total = int(rng.binomial(requests, min(fill_rate, 0.99)))
            if impressions_total == 0:
                continue

            # Split impressions across this hour's served banners.
            weights = rng.dirichlet(np.ones(len(served_banners)))
            impressions_per_banner = np.random.default_rng(seed + zone.zoneid + hour_index).multinomial(
                impressions_total, weights
            )

            for banner, banner_impressions in zip(served_banners, impressions_per_banner):
                if banner_impressions == 0:
                    continue
                clicks = int(rng.binomial(banner_impressions, min(banner.base_ctr, 0.99)))
                conversions = int(rng.binomial(clicks, 0.05)) if clicks > 0 else 0
                # requests attributed proportionally for this banner-zone-hour row
                banner_requests = max(banner_impressions, int(requests * (banner_impressions / impressions_total)))
                revenue = _row_revenue(campaign_by_id[banner.campaignid], int(banner_impressions), clicks)

                rows.append({
                    "date_time": ts, "ad_id": banner.bannerid, "creative_id": banner.bannerid,
                    "zone_id": zone.zoneid,
                    "requests": banner_requests, "impressions": int(banner_impressions),
                    "clicks": clicks, "conversions": conversions,
                    "total_revenue": round(revenue, 4),
                    "total_cost": round(_row_cost(zone, revenue, int(banner_impressions)), 4),
                    "updated": ts,
                })

    return pd.DataFrame(rows)


def generate_revive_dataset(total_days: int = 14, seed: int = 7) -> dict[str, pd.DataFrame]:
    managers = generate_managers()
    affiliates = generate_affiliates(managers)
    clients = generate_clients(managers, seed=seed)
    campaigns = generate_campaigns(clients, total_days=total_days, seed=seed)
    banners = generate_banners(campaigns, seed=seed)
    zones = generate_zones(seed=seed)
    stats = generate_hourly_stats(banners, campaigns, zones, clients, affiliates,
                                  total_days=total_days, seed=seed)

    admin = apply_admin_fixtures(managers, affiliates, clients, campaigns, banners, zones, stats, seed=seed)
    managers, affiliates, clients = admin["managers"], admin["affiliates"], admin["clients"]
    campaigns, banners, zones, stats = admin["campaigns"], admin["banners"], admin["zones"], admin["stats"]

    return {
        **{t: admin[t] for t in ADMIN_TABLES},
        "rv_agency": pd.DataFrame([asdict(m) for m in managers]),
        "rv_affiliates": pd.DataFrame([asdict(a) for a in affiliates]),
        "rv_clients": pd.DataFrame([asdict(c) for c in clients]),
        "rv_campaigns": pd.DataFrame([asdict(c) for c in campaigns]),
        "rv_banners": pd.DataFrame([{k: v for k, v in asdict(b).items() if k != "base_ctr"} for b in banners]),
        "rv_zones": pd.DataFrame([{k: v for k, v in asdict(z).items()
                                    if k not in ("scenario", "base_fill_rate", "base_hourly_requests")}
                                   for z in zones]),
        "rv_data_summary_ad_hourly": stats,
        "_zones_with_scenario": pd.DataFrame([asdict(z) for z in zones]),  # kept for verification only
    }
