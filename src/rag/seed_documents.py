"""
Seed documents for the knowledge base. Replace/extend these with your
real Revive/DSP/SSP operational docs once available - these are
representative placeholders so the RAG half of the copilot is testable
end-to-end before real documents exist.
"""
from __future__ import annotations

SEED_DOCUMENTS = [
    {
        "source": "targeting_policy.md",
        "text": (
            "Lookalike Audience Expansion Policy\n\n"
            "Lookalike audiences must be capped at 5% expansion from the seed "
            "audience. Historical analysis across multiple advertiser verticals "
            "shows that expansion beyond this threshold degrades CTR by 20-40% "
            "and increases cost per acquisition significantly, because the "
            "expanded audience shares fewer meaningful behavioral signals with "
            "the original seed group.\n\n"
            "Exception: performance marketing campaigns with a seed audience "
            "over 500,000 users may expand up to 8%, since larger seed "
            "audiences tolerate wider expansion without the same signal loss."
        ),
    },
    {
        "source": "budget_pacing_playbook.md",
        "text": (
            "Budget Pacing and Exhaustion Response\n\n"
            "When a campaign exhausts its daily budget before end of day, "
            "delivery is automatically capped by the ad server - this is "
            "expected behavior, not a system fault. Campaigns exhausting "
            "budget before 6pm local time for 3+ consecutive days are strong "
            "candidates for a budget increase, since they are leaving "
            "addressable inventory unfilled during peak conversion hours.\n\n"
            "Do not increase budget reactively on a single exhaustion day - "
            "day-of-week seasonality (weekends typically pace faster) can "
            "cause a single early exhaustion that resolves itself the next day."
        ),
    },
    {
        "source": "anomaly_response_playbook.md",
        "text": (
            "CTR Anomaly Response Procedure\n\n"
            "A sudden CTR drop exceeding 3 standard deviations from the "
            "7-day trailing baseline should first be checked against three "
            "common causes, in this order: (1) creative or landing page "
            "changes deployed in the last 24 hours, (2) tracking pixel or "
            "conversion API outages reported by the ad server, (3) a shift "
            "in traffic mix toward lower-performing placements or devices.\n\n"
            "Only after ruling out these three causes should the anomaly be "
            "escalated as a genuine performance issue requiring targeting or "
            "bid strategy changes. Most CTR anomalies resolve within 48 hours "
            "without intervention once the underlying technical cause is fixed."
        ),
    },
    {
        "source": "reporting_standards.md",
        "text": (
            "Campaign Reporting Standards\n\n"
            "All automated reports must state the reporting period explicitly "
            "and distinguish between period-over-period comparisons (e.g. "
            "this week vs last week) and trend comparisons (e.g. first half "
            "vs second half of a 30-day window), since these answer different "
            "questions and are not interchangeable.\n\n"
            "CTR and CVR should always be reported alongside their underlying "
            "volume (impressions, clicks) - a percentage change on very low "
            "volume can be statistically meaningless and should be flagged as "
            "low-confidence rather than presented with the same weight as a "
            "change backed by high volume."
        ),
    },
    # --- Revive ad server playbooks (pair with the Revive admin tools) -----
    {
        "source": "revive_fill_rate_playbook.md",
        "text": (
            "Revive Zone Fill Rate Drop Checklist\n\n"
            "When a zone's fill rate (impressions / requests) falls, check these in order "
            "before touching demand: (1) settings changed on the zone itself - frequency "
            "capping, session capping or block time added recently will cut fill for "
            "returning visitors; check the audit log for the zone around the date the "
            "drop started. (2) Linked campaigns that paused, expired or finished their "
            "booked impressions - a zone with fewer eligible banners fills less. "
            "(3) Linked banners whose size doesn't match the zone - they never serve there. "
            "(4) Targeting rules on the linked banners that exclude most of the zone's "
            "traffic (country, day, hour, browser). (5) A zone that gets requests but no "
            "impressions at all usually has no eligible banner or a broken tag.\n\n"
            "Revert a capping change only after confirming with the website's manager - "
            "caps are often set deliberately to protect user experience."
        ),
    },
    {
        "source": "revive_pacing_playbook.md",
        "text": (
            "Revive Campaign Pacing Response\n\n"
            "A campaign is behind pace when delivery so far is below 90% of what it "
            "should have delivered by now (booked impressions x time elapsed / total run "
            "time). First check whether the booking itself changed - an increased booked "
            "total mid-flight puts a healthy campaign behind pace overnight; the audit log "
            "shows who changed it and when. Then compare the required daily impressions "
            "with what the campaign's linked zones can realistically supply.\n\n"
            "Options, least disruptive first: link the campaign to more matching zones; "
            "extend the end date with the advertiser's agreement; raise the campaign "
            "weight among its peers; only then raise priority. Never raise priority on "
            "several campaigns sharing the same zones at once - they compete with each other."
        ),
    },
    {
        "source": "revive_priority_change_policy.md",
        "text": (
            "Before Changing a Revive Campaign's Priority or Weight\n\n"
            "Revive serves contract campaigns (with booked impression goals) ahead of "
            "remnant campaigns, and uses weight to split delivery among campaigns of the "
            "same priority. Before changing priority or weight: (1) inspect the campaign "
            "for its booked goal, end date and pacing; (2) list the other campaigns linked "
            "to the same zones - a priority increase takes delivery from them, including "
            "other advertisers' contracted goals; (3) check that Revive's priority "
            "maintenance is running, since new priorities only take effect when it "
            "recalculates.\n\n"
            "Record the reason with the change. Priority changes that put another "
            "contracted campaign behind pace need the other advertiser's manager to agree."
        ),
    },
    {
        "source": "revive_maintenance_runbook.md",
        "text": (
            "Revive Maintenance Runbook\n\n"
            "Revive's maintenance job must run hourly (usually from cron). Statistics "
            "maintenance summarises raw delivery logs into the hourly stats tables; "
            "priority maintenance recalculates how fast each campaign should deliver to "
            "meet its booked goals. If statistics maintenance stops, reports stop "
            "updating; if priority maintenance stops, contract campaigns drift off pace "
            "even though ads still serve.\n\n"
            "If maintenance is overdue by more than 2 hours: check the cron entry and the "
            "maintenance log, run maintenance manually once, and confirm the last-run time "
            "updates. Do not report pacing problems as campaign issues until maintenance "
            "is healthy again."
        ),
    },
]
