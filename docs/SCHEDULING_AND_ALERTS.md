# Canonical Scheduling and Selective Delivery

## Scheduled investment authority

The active worker executes `CanonicalCIOCycle`. It does not run the retired daily snapshot, economic-regime pipeline, analytical-engine synthesis, weighted committee, score, or conviction-trend process.

For each configured market date the worker:

1. derives and atomically claims one durable `canonical-cio` cycle key;
2. loads the point-in-time context from the configured factory;
3. loads candidates only from the matching complete-universe screening publication;
4. executes opportunity ranking, five independent specialist reviews, CIO synthesis, portfolio construction, thesis creation, evidence freezing, and the daily briefing;
5. stores the briefing identifier on the completed claim; and
6. drains independently queued delivery events.

Any missing configuration, incomplete screening evidence, mismatched timestamp, or integrity failure blocks the cycle and records a retryable failure. There is no legacy fallback.

## Run the worker

```bash
export CAPITAL_INTELLIGENCE_CANONICAL_CONTEXT_PROVIDER=production_context:create_provider
python run_scheduler.py
```

One pass:

```bash
python run_scheduler.py --once
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CAPITAL_INTELLIGENCE_FULL_UNIVERSE_SCREENING_DATABASE` | `database/full_universe_screening.db` | Immutable complete-universe publications consumed by the CIO executor. |
| `CAPITAL_INTELLIGENCE_CANONICAL_CONTEXT_PROVIDER` | none | Required `module:function` context-provider factory. |
| `CAPITAL_INTELLIGENCE_ALERT_DATABASE` | `database/alerts.db` | Durable cycle claims and delivery operations. |
| `CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE` | `America/New_York` | Market-date boundary. |
| `CAPITAL_INTELLIGENCE_SCHEDULER_HOUR` | `7` | Local scheduled hour. |
| `CAPITAL_INTELLIGENCE_SCHEDULER_POLL_SECONDS` | `60` | Worker polling interval. |
| `CAPITAL_INTELLIGENCE_SCHEDULER_RETRY_MINUTES` | `15` | Failed-cycle retry delay. |
| `CAPITAL_INTELLIGENCE_SCHEDULER_LEASE_MINUTES` | `30` | Running-claim lease. |

## Safety boundaries

- Scheduling cannot create candidates outside the complete screening publication.
- Context providers cannot issue CIO actions or alter the candidate set.
- Portfolio actions remain proposals until the governed paper-execution boundary.
- Delivery cannot change investment decisions.
- Cycle claims are idempotent and failures remain auditable.
