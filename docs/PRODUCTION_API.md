# Capital Intelligence Production API

## Purpose

The API serves persisted, governed Capital Intelligence records. It does not run a new market cycle, rerank candidates, rescore evidence, create orders, or execute trades.

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

The primary read boundary is the append-only CIO journal.

## Run locally

```bash
uvicorn api.app:create_app --factory --host 0.0.0.0 --port 8000
```

OpenAPI is available at `/docs` and `/openapi.json`.

## Canonical CIO endpoints

```text
GET /v1/cio/latest
GET /v1/cio/history?limit=30&offset=0
GET /v1/cio/decisions/latest
GET /v1/cio/construction/latest
GET /v1/cio/evidence/latest
GET /v1/cio/evaluations/latest
GET /v1/cio/theses?limit=100
GET /v1/cio/process
```

The endpoints return persisted payloads plus journal metadata:

- event sequence;
- event and aggregate identifiers;
- event type;
- occurrence and recording timestamps;
- schema version; and
- tamper-evident content hash.

The API opens the journal in query-only mode. It returns `404` rather than constructing synthetic decisions, evidence, evaluations, theses, or briefings.

## Other authenticated endpoints

```text
POST /v1/auth/logout
GET  /v1/auth/me
GET  /v1/environment/latest
GET  /v1/replays
GET  /v1/replays/{replay_identifier}
GET  /v1/portfolios
GET  /v1/portfolios/{portfolio_code}
GET  /v1/alerts/preferences
PUT  /v1/alerts/preferences
GET  /v1/alerts?limit=50&include_suppressed=false
POST /v1/alerts/{delivery_id}/acknowledge
```

Portfolio responses remain filtered by mandate grants. Alerts remain scoped to the authenticated user and may reflect material evidence, opportunity, risk, thesis, implementation, confidence, or CIO-decision changes.

## Deprecated diagnostics

`/v1/daily/*` and legacy snapshot-decision/replay records remain available only as explicitly deprecated diagnostic or audit surfaces. They are not recommendation authority, and clients should migrate to `/v1/cio/*`.

## Unregistered legacy routes

The production application does not register:

```text
/v1/personal-cio/*
/v1/investor-memory/*
/v1/conviction/*
/v1/goals/*
/v1/investment-policy/*
```

Historical stores or implementation modules may remain temporarily for migration and offline research. Identity grants cannot reactivate an unregistered route.

## Public and administrator endpoints

Public:

```text
GET  /health
GET  /ready
POST /v1/auth/login
POST /v1/auth/refresh
```

Administrator:

```text
GET  /v1/users
POST /v1/users
POST /v1/users/{user_id}/mandates
POST /v1/users/{user_id}/investor-access
POST /v1/users/{user_id}/disable
```

User and mandate administration controls access only. It does not create personalized investment objectives.

## HTTP behavior

- `200` — valid persisted response;
- `201` — administrator created a resource;
- `204` — logout or acknowledgement completed;
- `401` — missing, invalid, expired, or revoked credentials;
- `403` — authenticated identity lacks administrative authority;
- `404` — unknown, unauthorized, absent canonical, deprecated, or unregistered resource;
- `409` — immutable-resource or delivery-state conflict;
- `422` — invalid parameters; and
- `503` — a required backing store is unavailable.

## Security boundary

- Passwords use scrypt and are never stored in plaintext.
- Access and refresh tokens are stored only as hashes and are revocable.
- Journal, authentication audit, and delivery-attempt histories are append-only.
- Journal and market/portfolio repositories are read-only through the API.
- No allocation or broker mutation route exists.
- CORS is disabled unless explicit origins are configured.
- Defensive no-store, frame, referrer, and content-type headers are installed.
- Unavailable stores fail safely rather than exposing stack traces or fabricated outputs.

## Key configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CAPITAL_INTELLIGENCE_DATA_DIR` | `database` | Base storage directory. |
| `CAPITAL_INTELLIGENCE_JOURNAL_DATABASE` | `database/institutional_journal.db` | Canonical append-only CIO journal. |
| `CAPITAL_INTELLIGENCE_SNAPSHOT_DATABASE` | `database/daily_intelligence_snapshots.db` | Deprecated diagnostic snapshots. |
| `CAPITAL_INTELLIGENCE_PORTFOLIO_DATABASE` | `database/capital_intelligence.db` | Authorized paper portfolios. |
| `CAPITAL_INTELLIGENCE_IDENTITY_DATABASE` | `database/identity.db` | Users, grants, and sessions. |
| `CAPITAL_INTELLIGENCE_ALERT_DATABASE` | `database/alerts.db` | Preferences and delivery history. |
| `CAPITAL_INTELLIGENCE_REQUIRE_JOURNAL` | `false` | Require journal readiness. |
| `CAPITAL_INTELLIGENCE_AUTHENTICATION_REQUIRED` | `true` | Require authentication. |
| `CAPITAL_INTELLIGENCE_ALLOWED_ORIGINS` | empty | Explicit CORS origins. |
| `CAPITAL_INTELLIGENCE_HISTORY_DEFAULT_LIMIT` | `30` | Default history page size. |
| `CAPITAL_INTELLIGENCE_HISTORY_MAX_LIMIT` | `100` | Maximum history page size. |
