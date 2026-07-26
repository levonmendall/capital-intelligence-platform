# Capital Intelligence Production API

## Purpose

The API serves governed Capital Intelligence outputs without running a new market cycle, recalculating decisions, creating orders, or executing trades.

The active API applies one institutional objective: maximize long-term compounded portfolio returns. It does not expose individual investment goals, retirement targets, personalized required returns, risk preferences, or Personal CIO briefing routes.

## Run locally

```bash
uvicorn api.app:create_app --factory --host 0.0.0.0 --port 8000
```

Interactive OpenAPI documentation is available at `/docs`; the deterministic contract is available at `/openapi.json`.

## Public endpoints

```text
GET  /health
GET  /ready
POST /v1/auth/login
POST /v1/auth/refresh
```

`/health` proves only that the process is running. `/ready` checks required intelligence, portfolio, identity, alert, backup, and operational dependencies. Historical personal-goal databases are not runtime readiness dependencies.

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
GET  /v1/alerts/preferences
PUT  /v1/alerts/preferences
GET  /v1/alerts?limit=50&include_suppressed=false
POST /v1/alerts/{delivery_id}/acknowledge
```

Portfolio responses are filtered by mandate grants. Alert preferences and delivery history are scoped to the authenticated user. Unauthorized resource access returns `404` to avoid disclosing another user’s resources.

Investor Memory endpoints remain compatibility-only while historical records are migrated toward an institutional Decision Review Journal. They must not influence opportunity ranking, specialist analysis, CIO action, portfolio implementation, or alerts.

## Removed active routes

The following legacy route families are no longer registered in the production application:

```text
/v1/investment-policy/{investor_identifier}
/v1/goals/{investor_identifier}
/v1/personal-cio/{investor_identifier}
```

Historical storage and implementation modules may remain temporarily for migration and backward-compatible offline reads. New clients must not depend on them.

## Administrator endpoints

```text
GET  /v1/users
POST /v1/users
POST /v1/users/{user_id}/mandates
POST /v1/users/{user_id}/investor-access
POST /v1/users/{user_id}/disable
```

These routes manage authentication and data access. They do not create personalized investment objectives.

## Sessions

Login returns a short-lived opaque access token and a longer-lived opaque refresh token. Only hashes are stored. Refresh rotates and revokes the previous session. Logout and account disabling revoke active sessions.

```http
Authorization: Bearer ci_access_...
```

## Alerts

New users receive in-app delivery only and do not receive a daily summary unless they enable it. Material notifications rely on governed material-change results and user delivery preferences.

Alert eligibility and wording may reflect material changes in evidence, opportunity, risk, active theses, portfolio implementation, confidence, or CIO decisions. They must not depend on personal goals, target dates, preferred risk levels, or personalized investment philosophies.

## HTTP behavior

- `200` — valid response, including honestly labeled incomplete or stale output;
- `201` — administrator created a user;
- `204` — logout completed;
- `401` — credentials missing, invalid, expired, or revoked;
- `403` — authenticated user lacks a required administrative role;
- `404` — unknown, unauthorized, or deprecated/unregistered resource;
- `409` — immutable-resource conflict, invalid alert transition, or unavailable channel;
- `422` — invalid or out-of-policy parameters; and
- `503` — a required backing store is unavailable or not ready.

The API never upgrades stale or incomplete evidence to current and never infers missing objectives because objectives are not decision inputs.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CAPITAL_INTELLIGENCE_DATA_DIR` | `database` | Base directory for local stores. |
| `CAPITAL_INTELLIGENCE_SNAPSHOT_DATABASE` | `database/daily_intelligence_snapshots.db` | Canonical daily snapshot history. |
| `CAPITAL_INTELLIGENCE_PORTFOLIO_DATABASE` | `database/capital_intelligence.db` | Authorized portfolio and paper data. |
| `CAPITAL_INTELLIGENCE_INVESTOR_MEMORY_DATABASE` | `database/investor_memory.db` | Compatibility-only historical review records. |
| `CAPITAL_INTELLIGENCE_IDENTITY_DATABASE` | `database/identity.db` | Users, grants, sessions, and authentication audit. |
| `CAPITAL_INTELLIGENCE_ALERT_DATABASE` | `database/alerts.db` | Preferences, cycle claims, delivery records, and attempts. |
| `CAPITAL_INTELLIGENCE_JOURNAL_DATABASE` | `database/institutional_journal.db` | Institutional decision journal. |
| `CAPITAL_INTELLIGENCE_REPLAY_DIRECTORY` | `database/decision_replays` | Immutable Decision Replay artifacts. |
| `CAPITAL_INTELLIGENCE_AUTHENTICATION_REQUIRED` | `true` | Require authenticated application access. |
| `CAPITAL_INTELLIGENCE_ACCESS_TOKEN_MINUTES` | `15` | Access-session lifetime. |
| `CAPITAL_INTELLIGENCE_REFRESH_TOKEN_DAYS` | `30` | Refresh-session lifetime. |
| `CAPITAL_INTELLIGENCE_PASSWORD_MINIMUM_LENGTH` | `12` | Password minimum length. |
| `CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_EMAIL` | unset | Initial administrator email. |
| `CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_PASSWORD` | unset | Initial administrator password. |
| `CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE` | `America/New_York` | Scheduled market-date timezone. |
| `CAPITAL_INTELLIGENCE_SCHEDULER_HOUR` | `7` | Local daily cycle hour. |
| `CAPITAL_INTELLIGENCE_SCHEDULER_POLL_SECONDS` | `60` | Worker polling interval. |
| `CAPITAL_INTELLIGENCE_ALERT_MAXIMUM_ATTEMPTS` | `4` | Maximum delivery attempts. |
| `CAPITAL_INTELLIGENCE_ALERT_RETRY_MINUTES` | `5` | Base retry delay. |
| `CAPITAL_INTELLIGENCE_SMTP_HOST` | unset | SMTP host; unset disables email. |
| `CAPITAL_INTELLIGENCE_SMTP_PORT` | `587` | SMTP port. |
| `CAPITAL_INTELLIGENCE_SMTP_FROM_ADDRESS` | unset | Required sender when SMTP is enabled. |
| `CAPITAL_INTELLIGENCE_REQUIRE_JOURNAL` | `false` | Require journal readiness. |
| `CAPITAL_INTELLIGENCE_REQUIRE_LIVE_PROVIDER` | `false` | Require live FRED credentials. |
| `CAPITAL_INTELLIGENCE_ALLOWED_ORIGINS` | empty | Explicit CORS origins. |
| `CAPITAL_INTELLIGENCE_HISTORY_DEFAULT_LIMIT` | `30` | Default history page size. |
| `CAPITAL_INTELLIGENCE_HISTORY_MAX_LIMIT` | `100` | Maximum history page size. |
| `CAPITAL_INTELLIGENCE_API_NAME` | `Capital Intelligence API` | OpenAPI service name. |
| `CAPITAL_INTELLIGENCE_API_VERSION` | `1.3.0` | OpenAPI service version. |

## Security boundary

- Passwords use scrypt and are never stored in plaintext.
- Access and refresh tokens are stored only as hashes and are revocable.
- Authentication audit and delivery-attempt history are append-only.
- Portfolio, compatibility review records, preferences, and alerts are enforced server-side.
- Market and portfolio repositories remain read-only/query-only through the production API.
- No trade or allocation mutation route exists.
- Responses include defensive no-store, frame, referrer, and content-type headers.
- CORS is disabled unless explicit origins are configured.
- Unavailable stores produce safe `503` responses rather than stack traces.