# Scheduled Daily Intelligence and Selective Alert Delivery

## Purpose

The scheduler runs the governed Capital Intelligence process every configured
market day while keeping notification separate from analysis. Every due cycle is
recorded. Users are notified only when the existing material-change policy says
the portfolio warrants review, or when the user explicitly enables a daily
summary.

## Operating model

The persistent worker:

1. resolves one scheduled cycle key from the configured market timezone and date;
2. atomically claims that cycle in SQLite;
3. runs the canonical daily intelligence service once;
4. stores the daily snapshot through the existing append-only snapshot store;
5. evaluates the governed material-change result against each active user's
   preferences;
6. records suppressed, pending, sent, failed, and acknowledged delivery states;
7. dispatches in-app alerts immediately and email only when SMTP is configured;
8. retries failed delivery with bounded exponential backoff; and
9. marks the cycle complete without creating duplicate alerts on retries.

The first cycle after a cold worker start establishes a comparison baseline and
remains silent unless a user has opted into a daily summary. The persistent
worker then retains the prior governed run and decision for the next material
comparison.

## Run the worker

```bash
python run_scheduler.py
```

Run one due-cycle and delivery pass for cron, diagnostics, or a deployment smoke
test:

```bash
python run_scheduler.py --once
```

The long-running worker is the recommended production mode because it preserves
the previous governed cycle in memory for the next material-change comparison.
PR25 should supervise it as a separate service.

## Default behavior

New users default to:

- in-app delivery only;
- no daily summary;
- material risk, environment, committee, portfolio, conviction, and data-quality
  topics enabled;
- a five-point minimum conviction change; and
- an 8:00 AM local preference.

Email is never enabled by default. A user cannot enable email through the API or
Streamlit unless the runtime has a configured SMTP host and sender address.

## Authenticated API

```text
GET  /v1/alerts/preferences
PUT  /v1/alerts/preferences
GET  /v1/alerts?limit=50&include_suppressed=false
POST /v1/alerts/{delivery_id}/acknowledge
```

All routes are scoped to the authenticated user. A user cannot list or
acknowledge another user's alerts. Suppressed records are hidden by default but
can be requested for auditing.

## Delivery states

- `pending` — queued or awaiting its next retry;
- `sent` — available in-app or accepted by the configured email adapter;
- `failed` — exhausted the bounded retry policy;
- `suppressed` — analysis completed, but no enabled topic warranted delivery;
- `acknowledged` — the user marked a sent in-app alert as reviewed.

Every delivery attempt is written to an append-only attempt table. Delivery
records themselves remain mutable only for operational state transitions.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CAPITAL_INTELLIGENCE_ALERT_DATABASE` | `database/alerts.db` | Preferences, cycle claims, delivery records, and attempts. |
| `CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE` | `America/New_York` | Market-date boundary and scheduled hour timezone. |
| `CAPITAL_INTELLIGENCE_SCHEDULER_HOUR` | `7` | Daily local execution hour, 0–23. |
| `CAPITAL_INTELLIGENCE_SCHEDULER_POLL_SECONDS` | `60` | Persistent worker polling interval. |
| `CAPITAL_INTELLIGENCE_SCHEDULER_RETRY_MINUTES` | `15` | Failed cycle retry delay. |
| `CAPITAL_INTELLIGENCE_SCHEDULER_LEASE_MINUTES` | `30` | Running-cycle claim lease. |
| `CAPITAL_INTELLIGENCE_ALERT_MAXIMUM_ATTEMPTS` | `4` | Maximum channel delivery attempts. |
| `CAPITAL_INTELLIGENCE_ALERT_RETRY_MINUTES` | `5` | Base delivery retry delay. |
| `CAPITAL_INTELLIGENCE_SMTP_HOST` | empty | SMTP server; empty disables email. |
| `CAPITAL_INTELLIGENCE_SMTP_PORT` | `587` | SMTP port. |
| `CAPITAL_INTELLIGENCE_SMTP_USERNAME` | empty | Optional SMTP username. |
| `CAPITAL_INTELLIGENCE_SMTP_PASSWORD` | empty | Optional SMTP password. |
| `CAPITAL_INTELLIGENCE_SMTP_FROM_ADDRESS` | empty | Required sender address when SMTP is enabled. |
| `CAPITAL_INTELLIGENCE_SMTP_USE_TLS` | `true` | StartTLS for SMTP delivery. |

## Safety boundaries

- Scheduling never executes a trade or changes a portfolio.
- A score movement alone does not bypass material-change policy.
- Daily summaries require explicit opt-in.
- Email requires explicit user selection and runtime configuration.
- Cycle claims and delivery deduplication prevent repeated notifications.
- In-app alerts and preferences are scoped to authenticated users.
- Unchanged conditions create an auditable suppression record rather than a
  noisy notification.
