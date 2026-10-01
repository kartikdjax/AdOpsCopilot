# Spec Delta

## MODIFIED Requirements

### Requirement: Sign-up creates a pending account
Sign-up SHALL be off unless the `ALLOW_SIGNUP` setting is on; while off, `POST /auth/signup` SHALL respond 403 and create nothing. When on, the API SHALL let anyone create an account with an email, a password of at least 8 characters and a display name, SHALL store the password only as a salted scrypt hash, and SHALL give every new account the role `pending` with no Revive manager.

#### Scenario: Sign-up disabled
- **WHEN** sign-up is off and a visitor posts to `/auth/signup`
- **THEN** the API responds 403 and creates no account

#### Scenario: New sign-up
- **WHEN** sign-up is on and a visitor signs up with a new email
- **THEN** the response returns the user with role `pending` and no agency
- **AND** a session cookie is set

#### Scenario: Duplicate email
- **WHEN** sign-up is on and a visitor signs up with an email that already has an account
- **THEN** the API responds 409 and creates no account

## ADDED Requirements

### Requirement: Operators create accounts from the server
`python -m src.api.manage_users add <email> --name <display name> --role <admin|manager|pending> [--agency-id <id>]` SHALL create an account with a generated password of at least 16 characters, print that password once, and store only its scrypt hash. It SHALL refuse an email that already has an account, and a manager role without a Revive manager id that exists.

#### Scenario: New account
- **WHEN** an operator adds a new email with role `admin`
- **THEN** the account exists with role `admin`, the printed password signs in, and the database holds no plain-text password

#### Scenario: Existing email
- **WHEN** an operator adds an email that already has an account
- **THEN** the command exits non-zero and the existing account is unchanged
