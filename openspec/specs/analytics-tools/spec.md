# analytics-tools Specification

## Purpose
The 11 core tools available in every mode: metric catalogue, freshness, KPIs, period comparison, rankings, trends, anomalies, change explanation and knowledge-base search.

## Requirements

### Requirement: Metric catalogue needs no data access
`list_available_metrics` and `get_metric_definition` SHALL answer from the registry without querying data or requiring a scope.

#### Scenario: Metric definition
- **WHEN** the exchange `fill_rate` definition is requested
- **THEN** its formula mentions wins

### Requirement: Period comparison separates real moves from noise
`compare_periods` SHALL compare the current window with the previous window of equal length and label the direction `increasing`, `decreasing` or `stable`.

#### Scenario: Real decline
- **WHEN** win rate falls from 24.0 to 18.0
- **THEN** the direction is `decreasing`

#### Scenario: Flat metric
- **WHEN** fill rate is unchanged between windows
- **THEN** the direction is `stable`

### Requirement: Rankings resolve names and keep volume
`rank_entities` SHALL return entity names and, when a volume metric is given, each entity's volume.

#### Scenario: Low-volume entity
- **WHEN** an entity ranks on a rate backed by 40 impressions
- **THEN** its result shows volume 40

### Requirement: Trend and anomaly detection
`analyze_trend` SHALL classify a series as `increasing`, `decreasing` or `stable`, and `detect_anomalies` SHALL flag days far from their rolling baseline.

#### Scenario: Known step change
- **WHEN** the ctr_improvement campaign's CTR is analysed
- **THEN** the trend is `increasing`

#### Scenario: Noise only
- **WHEN** the stable campaign's CTR is analysed
- **THEN** the trend is `stable`

#### Scenario: Known crash day
- **WHEN** anomalies are detected on the ctr_anomaly_drop campaign
- **THEN** at least one anomaly is found

### Requirement: Change explanations rank contributors by absolute change
`explain_metric_change` SHALL rank child entities by the absolute size of their change, not by percentage change.

#### Scenario: Large drop versus tiny swing
- **WHEN** one campaign drops by about 80,000 units and another goes from 8 to 2
- **THEN** the 80,000-unit drop is the top contributor
