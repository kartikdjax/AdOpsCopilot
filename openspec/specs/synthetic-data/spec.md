# synthetic-data Specification

## Purpose
Provides labelled synthetic data with known scenarios for every feature to be tested against, and loads it only into databases the Copilot owns.

## Requirements

### Requirement: Generators plant known scenarios
The Revive generator SHALL produce zones whose scenarios show in the data (under_monetized fills less than healthy, fill_rate_decline declines, seasonal_growth grows) plus the problems listed in admin_fixtures.PLANTED. The exchange generator SHALL produce a supply partner whose timeouts spike in the last 3 days only, a campaign whose win rate declines, a campaign whose bid price grows, and raw auctions where no request wins more than once.

#### Scenario: Timeout spike
- **WHEN** the exchange data is generated
- **THEN** the spiking partner's timeout rate over the last 3 days is more than 3 times its earlier rate and more than 3 times the stable partner's

#### Scenario: Under-monetised zone
- **WHEN** the Revive data is generated
- **THEN** the under_monetized zone's fill rate is below the healthy zone's

### Requirement: The Revive loader only writes to a claimed synthetic database
`load_revive_data` SHALL refuse to change anything unless the target database has the Revive tables, carries the `copilot_synthetic_marker` table, and holds only generator-named rows in the advertiser, website, campaign and zone tables. The loader SHALL keep Revive's own admin login, the Default manager and Revive's own audit rows.

#### Scenario: Unclaimed database
- **WHEN** the loader targets a database without the marker
- **THEN** it exits non-zero, explains how to claim it, and changes nothing

#### Scenario: Real rows present
- **WHEN** the loader or a claim targets a database with an advertiser named "NB Test Advertiser"
- **THEN** it exits non-zero naming that row, and changes nothing

#### Scenario: Claimed synthetic database
- **WHEN** the loader targets a claimed database holding only generator rows
- **THEN** it replaces the synthetic data

### Requirement: A database is claimed explicitly
The marker table SHALL be created only by `--claim <database>`, where the name must equal the target database, and only if the database holds no foreign rows. Claiming an already-claimed database SHALL change nothing.

#### Scenario: Claim with the wrong name
- **WHEN** `--claim` names a database other than the target
- **THEN** no marker is created and nothing is loaded

#### Scenario: Claim twice
- **WHEN** a claimed database is claimed again
- **THEN** it still has exactly one marker row
