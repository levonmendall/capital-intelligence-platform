# Capital Intelligence Production API

## Purpose

The production API is a read-only boundary over previously governed Capital
Intelligence outputs. It does not run a new market cycle, recalculate a score,
seed a portfolio, alter history, create orders, or execute trades.

The primary contract is the existing `daily-capital-intelligence.v1` snapshot.
Clients receive the same score, environment, committee decision, portfolio
impact, operating status, source identifiers, and replay references used by the
Streamlit application.

## Run locally

```bash
uvicorn api.app:create_app --factory --host 0.0.0.0 --port 8000
```

Interactive OpenAPI documentation is available at `/docs`; the deterministic
OpenAPI document is available at `/openapi.json`.

## Version 1 endpoints

```text
GET /health
GET /ready
GET /v1/daily/latest
GET /v1/daily/history?limit=30&offset=0
GET /v1/environment/latest
GET /v1/decisions/{decision_identifier}
GET /v1/replays
GET /v1/replays/{replay_identifier}
GET /v1/portfolios
GET /v1/portfolios/{portfolio_code}
GET /v1/conviction/latest?lookback=7
GET /v1/investor-memory/{investor_identifier}
GET /v1/investor-memory/{investor_identifier}/events?limit=50
```

There are no POST, PUT, PATCH, or DELETE application routes in Version 1.

## Health and readiness

`/health` proves only that the API process is running.

`/ready` checks the configured dependencies separately:

- append-only daily snapshot database;
- portfolio database;
- optional replay artifact directory;
- optional or required institutional journal; and
- optional or required live-provider credentials.

A missing required dependency returns HTTP 503. Optional dependencies are
reported but do not prevent readiness.

## Personal CIO

Conviction reads canonical daily snapshot history without rerunning analysis.
Investor Memory is read-only through the API; reflection writes remain inside
the trusted application boundary until authentication and investor-level
authorization are available. A missing memory store returns an empty profile,
not an invented preference.

## HTTP behavior

- `200` — a valid response, including an honestly labeled incomplete or stale
  daily snapshot;
- `404` — an unknown snapshot-backed decision, replay, or portfolio;
- `409` — the same immutable replay identifier resolves to conflicting
  artifacts;
- `422` — invalid or out-of-policy request parameters; and
- `503` — a required backing store is unavailable or corrupt.

The API never upgrades stale or incomplete data to a current state.

## Configuration

All paths are relative to the process working directory unless absolute paths
are supplied.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CAPITAL_INTELLIGENCE_DATA_DIR` | `database` | Base directory for local stores. |
| `CAPITAL_INTELLIGENCE_SNAPSHOT_DATABASE` | `database/daily_intelligence_snapshots.db` | Canonical daily snapshot history. |
| `CAPITAL_INTELLIGENCE_PORTFOLIO_DATABASE` | `database/capital_intelligence.db` | Virtual mandate and portfolio data. |
| `CAPITAL_INTELLIGENCE_INVESTOR_MEMORY_DATABASE` | `database/investor_memory.db` | Append-only explicit investor behavior and lessons. |
| `CAPITAL_INTELLIGENCE_JOURNAL_DATABASE` | `database/institutional_journal.db` | Institutional journal readiness target. |
| `CAPITAL_INTELLIGENCE_REPLAY_DIRECTORY` | `database/decision_replays` | Immutable Decision Replay JSON artifacts. Empty disables the directory. |
| `CAPITAL_INTELLIGENCE_REQUIRE_JOURNAL` | `false` | Make journal availability required for readiness. |
| `CAPITAL_INTELLIGENCE_REQUIRE_LIVE_PROVIDER` | `false` | Require `FRED_API_KEY` for readiness. |
| `CAPITAL_INTELLIGENCE_ALLOWED_ORIGINS` | empty | Comma-separated CORS origins. |
| `CAPITAL_INTELLIGENCE_HISTORY_DEFAULT_LIMIT` | `30` | Default history page size. |
| `CAPITAL_INTELLIGENCE_HISTORY_MAX_LIMIT` | `100` | Maximum history page size. |
| `CAPITAL_INTELLIGENCE_CONVICTION_DEFAULT_LOOKBACK` | `7` | Default conviction trend observations. |
| `CAPITAL_INTELLIGENCE_CONVICTION_MAX_LOOKBACK` | `30` | Maximum conviction trend observations. |
| `CAPITAL_INTELLIGENCE_API_NAME` | `Capital Intelligence API` | OpenAPI service name. |
| `CAPITAL_INTELLIGENCE_API_VERSION` | `1.1.0` | OpenAPI service version. |

## Replay artifacts

Replay artifacts are read from JSON files in the configured replay directory.
The filename is not treated as an identifier; the API scans the payload and
uses its immutable `identifier` field. Duplicate identifiers with different
content are rejected as a conflict. This prevents path traversal and avoids
silently selecting one version of inconsistent history.

A replay identifier can appear in daily snapshot history before its full
artifact is available. The replay list marks each reference with an `available`
flag so clients can distinguish an audit reference from a retrievable replay.

## Security boundary

- SQLite databases are opened in read-only and query-only modes.
- Investor Memory reads are explicit; the API does not infer preferences from
  unrelated activity.
- Portfolio reads do not initialize or seed the database.
- No trade or allocation mutation route exists.
- Responses include no-store and defensive browser headers.
- CORS is disabled unless explicit origins are configured.
- Runtime exceptions from unavailable stores are converted to safe HTTP 503
  responses rather than leaking stack traces.
