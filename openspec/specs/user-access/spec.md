# user-access Specification

## Purpose
Controls who can use the Copilot and which Revive data each user sees. Sign-up is open, but Revive access is granted only by an operator on the server, and a user's data scope is enforced by the tools themselves rather than trusted to the LLM.

## Requirements

### Requirement: Sign-up creates a pending account
The API SHALL let anyone create an account with an email, a password of at least 8 characters and a display name, SHALL store the password only as a salted scrypt hash, and SHALL give every new account the role `pending` with no Revive manager.

#### Scenario: New sign-up
- **WHEN** a visitor signs up with a new email
- **THEN** the response returns the user with role `pending` and no agency
- **AND** a session cookie is set

#### Scenario: Duplicate email
- **WHEN** a visitor signs up with an email that already has an account
- **THEN** the API responds 409 and creates no account

### Requirement: Roles are granted only from the server
Roles SHALL be changed only through the server-side command `python -m src.api.manage_users`. The web API SHALL expose no endpoint that changes a role. A role change SHALL take effect on the user's next request, without signing in again.

#### Scenario: Promotion applies on the next request
- **WHEN** an operator makes a signed-in pending user a manager of Revive manager 2
- **THEN** that user's next request is scoped to manager 2

### Requirement: Roles map to data scopes
The API SHALL derive a scope from the user's role on every request: `admin` sees all Revive data; `manager` with a Revive manager id sees only that manager's data; `pending`, or `manager` without a manager id, has no Revive access.

#### Scenario: Pending user asks a Revive question
- **WHEN** a pending user posts a Revive-mode message to `/chat`
- **THEN** the API responds 403 before any LLM or tool call

#### Scenario: Manager without a manager id
- **WHEN** a user has role `manager` and no agency id
- **THEN** the user has no Revive access

### Requirement: Scope travels as request metadata and fails closed
The orchestrator SHALL attach the user's scope to every MCP tool call as request metadata, never as a tool argument. No tool schema SHALL contain a scope, agency or context parameter. Revive tools SHALL refuse to run when a call carries no scope, and a scope SHALL be rejected when its role is unknown, a manager scope has no agency, or an admin scope names one.

#### Scenario: Call without a scope
- **WHEN** a Revive tool is called with no scope metadata
- **THEN** the tool returns an error saying the request carries no user scope

#### Scenario: Argument can't widen scope
- **WHEN** a manager-scoped call passes `agency_id` as a tool argument
- **THEN** the result is an error or the same value the manager scope returns

#### Scenario: Forged role
- **WHEN** scope metadata names a role other than `admin` or `manager`
- **THEN** the scope is rejected with a permission error

### Requirement: Manager scope limits every Revive tool
For a manager scope, every Revive tool SHALL return only that manager's advertisers, campaigns, banners, websites, zones, users and audit events, and SHALL NOT reveal platform administrators among the users with access to an object.

#### Scenario: Listing objects
- **WHEN** manager 2 lists zones
- **THEN** only zones on manager 2's websites are returned

#### Scenario: Totals partition the platform
- **WHEN** revenue is calculated for the admin scope and for each manager scope
- **THEN** the manager totals add up to the admin total

#### Scenario: Another manager's object
- **WHEN** manager 2 inspects a campaign that belongs to manager 1
- **THEN** the tool gives the same "not found" error as for an id that doesn't exist
