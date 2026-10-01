# Spec Delta

## MODIFIED Requirements

### Requirement: A database is claimed explicitly
The marker table SHALL be created only in two ways: by `--claim <database>`, where the name must equal the target database, and only if the database holds no foreign rows; or by the setup command when it creates the Revive tables itself in a database that held none. Claiming an already-claimed database SHALL change nothing.

#### Scenario: Claim with the wrong name
- **WHEN** `--claim` names a database other than the target
- **THEN** no marker is created and nothing is loaded

#### Scenario: Claim twice
- **WHEN** a claimed database is claimed again
- **THEN** it still has exactly one marker row

#### Scenario: Setup bootstraps an empty database
- **WHEN** setup targets a MySQL database with no Revive tables
- **THEN** it creates the tables and the marker, and the loader accepts the database

## ADDED Requirements

### Requirement: A fresh Revive database can be bootstrapped
The project SHALL carry the MySQL definitions, taken from Revive 6.0.8, of every Revive table the Copilot reads or loads, and Revive's base rows: the Default manager, the administrator and manager accounts, an `admin` user that can never log in, and the application-variable rows reporting the Revive version and plugins. Bootstrapping SHALL create these in a database with no Revive tables.

#### Scenario: Tables the app needs
- **WHEN** the bootstrap definitions are compared with the tables the Copilot's queries and loader name
- **THEN** every such table has a definition

#### Scenario: Admin can't log in
- **WHEN** the bootstrapped `admin` user's password field is read
- **THEN** it holds a value no password hash produces

### Requirement: The exchange loader only replaces data in a Copilot-owned database
The exchange loaders SHALL read ClickHouse connection settings from the environment. `load_adexchange_data` SHALL replace, not append to, every table it writes, and both it and the real-time refresh SHALL refuse to run unless the `adexchange` database carries the Copilot marker table. `--claim adexchange` SHALL mark an existing database, and setup SHALL mark one it creates.

#### Scenario: Reload doesn't duplicate
- **WHEN** the exchange loader runs twice on a Copilot-owned database
- **THEN** each table holds the rows of one run only

#### Scenario: Unowned database
- **WHEN** the exchange loader or refresh targets an `adexchange` database without the marker
- **THEN** it exits non-zero, explains how to claim it, and changes nothing
