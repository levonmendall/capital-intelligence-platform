# Authentication and mandate authorization

## Purpose

Capital Intelligence now treats identity and authorization as service and
repository concerns rather than interface visibility. Authentication is required
by default when the API or secured Streamlit application loads settings from the
environment.

Only `/health`, `/ready`, API documentation, login, and refresh are public. All
intelligence, replay, personal-memory, and portfolio routes require a revocable
access session.

## Run securely

Configure the first administrator before the first API or Streamlit start:

```bash
export CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_EMAIL="admin@example.com"
export CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_PASSWORD="replace-with-a-long-random-password"
export CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_NAME="Platform Administrator"
```

Run the API:

```bash
uvicorn api.app:create_app --factory --host 0.0.0.0 --port 8000
```

Run the authenticated Streamlit entrypoint:

```bash
streamlit run secure_app.py
```

The bootstrap password is used only to create the initial account when the email
does not exist. Remove the bootstrap password from the runtime environment after
the account is created.

## Credentials and sessions

Passwords use the standard-library scrypt password KDF with a unique random
salt. The database never stores a plaintext password.

Access and refresh credentials are opaque, high-entropy values. The database
stores only their SHA-256 hashes. Access sessions default to 15 minutes and
refresh sessions default to 30 days. Refresh rotates both credentials and
revokes the previous session. Logout and account disabling revoke sessions.

```text
POST /v1/auth/login
POST /v1/auth/refresh
POST /v1/auth/logout
GET  /v1/auth/me
```

## Roles

- `investor` — views assigned mandates and their own Investor Memory;
- `advisor` — views assigned mandates and explicitly granted investor profiles;
- `auditor` — read-only access across mandates and investor profiles;
- `administrator` — user provisioning, access grants, disabling, and all reads.

Roles do not replace resource grants. Investors and advisors receive explicit
mandate grants. Advisor access to another investor's memory is also explicit.

## Mandate grants

A mandate grant has one of two permissions:

- `view` — read mandate holdings, trades, valuation history, and opportunity cost;
- `manage` — reserved for future authenticated mandate mutations.

Unauthorized mandate detail returns `404` to avoid disclosing that another
investor's mandate exists. Portfolio lists contain only authorized mandates.

Administrator routes:

```text
GET  /v1/users
POST /v1/users
POST /v1/users/{user_id}/mandates
POST /v1/users/{user_id}/investor-access
POST /v1/users/{user_id}/disable
```

## Investor Memory grants

An investor can read and record reflections for their own immutable investor
identifier. Advisors require an explicit `view` or `reflect` grant. Auditors may
read but not write. Administrators may access all profiles.

The production API remains read-only for Investor Memory in this PR. The secured
Streamlit entrypoint records reflections only after checking the authenticated
principal's write permission.

## Audit history

The identity database records user creation, role grants, mandate grants,
investor grants, login attempts, refreshes, logout, and account disabling.
Database triggers reject updates and deletes from the authentication audit table.
Sensitive credentials and password material are never included in audit detail.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CAPITAL_INTELLIGENCE_IDENTITY_DATABASE` | `database/identity.db` | Users, grants, sessions, and authentication audit. |
| `CAPITAL_INTELLIGENCE_AUTHENTICATION_REQUIRED` | `true` | Require authenticated API and Streamlit access. |
| `CAPITAL_INTELLIGENCE_ACCESS_TOKEN_MINUTES` | `15` | Access-session lifetime. |
| `CAPITAL_INTELLIGENCE_REFRESH_TOKEN_DAYS` | `30` | Refresh-session lifetime. |
| `CAPITAL_INTELLIGENCE_PASSWORD_MINIMUM_LENGTH` | `12` | Minimum password length. |
| `CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_EMAIL` | unset | Initial administrator email. |
| `CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_PASSWORD` | unset | Initial administrator password. |
| `CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_NAME` | `Platform Administrator` | Initial display name. |

Directly constructed `ApiSettings()` instances default authentication off for
isolated legacy contract fixtures. Environment-loaded runtime settings default it
on. Production code should use `ApiSettings.from_env()` or the application
factory without explicit settings.

## Security boundaries

- Authorization is enforced by FastAPI dependencies and resource-aware routes.
- The Streamlit compatibility entrypoint scopes legacy reads before loading the
  existing four-screen application.
- Tokens are revocable and are not self-contained bearer claims.
- Disabled users cannot log in, refresh, or continue an existing session.
- Cross-investor and cross-mandate requests do not reveal resource existence.
- This PR does not add trade execution or portfolio mutation routes.
