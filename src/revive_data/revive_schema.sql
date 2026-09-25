-- Phase 6: Revive Adserver-accurate schema.
--
-- Table and column names deliberately match Revive's REAL MySQL schema
-- (rv_clients, rv_campaigns, rv_banners, rv_zones, rv_data_summary_ad_hourly)
-- so that swapping synthetic data for a real Revive MySQL connection
-- later is a connection-string + ETL-source change, not a rewrite of
-- every query and MCP tool built on top of this.
--
-- Real Revive stores this in MySQL (OLTP); we mirror it into ClickHouse
-- (OLAP) for fast conversational analytics, via periodic ETL sync -
-- this does NOT touch Revive's live production read path, which matters
-- for a plugin that has to coexist with the actual ad-serving system.

CREATE DATABASE IF NOT EXISTS revive;

CREATE TABLE IF NOT EXISTS revive.rv_clients
(
    clientid    UInt32,
    clientname  String,
    contactname String,
    email       String
)
ENGINE = MergeTree
ORDER BY clientid;

CREATE TABLE IF NOT EXISTS revive.rv_campaigns
(
    campaignid   UInt32,
    clientid     UInt32,
    campaignname String,
    activate_time DateTime,
    expire_time   DateTime,
    views        UInt64,   -- lifetime impression target/cap, Revive's real field name
    clicks       UInt64,   -- lifetime click cap
    status       Int8      -- Revive uses signed int: 0=active in some versions; kept generic
)
ENGINE = MergeTree
ORDER BY campaignid;

CREATE TABLE IF NOT EXISTS revive.rv_banners
(
    bannerid    UInt32,
    campaignid  UInt32,
    description String,
    -- Revive calls creatives "banners" regardless of format (image/HTML/video)
    banner_type Enum8('image' = 1, 'html' = 2, 'video' = 3)
)
ENGINE = MergeTree
ORDER BY bannerid;

CREATE TABLE IF NOT EXISTS revive.rv_zones
(
    zoneid      UInt32,
    -- "affiliateid" is Revive's real internal name for a publisher/site
    -- owner - kept as-is for schema fidelity, even though "publisher" is
    -- the term you'd use in the UI/conversation.
    affiliateid UInt32,
    zonename    String,
    -- Revive's real zone type enum: 1=banner, 2=interstitial, 3=email,
    -- 4=text ad, 5=popup - simplified here to the common ones.
    zone_type   Enum8('banner' = 1, 'interstitial' = 2, 'popup' = 5)
)
ENGINE = MergeTree
ORDER BY zoneid;

-- The core stats fact table - matches rv_data_summary_ad_hourly's real
-- columns and hourly granularity. `requests` here is AD REQUESTS (a
-- zone asking for a banner to serve), not OpenRTB bid requests - that's
-- a separate concept introduced in Phase 7's SSP tools.
CREATE TABLE IF NOT EXISTS revive.rv_data_summary_ad_hourly
(
    date_time   DateTime,
    ad_id       UInt32,   -- = bannerid, Revive's real column name
    zone_id     UInt32,
    requests    UInt64,   -- ad requests received for this banner+zone+hour
    impressions UInt64,
    clicks      UInt64,
    conversions UInt64
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(date_time)
ORDER BY (ad_id, zone_id, date_time);

-- Example query pattern MCP tools will use - fill rate is a first-class
-- SSP metric and falls directly out of requests vs impressions:
-- SELECT zone_id,
--        sum(requests) AS requests,
--        sum(impressions) AS impressions,
--        round(sum(impressions) / sum(requests) * 100, 2) AS fill_rate_pct
-- FROM revive.rv_data_summary_ad_hourly
-- WHERE date_time >= now() - INTERVAL 7 DAY
-- GROUP BY zone_id
-- ORDER BY fill_rate_pct ASC;
