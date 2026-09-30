# revive-admin-tools Specification

## Purpose
Revive-mode tools that answer ad-ops questions about setup and history: health checks, object inspection, the audit log and maintenance status. All read Revive's MySQL database and respect the user's scope.

## Requirements

### Requirement: Health checks find setup problems
`run_revive_check` SHALL offer these checks: campaigns_expiring, campaigns_behind_pace, active_no_delivery, campaigns_not_running, unlinked_zones, size_mismatch, zero_fill_zones and inactive_users. Each SHALL return matching rows capped at 50 with a truncated flag. `all` SHALL return each check's row count. Unknown checks, parameters a check doesn't take and negative values SHALL raise ValueError.

#### Scenario: Planted problems
- **WHEN** each check runs against freshly loaded synthetic data
- **THEN** it finds exactly the rows planted for it in admin_fixtures.PLANTED, and no other synthetic rows

#### Scenario: Overview counts
- **WHEN** the `all` check runs
- **THEN** each count equals the number of rows its own check returns

#### Scenario: Parameters change the answer
- **WHEN** campaigns_expiring runs with a 2-day window and the planted campaign ends in 3 days
- **THEN** no rows are returned

### Requirement: Objects can be inspected without secrets
`inspect_revive_object` SHALL return the fields and related links of a campaign, banner, zone, website, advertiser, manager or user by id, decoding Revive status and revenue codes into labels. User results SHALL never include password fields. A missing id SHALL raise ValueError.

#### Scenario: Campaign
- **WHEN** a running CPM campaign with no click goal is inspected
- **THEN** its status label is `running`, revenue type `CPM` and booked clicks `unlimited`

#### Scenario: User
- **WHEN** a user is inspected
- **THEN** no field name contains "password"

### Requirement: The audit log answers who changed what
`get_revive_audit_log` SHALL return Revive audit events filtered by object type and id, username, action and a day window, with each change as field, old value and new value. Events on a banner's zone links SHALL be included with the banner's history. Password fields SHALL never appear. An object id without an object type, an unknown object type or an unknown action SHALL raise ValueError.

#### Scenario: Who paused a campaign
- **WHEN** the audit log for the planted paused campaign is requested
- **THEN** it shows one event by the user who paused it, with status changing from running to paused

#### Scenario: Day window
- **WHEN** the window is shorter than the age of an object's only event
- **THEN** no events are returned

### Requirement: Freshness reports Revive's system state
`get_data_freshness` for revive SHALL include the Revive version, installed plugins and the status of statistics and priority maintenance: `ok`, `overdue` with a warning, or `never_run` with a warning.

#### Scenario: Overdue priority maintenance
- **WHEN** priority maintenance last ran 300 minutes ago
- **THEN** its status is `overdue` and one warning is reported
