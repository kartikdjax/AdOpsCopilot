# exchange-tools Specification

## Purpose
Exchange-mode tools for ad-exchange auction data in ClickHouse: bundled reports, real-time health and supply/demand cross-analysis. Revive mode also has a report tool and banner-to-zone mapping, described here because they share the report and cross-analysis code.

## Requirements

### Requirement: Reports bundle KPIs, trend and anomalies
`generate_revive_report` and `generate_exchange_report` SHALL return, in one call, the domain's KPIs for an entity, a trend and anomalies for the primary metric. The exchange report's primary metric SHALL be win rate.

#### Scenario: Exchange report
- **WHEN** a report is generated for one supply partner
- **THEN** it contains 7 KPIs and its primary metric is `win_rate`

#### Scenario: Revive report
- **WHEN** a report is generated for one zone
- **THEN** it contains 8 KPIs, a trend and anomalies

### Requirement: Real-time health covers short windows only
`get_realtime_exchange_health` SHALL compute QPS, bid rate, timeout rate and average latency from raw auction rows over the last N minutes, and SHALL reject windows over 180 minutes.

#### Scenario: Rates
- **WHEN** 9000 requests, 8500 responses, 6000 bids and 450 timeouts fall in a 15-minute window
- **THEN** QPS is 10.0, bid rate is 70.59% and timeout rate is 5.0%

#### Scenario: Window too long
- **WHEN** a 500-minute window is requested
- **THEN** a ValueError is raised

### Requirement: Cross-analysis holds one side fixed
`get_supply_demand_cross_analysis` SHALL require a supply partner id, a demand partner id or both, and SHALL return the metric for each pairing with the given side held fixed. `get_banner_zone_mapping` SHALL return banner-zone pairs ranked by impressions, and without ids SHALL return an account-wide overview limited to 50 pairs.

#### Scenario: No ids
- **WHEN** cross-analysis is called without any partner id
- **THEN** a ValueError is raised

#### Scenario: One DSP across SSPs
- **WHEN** cross-analysis is called for one demand partner
- **THEN** every pair has that demand partner and the supply partners vary
