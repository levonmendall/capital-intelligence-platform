# Capital Intelligence Production API

## Purpose

The API serves previously governed Capital Intelligence outputs without running
a new market cycle, recalculating a score, creating orders, or executing trades.
Authentication, users, and resource grants now protect the production boundary.

The primary market contract remains `daily-capital-intelligence.v1`. Clients
receive the same score, environment, committee decision, portfolio impact,
operating status, source identifiers, and replay references used by the
Streamlit application.

## Run locally

Configure an initial administrator as described in
[Authentication and mandate authorization](AUTHENTICATION_AND_AUTHORIZATION.md),
then run:

```bash
uvicorn api.app:create_app --factory --host 0.0.0.0 --port 8000
```

Interactive OpenAPI documentation is available at `/docs`; the deterministic
OpenAPI document is available at `/openapi.json`.

## Public endpoints

```text
GET  /health
GET  /ready
POST /v1/auth/login
POST /v1/auth/refresh
```

`/health` proves only that the process is running. `/ready` checks daily
snapshots, portfolios, identity, optional replay artifacts, the optional or
required institutional journal, and optional or required provider credentials.
A secured runtime is not ready until at least one user exists.

## Authenticated endpoints

```text
POST /v1/auth/logout
GET  /v1/auth/me
GET  /v1/daily/latest
GET  /v1/daily/history?limit=30&offset=0
GET  /v1/environment/latest
GET  /v1/decisions/{decision_identifier}
GET  /v1/replays
GET  /v1/replays/{replay_identifier}
GET  /v1/portfolios
GET  /v1/portfolios/{portfolio_code}
GET  /v1/conviction/latest?lookback=7
GET  /v1/investor-memory/{investor_identifier}
GET  /v1/investor-memory/{investor_identifier}/events?limit=50
```

Portfolio list and detail responses are filtered by mandate grants. Investor
Memory requires ownership or an explicit investor-profile grant. Unauthorized
resource access returns `404` to avoid disclosing another user's resources.

## Administrator endpoints

```text
GET  /v1/users
POST /v1/users
POST /v1/users/{user_id}/mandates
POST /v1/users/{user_id}/investor-access
POST /v1/users/{user_id}/disable
```

These endpoints require the `administrator` role. They never return password
hashes, session hashes, or credentials.

## Sessions

Login returns a short-lived opaque access token and a longer-lived opaque
refresh token. Only hashes are stored. Refresh rotates and revokes the previous
session. Logout and account disabling revoke active sessions.

Use the access credential as:

```http
Authorization: Bearer ci_access_...
```

## Personal CIO

Conviction reads canonical daily snapshot history without rerunning analysis.
Investor Memory remains read-only through the API in PR23. Authenticated
reflection writes are available through the secured Streamlit boundary and are
restricted to the investor's own identity or an explicit `reflect` grant.

A missing authorized memory store returns an empty profile, not an invented
preference.

## HTTP behavior

- `200` — a valid response, including an honestly labeled incomplete or stale
  daily snapshot;
- `201` — an administrator created a user;
- `204` — logout completed;
- `401` — credentials are missing, invalid, expired, or revoked;
- `403` — the user is authenticated but lacks a required administrative role;
- `404` — an unknown or unauthorized decision, replay, investor, or mandate;
- `409` — an immutable identity or replay identifier conflicts;
- `422` — invalid or out-of-policy request parameters; and
- `503` — a required backing store is unavailable or not ready.

The API never upgrades stale or incomplete data to a current state.

## Configuration

All paths are relative to the process working directory unless absolute paths
are supplied.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CAPITAL_INTELLIGENCE_DATA_DIR` | `database` | Base directory for local stores. |
| `CAPITAL_INTELLIGENCE_SNAPSHOT_DATABASE` | `database/daily_intelligence_snapshots.db` | Canonical daily snapshot history. |
| `CAPITAL_INTELLIGENCE_PORTFOLIO_DATABASE` | `database/capital_intelligence.db` | Virtual mandate and portfolio data. |
| `CAPITAL_INTELLIGENCE_INVESTOR_MEMORY_DATABASE` | `database/investor_memory.db` | Append-only investor behavior and lessons. |
| `CAPITAL_INTELLIGENCE_IDENTITY_DATABASE` | `database/identity.db` | Users, grants, sessions, and authentication audit. |
| `CAPITAL_INTELLIGENCE_JOURNAL_DATABASE` | `database/institutional_journal.db` | Institutional journal readiness target. |
| `CAPITAL_INTELLIGENCE_REPLAY_DIRECTORY` | `database/decision_replays` | Immutable Decision Replay artifacts. |
| `CAPITAL_INTELLIGENCE_AUTHENTICATION_REQUIRED` | `true` | Require authenticated application access. |
| `CAPITAL_INTELLIGENCE_ACCESS_TOKEN_MINUTES` | `15` | Access-session lifetime. |
| `CAPITAL_INTELLIGENCE_REFRESH_TOKEN_DAYS` | `30` | Refresh-session lifetime. |
| `CAPITAL_INTELLIGENCE_PASSWORD_MINIMUM_LENGTH` | `12` | Password minimum length. |
| `CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_EMAIL` | unset | Initial administrator email. |
| `CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_PASSWORD` | unset | Initial administrator password. |
| `CAPITAL_INTELLIGENCE_REQUIRE_JOURNAL` | `false` | Require journal readiness. |
| `CAPITAL_INTELLIGENCE_REQUIRE_LIVE_PROVIDER` | `false` | Require `FRED_API_KEY`. |
| `CAPITAL_INTELLIGENCE_ALLOWED_ORIGINS` | empty | Comma-separated CORS origins. |
| `CAPITAL_INTELLIGENCE_HISTORY_DEFAULT_LIMIT` | `30` | Default history page size. |
| `CAPITAL_INTELLIGENCE_HISTORY_MAX_LIMIT` | `100` | Maximum history page size. |
| `CAPITAL_INTELLIGENCE_CONVICTION_DEFAULT_LOOKBACK` | `7` | Default conviction observations. |
| `CAPITAL_INTELLIGENCE_CONVICTION_MAX_LOOKBACK` | `30` | Maximum conviction observations. |
| `CAPITAL_INTELLIGENCE_API_NAME` | `Capital Intelligence API` | OpenAPI service name. |
| `CAPITAL_INTELLIGENCE_API_VERSION` | `1.2.0` | OpenAPI service version. |

## Replay artifacts

Replay filenames are not treated as identifiers. The API scans each payload and
uses its immutable `identifier`. Duplicate identifiers with different content
return a conflict instead of silently selecting one version.

## Security boundary

- Passwords use scrypt and are never stored in plaintext.
- Access and refresh tokens are stored only as hashes and are revocable.
- Authentication audit history is append-only.
- Portfolio and Investor Memory authorization is enforced server-side.
- SQLite market and portfolio repositories remain read-only/query-only in the
  production API.
- No trade or allocation mutation route exists.
- Responses include no-store, frame-denial, referrer, and content-type headers.
- CORS is disabled unless explicit origins are configured.
- Unavailable stores produce safe HTTP 503 responses rather than stack traces.
