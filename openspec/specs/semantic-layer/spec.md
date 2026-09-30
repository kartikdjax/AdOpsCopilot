# semantic-layer Specification

## Purpose
Defines metrics once per data domain and builds all SQL in code, so the LLM chooses metrics and entities but never writes queries.

## Requirements

### Requirement: Metrics are defined per domain
The metric registry SHALL hold separate metric sets for the `revive` and `exchange` domains. A metric name MAY exist in both with a different formula. Asking a domain for a metric or entity type it doesn't define SHALL raise a ValueError with a useful message.

#### Scenario: Domain-specific metric
- **WHEN** the revive domain is asked for `win_rate`
- **THEN** a ValueError is raised

#### Scenario: Same name, different formula
- **WHEN** `fill_rate` is looked up in each domain
- **THEN** revive computes it from impressions and exchange from wins

### Requirement: Ratio metrics are safe from division by zero
Every ratio metric's SQL SHALL guard its denominator with NULLIF.

#### Scenario: CTR expression
- **WHEN** the SQL for revive `ctr` is generated
- **THEN** it contains NULLIF

### Requirement: Queries use bound parameters
Query builders SHALL pass entity ids, day counts and limits as bound parameters (ClickHouse `{name:Type}`, MySQL `:name`), never formatted into the SQL text.

#### Scenario: Exchange time series for one entity
- **WHEN** a time series is built for one DSP campaign over 14 days
- **THEN** the SQL contains `{entity_id:UInt32}` and `{days:UInt32}`

#### Scenario: Revive time series for one entity
- **WHEN** a time series is built for one campaign
- **THEN** the SQL contains `:entity_id` and `:days`

### Requirement: Revive joins follow the object hierarchy
The MySQL builder SHALL add joins only when the entity type needs them: none for zones, banner and campaign joins for advertisers.

#### Scenario: Advertiser query
- **WHEN** a time series is built by advertiser
- **THEN** the SQL has exactly two LEFT JOINs and filters on the advertiser id

### Requirement: Rankings can expose volume
Ranking queries SHALL accept a volume metric and return it with each row, so a high rate on tiny volume is visible.

#### Scenario: Ranking with volume guard
- **WHEN** zones are ranked by CTR with impressions as the volume metric
- **THEN** each row includes a volume value and the query is limited
