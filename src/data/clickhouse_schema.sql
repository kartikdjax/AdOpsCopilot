-- AI Analytics Copilot: ClickHouse schema
-- Design notes:
--   - `ad_events` is the raw fact table: one row per impression/click/conversion.
--     ClickHouse is an OLAP columnar store, so wide, append-only fact tables
--     with a good ORDER BY key are the right shape (unlike a normalized OLTP schema).
--   - `daily_campaign_stats` is a materialized view: ClickHouse pre-aggregates
--     into it on INSERT, so dashboards/KPI queries hit a small pre-summed table
--     instead of scanning millions of raw event rows every time.

CREATE DATABASE IF NOT EXISTS adtech;

CREATE TABLE IF NOT EXISTS adtech.advertisers
(
    advertiser_id   UInt32,
    advertiser_name String,
    industry        String
)
ENGINE = MergeTree
ORDER BY advertiser_id;

CREATE TABLE IF NOT EXISTS adtech.campaigns
(
    campaign_id     UInt32,
    advertiser_id   UInt32,
    campaign_name   String,
    status          Enum8('active' = 1, 'paused' = 2, 'ended' = 3),
    daily_budget    Decimal(10, 2),
    start_date      Date,
    end_date        Date
)
ENGINE = MergeTree
ORDER BY campaign_id;

-- Raw event fact table. event_type covers the full funnel.
CREATE TABLE IF NOT EXISTS adtech.ad_events
(
    event_time      DateTime,
    event_date      Date DEFAULT toDate(event_time),
    campaign_id     UInt32,
    event_type      Enum8('impression' = 1, 'click' = 2, 'conversion' = 3),
    spend           Decimal(10, 4),   -- cost attributed to this event (0 for impressions if CPC billing)
    device_type     Enum8('mobile' = 1, 'desktop' = 2, 'tablet' = 3),
    geo_country     String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_date)
ORDER BY (campaign_id, event_time);

-- Pre-aggregated daily stats per campaign, kept in sync automatically as
-- ad_events rows are inserted (AggregatingMergeTree + MV = "materialized view").
CREATE TABLE IF NOT EXISTS adtech.daily_campaign_stats
(
    event_date      Date,
    campaign_id     UInt32,
    impressions     AggregateFunction(sum, UInt64),
    clicks          AggregateFunction(sum, UInt64),
    conversions     AggregateFunction(sum, UInt64),
    spend           AggregateFunction(sum, Decimal(10, 4))
)
ENGINE = AggregatingMergeTree
ORDER BY (campaign_id, event_date);

CREATE MATERIALIZED VIEW IF NOT EXISTS adtech.daily_campaign_stats_mv
TO adtech.daily_campaign_stats
AS
SELECT
    event_date,
    campaign_id,
    sumState(toUInt64(event_type = 'impression')) AS impressions,
    sumState(toUInt64(event_type = 'click'))       AS clicks,
    sumState(toUInt64(event_type = 'conversion'))  AS conversions,
    sumState(spend)                                AS spend
FROM adtech.ad_events
GROUP BY event_date, campaign_id;

-- Example query showing the pattern MCP tools will use:
-- SELECT event_date, campaign_id,
--        sumMerge(impressions) AS impressions,
--        sumMerge(clicks) AS clicks,
--        sumMerge(clicks) / sumMerge(impressions) * 100 AS ctr
-- FROM adtech.daily_campaign_stats
-- WHERE campaign_id = 1001
-- GROUP BY event_date, campaign_id
-- ORDER BY event_date;
