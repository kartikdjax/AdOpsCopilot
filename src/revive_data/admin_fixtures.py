"""
Admin-side fixtures for the Revive synthetic dataset: banner/campaign-zone
links, targeting rules, login accounts, users - plus one PLANTED problem
per run_revive_check check, so each check has a known, labeled answer
(the same idea as the zone scenarios in generate_revive_data.py).

Planted problems (see PLANTED for the IDs tests assert against):
  - campaigns_expiring:     campaign 5 ends in 3 days
  - campaigns_behind_pace:  campaign 3 is booked for 2x what it can deliver
  - active_no_delivery:     campaign 6 is running but stopped delivering 36h ago
  - campaigns_not_running:  campaign 4 is paused; campaign 7 hasn't started yet
  - unlinked_zones:         zone 3006 has nothing linked
  - size_mismatch:          728x90 banner 14 is linked to 300x250 zone 3000
  - zero_fill_zones:        zone 3007 gets requests but serves nothing
  - inactive_users:         users 103, 104 (never logged in), 106

Audit trail (rv_audit): one event behind each planted problem, plus
routine noise - see _audit_events. Loaded directly, our objects were
never audited by Revive itself, so without these the audit log would
have nothing to say about them.

Everything here is keyed by fixed IDs at or above SYNTHETIC_ID_START in
the tables that also hold the real install's own rows (rv_accounts,
rv_users), so the loader can replace them without touching the admin
login.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import phpserialize

SYNTHETIC_ID_START = 100          # rv_accounts / rv_users rows from here up are synthetic
DEFAULT_MANAGER_ACCOUNT_ID = 2    # the install's own Default manager account

# Real Revive campaign status codes (OA_ENTITY_STATUS_*).
STATUS_RUNNING, STATUS_PAUSED, STATUS_AWAITING = 0, 1, 2

# A password no hash function produces - these users can never log in.
_NO_LOGIN_PASSWORD = "!synthetic-no-login"

PLANTED = {
    "campaigns_expiring": [5],
    "campaigns_behind_pace": [3],
    "active_no_delivery": [6],
    "campaigns_not_running": [4, 7],
    "unlinked_zones": [3006],
    "size_mismatch": [(14, 3000)],
    "zero_fill_zones": [3007],
    "inactive_users": [103, 104, 106],
}

# Real Revive audit action codes.
AUDIT_INSERT, AUDIT_UPDATE, AUDIT_DELETE = 1, 2, 3


@dataclass(frozen=True, slots=True)
class Account:
    account_id: int
    account_type: str      # ADMIN | MANAGER | ADVERTISER | TRAFFICKER (website)
    account_name: str


@dataclass(frozen=True, slots=True)
class User:
    user_id: int
    contact_name: str
    email_address: str
    username: str
    password: str
    default_account_id: int
    active: int
    date_created: datetime
    date_last_login: datetime | None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None)


def apply_admin_fixtures(managers, affiliates, clients, campaigns, banners, zones,
                         stats: pd.DataFrame, seed: int = 7) -> dict:
    """Takes the performance dataset from generate_revive_dataset and returns
    updated object lists + stats, and the admin-only tables. New objects are
    added AFTER stats generation so the existing zone scenarios keep the
    exact same random draws."""
    from src.revive_data.generate_revive_data import FINANCE_CPM, FINANCE_RS, Campaign

    rng = np.random.default_rng(seed)
    now = _now()
    banner_campaign = {b.bannerid: b.campaignid for b in banners}
    stats = stats.copy()
    stats["campaignid"] = stats["ad_id"].map(banner_campaign)

    # --- Planted delivery problems on existing campaigns --------------------
    # Campaign 4 paused 5 days ago: no delivery since.
    stats = stats[~((stats["campaignid"] == 4) & (stats["date_time"] >= now - timedelta(days=5)))]
    # Campaign 6 still running but nothing in the last 36h.
    stats = stats[~((stats["campaignid"] == 6) & (stats["date_time"] >= now - timedelta(hours=36)))]

    # Booked impressions (views): set so every running campaign is exactly on
    # pace, except campaign 3, booked for twice that (50% pace).
    delivered = stats.groupby("campaignid")["impressions"].sum().to_dict()
    updated_campaigns = []
    for c in campaigns:
        expire = now + timedelta(days=3) if c.campaignid == 5 else c.expire_time
        elapsed = (now - c.activate_time).total_seconds()
        total = (expire - c.activate_time).total_seconds()
        views = int(delivered.get(c.campaignid, 0) * total / elapsed)
        if c.campaignid == 3:
            views *= 2
        updated_campaigns.append(replace(
            c, expire_time=expire, views=views, clicks=-1,  # -1 = no click goal, as in Revive
            status=STATUS_PAUSED if c.campaignid == 4 else c.status,
        ))
    campaigns = updated_campaigns

    # --- New objects: not part of the performance generation ---------------
    campaigns.append(Campaign(
        campaignid=7, clientid=2002, campaignname="Advertiser_3_Campaign_3",
        activate_time=now + timedelta(days=5), expire_time=now + timedelta(days=35),
        views=500_000, clicks=-1, status=STATUS_AWAITING, revenue=2.5, revenue_type=FINANCE_CPM,
        updated=now,
    ))
    template = banners[0]
    banners = banners + [
        replace(template, bannerid=13, campaignid=7, description="Advertiser_3_Campaign_3_Banner_1"),
        replace(template, bannerid=14, campaignid=1, description="Advertiser_1_Campaign_1_Leaderboard",
                width=728, height=90),
    ]
    # Zone_3's fill decline starts mid-window: it's the day someone capped it.
    zones = [replace(z, capping=3) if z.zoneid == 3002 else z for z in zones]
    zone_template = zones[0]
    zones = zones + [
        replace(zone_template, zoneid=3006, affiliateid=4000, zonename="Zone_7_unlinked",
                cost=50.0, cost_type=FINANCE_RS, scenario="unlinked", base_fill_rate=0.0,
                base_hourly_requests=0),
        replace(zone_template, zoneid=3007, affiliateid=4001, zonename="Zone_8_zero_fill",
                cost=50.0, cost_type=FINANCE_RS, scenario="zero_fill", base_fill_rate=0.0,
                base_hourly_requests=0),
    ]

    # Zone 3007: Manager_2's banners 5, 7, 8 get requests for 7 days, never an impression.
    zero_fill_rows = [
        {"date_time": now - timedelta(hours=h), "ad_id": ad_id, "creative_id": ad_id, "zone_id": 3007,
         "requests": int(rng.integers(15, 30)), "impressions": 0, "clicks": 0, "conversions": 0,
         "total_revenue": 0.0, "total_cost": 0.0, "updated": now - timedelta(hours=h)}
        for h in range(1, 7 * 24 + 1) for ad_id in (5, 7, 8)
    ]
    stats = pd.concat([stats.drop(columns="campaignid"), pd.DataFrame(zero_fill_rows)], ignore_index=True)

    # --- Links: every pair that delivered, plus the planted ones ------------
    pairs = set(map(tuple, stats[["ad_id", "zone_id"]].drop_duplicates().itertuples(index=False)))
    pairs |= {(14, 3000), (13, 3002)}  # size mismatch; not-yet-started campaign 7
    banner_campaign = {b.bannerid: b.campaignid for b in banners}
    ad_zone = pd.DataFrame(
        [{"zone_id": int(z), "ad_id": int(a), "priority": 0.0, "link_type": 1,
          "priority_factor": 1.0, "to_be_delivered": 1} for a, z in sorted(pairs)]
    )
    placement_zone = pd.DataFrame(sorted(
        {(int(z), banner_campaign[int(a)]) for a, z in pairs}), columns=["zone_id", "placement_id"])

    # --- Targeting rules (real Revive delivery-limitation plugin names) ------
    acls = pd.DataFrame([
        {"bannerid": 1, "logical": "and", "type": "deliveryLimitations:Geo:Country",
         "comparison": "=~", "data": "US,GB,CA", "executionorder": 0},
        {"bannerid": 1, "logical": "and", "type": "deliveryLimitations:Time:Day",
         "comparison": "=~", "data": "1,2,3,4,5", "executionorder": 1},
        {"bannerid": 5, "logical": "and", "type": "deliveryLimitations:Client:Browser",
         "comparison": "!~", "data": "IE", "executionorder": 0},
        {"bannerid": 9, "logical": "and", "type": "deliveryLimitations:Time:Hour",
         "comparison": "=~", "data": "8,9,10,11,12,13,14,15,16,17,18", "executionorder": 0},
        {"bannerid": 14, "logical": "and", "type": "deliveryLimitations:Geo:Country",
         "comparison": "==", "data": "IN", "executionorder": 0},
    ])

    # --- Accounts: one per synthetic manager, advertiser and website --------
    accounts: list[Account] = []
    next_id = SYNTHETIC_ID_START
    manager_account = {1: DEFAULT_MANAGER_ACCOUNT_ID}
    for m in managers:
        accounts.append(Account(next_id, "MANAGER", m.name))
        manager_account[m.agencyid] = next_id
        next_id += 1
    client_account, affiliate_account = {}, {}
    for c in clients:
        accounts.append(Account(next_id, "ADVERTISER", c.clientname))
        client_account[c.clientid] = next_id
        next_id += 1
    for a in affiliates:
        accounts.append(Account(next_id, "TRAFFICKER", a.name))
        affiliate_account[a.affiliateid] = next_id
        next_id += 1

    # --- Users: every role and login state, three of them inactive -----------
    def user(uid, username, name, account, active, last_login_days):
        last = None if last_login_days is None else now - timedelta(days=last_login_days)
        return User(uid, name, f"{username}@example.com", username, _NO_LOGIN_PASSWORD,
                    account, active, now - timedelta(days=400), last)

    users = [
        user(100, "mgr2_ops", "Manager 2 Ops", manager_account[2], 1, 2),
        user(101, "default_mgr_analyst", "Default Manager Analyst", DEFAULT_MANAGER_ACCOUNT_ID, 1, 10),
        user(102, "adv1_owner", "Advertiser 1 Owner", client_account[2000], 1, 5),
        user(103, "adv2_owner", "Advertiser 2 Owner", client_account[2001], 1, 120),
        user(104, "adv3_owner", "Advertiser 3 Owner", client_account[2002], 1, None),
        user(105, "web1_owner", "Website 1 Owner", affiliate_account[4000], 1, 30),
        user(106, "web2_owner", "Website 2 Owner", affiliate_account[4001], 1, 200),
        user(107, "web3_former", "Website 3 Former Owner", affiliate_account[4002], 0, 400),
        user(108, "agency_buyer", "Agency Buyer", client_account[2000], 1, 1),
    ]
    user_accounts = [(u.user_id, u.default_account_id) for u in users] + [(108, client_account[2002])]
    account_user = pd.DataFrame([{"account_id": acc, "user_id": uid, "linked": now - timedelta(days=400)}
                                 for uid, acc in user_accounts])

    fill_decline_start = stats["date_time"].min() + (now - stats["date_time"].min()) / 2
    audit = _audit_events(now, fill_decline_start, users, campaigns)

    return {
        "rv_audit": audit,
        "managers": [replace(m, account_id=manager_account[m.agencyid]) for m in managers],
        "clients": [replace(c, account_id=client_account[c.clientid]) for c in clients],
        "affiliates": [replace(a, account_id=affiliate_account[a.affiliateid]) for a in affiliates],
        "campaigns": campaigns,
        "banners": banners,
        "zones": zones,
        "stats": stats,
        "rv_ad_zone_assoc": ad_zone,
        "rv_placement_zone_assoc": placement_zone,
        "rv_acls": acls,
        "rv_accounts": pd.DataFrame([asdict(a) for a in accounts]),
        "rv_users": pd.DataFrame([asdict(u) for u in users]),
        "rv_account_user_assoc": account_user,
    }


def _serialize(details: dict) -> str:
    """Revive stores audit details as a PHP-serialized array."""
    return phpserialize.dumps(details).decode("utf-8")


def _change(was, is_) -> dict:
    return {"was": was, "is": is_}


def _audit_events(now: datetime, fill_decline_start: datetime, users: list[User],
                  campaigns: list) -> pd.DataFrame:
    """One event behind each planted problem, plus routine noise. Every
    event matches the object's CURRENT state, so the audit log and
    inspect_revive_object never contradict each other."""
    by_name = {u.username: u for u in users}
    campaign = {c.campaignid: c for c in campaigns}
    fmt = "%Y-%m-%d %H:%M:%S"

    events = [
        # (hours ago, username, action, context, contextid, details)
        (5 * 24 + 1, "mgr2_ops", AUDIT_UPDATE, "campaigns", 4,
         {"status": _change(0, 1), "key_desc": campaign[4].campaignname}),
        (10 * 24, "mgr2_ops", AUDIT_UPDATE, "campaigns", 3,
         {"views": _change(campaign[3].views // 2, campaign[3].views), "key_desc": campaign[3].campaignname}),
        (3 * 24, "default_mgr_analyst", AUDIT_INSERT, "banners", 14,
         {"bannerid": 14, "campaignid": 1, "width": 728, "height": 90,
          "description": "Advertiser_1_Campaign_1_Leaderboard", "key_desc": "Advertiser_1_Campaign_1_Leaderboard"}),
        (3 * 24 - 1, "default_mgr_analyst", AUDIT_INSERT, "ad_zone_assoc", 0,
         {"ad_id": 14, "zone_id": 3000, "link_type": 1, "key_desc": "Ad #14 -> Zone #3000"}),
        ((now - fill_decline_start).total_seconds() / 3600 + 2, "default_mgr_analyst", AUDIT_UPDATE, "zones", 3002,
         {"capping": _change(0, 3), "key_desc": "Zone_3_fill_rate_decline"}),
        (4 * 24, "default_mgr_analyst", AUDIT_UPDATE, "campaigns", 5,
         {"expire_time": _change((now + timedelta(days=30)).strftime(fmt), campaign[5].expire_time.strftime(fmt)),
          "key_desc": campaign[5].campaignname}),
        (20 * 24, "default_mgr_analyst", AUDIT_UPDATE, "users", 107,
         {"active": _change(1, 0), "key_desc": "web3_former"}),
        (7 * 24, "mgr2_ops", AUDIT_INSERT, "zones", 3007,
         {"zoneid": 3007, "affiliateid": 4001, "zonename": "Zone_8_zero_fill", "width": 300, "height": 250,
          "key_desc": "Zone_8_zero_fill"}),
        (24, "default_mgr_analyst", AUDIT_INSERT, "campaigns", 7,
         {"campaignid": 7, "clientid": 2002, "campaignname": "Advertiser_3_Campaign_3", "status": 2,
          "views": 500_000, "key_desc": "Advertiser_3_Campaign_3"}),
        (23, "default_mgr_analyst", AUDIT_INSERT, "placement_zone_assoc", 0,
         {"placement_id": 7, "zone_id": 3002, "key_desc": "Campaign #7 -> Zone #3002"}),
        # Routine noise.
        (2 * 24, "mgr2_ops", AUDIT_UPDATE, "banners", 5,
         {"weight": _change(2, 1), "key_desc": "Advertiser_2_Campaign_1_Banner_1"}),
        (8 * 24, "default_mgr_analyst", AUDIT_INSERT, "acls", 1,
         {"bannerid": 1, "type": "deliveryLimitations:Time:Day", "comparison": "=~", "data": "1,2,3,4,5",
          "key_desc": "Banner #1 -> Time:Day"}),
        (30 * 24, "web1_owner", AUDIT_UPDATE, "users", 105,
         {"contact_name": _change("Website One Owner", "Website 1 Owner"),
          "password": _change("5f4dcc3b5aa765d61d8327deb882cf99", "e10adc3949ba59abbe56e057f20f883e"),
          "key_desc": "web1_owner"}),
    ]
    rows = []
    for hours_ago, username, action, context, contextid, details in events:
        user = by_name[username]
        rows.append({
            "actionid": action, "context": context, "contextid": contextid, "parentid": None,
            "details": _serialize(details), "userid": user.user_id, "username": username, "usertype": 0,
            "updated": now - timedelta(hours=hours_ago), "account_id": user.default_account_id,
        })
    return pd.DataFrame(rows)
