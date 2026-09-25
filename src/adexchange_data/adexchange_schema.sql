-- Phase 6 extension: Ad Exchange schema - demand (DSP) and supply (SSP)
-- sides of a real-time auction, separate from Revive's ad-serving schema.
--
-- Two-tier design, matching real exchange architecture:
--   - RAW tables (ax_bid_requests, ax_bid_responses, ax_impressions,
--     ax_clicks): per-auction granularity, intended for real-time/
--     short-window operational queries (QPS, timeout rate, latency).
--     In production these would have short retention (hours/days) -
--     the volume is too high to keep indefinitely at this grain.
--   - ax_hourly_stats: pre-aggregated, intended for historical trend
--     analysis over weeks/months, cheap to query at that timescale.

CREATE DATABASE IF NOT EXISTS adexchange;

-- ---------------------------------------------------------------------
-- Supply side (SSP) - who is asking the exchange for ads to fill
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS adexchange.ax_supply_partners
(
    supply_partner_id UInt32,
    partner_name       String,
    partner_type        Enum8('publisher_direct' = 1, 'ssp' = 2)
)
ENGINE = MergeTree
ORDER BY supply_partner_id;

CREATE TABLE IF NOT EXISTS adexchange.ax_ad_units
(
    ad_unit_id        UInt32,
    supply_partner_id UInt32,
    ad_unit_name       String,
    format             Enum8('banner' = 1, 'video' = 2, 'native' = 3),
    floor_price        Decimal(10, 4)
)
ENGINE = MergeTree
ORDER BY ad_unit_id;

-- ---------------------------------------------------------------------
-- Demand side (DSP) - who is bidding to fill supply
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS adexchange.ax_demand_partners
(
    demand_partner_id UInt32,
    partner_name        String
)
ENGINE = MergeTree
ORDER BY demand_partner_id;

CREATE TABLE IF NOT EXISTS adexchange.ax_dsp_campaigns
(
    campaign_id         UInt32,
    demand_partner_id  UInt32,
    campaign_name        String,
    daily_budget         Decimal(10, 2)
)
ENGINE = MergeTree
ORDER BY campaign_id;

-- ---------------------------------------------------------------------
-- RAW auction tables - per-request/response granularity, short retention
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS adexchange.ax_bid_requests
(
    request_id         String,
    request_time        DateTime64(3),
    ad_unit_id          UInt32,
    supply_partner_id  UInt32,
    device_type          Enum8('mobile' = 1, 'desktop' = 2, 'tablet' = 3, 'ctv' = 4),
    geo_country          String,
    floor_price          Decimal(10, 4)
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(request_time)
ORDER BY (ad_unit_id, request_time);

CREATE TABLE IF NOT EXISTS adexchange.ax_bid_responses
(
    request_id          String,
    response_time         DateTime64(3),
    demand_partner_id   UInt32,
    campaign_id          UInt32,
    bid_price             Decimal(10, 4),  -- 0 for no_bid
    latency_ms            UInt32,
    status                 Enum8('bid' = 1, 'no_bid' = 2, 'timeout' = 3, 'error' = 4),
    is_winner              UInt8
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(response_time)
ORDER BY (demand_partner_id, response_time);

CREATE TABLE IF NOT EXISTS adexchange.ax_impressions
(
    request_id          String,
    impression_time      DateTime64(3),
    ad_unit_id           UInt32,
    supply_partner_id   UInt32,
    demand_partner_id   UInt32,
    campaign_id           UInt32,
    win_price              Decimal(10, 4)   -- clearing price, may be < top bid (2nd-price auction)
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(impression_time)
ORDER BY (campaign_id, impression_time);

CREATE TABLE IF NOT EXISTS adexchange.ax_clicks
(
    request_id  String,
    click_time    DateTime64(3),
    campaign_id  UInt32
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(click_time)
ORDER BY (campaign_id, click_time);

-- ---------------------------------------------------------------------
-- Hourly rollup - long retention, fast historical trend/anomaly queries
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS adexchange.ax_hourly_stats
(
    hour                  DateTime,
    supply_partner_id    UInt32,
    ad_unit_id             UInt32,
    demand_partner_id    UInt32,
    campaign_id            UInt32,
    bid_requests           UInt64,
    bid_responses          UInt64,  -- excludes no_bid
    bids                    UInt64,  -- responses with status='bid'
    wins                    UInt64,
    timeouts                UInt64,
    spend                   Decimal(12, 4),
    clicks                  UInt64,
    avg_latency_ms          Float32,
    avg_bid_price           Float32,
    avg_win_price           Float32
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(hour)
ORDER BY (supply_partner_id, demand_partner_id, campaign_id, hour);

-- Example query patterns Phase 7's tools will use:
--
-- Real-time/short-window (RAW tables, e.g. "what's happening right now"):
-- SELECT ad_unit_id,
--        count() AS requests,
--        countIf(status='bid') AS bids,
--        countIf(status='timeout') AS timeouts,
--        round(countIf(status='timeout') / count() * 100, 2) AS timeout_rate_pct,
--        avg(latency_ms) AS avg_latency_ms
-- FROM adexchange.ax_bid_responses
-- WHERE response_time >= now() - INTERVAL 15 MINUTE
-- GROUP BY ad_unit_id;
--
-- Historical trend (HOURLY table, e.g. "how has win rate moved over 30 days"):
-- SELECT toDate(hour) AS day, sum(wins)/sum(bids)*100 AS win_rate_pct
-- FROM adexchange.ax_hourly_stats
-- WHERE campaign_id = 1
-- GROUP BY day ORDER BY day;
