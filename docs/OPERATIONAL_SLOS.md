# Operational Service-Level Objectives

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

The operational SLO layer measures whether the production process required to uphold that rule is running on time. It has no investment authority: it cannot create or alter a recommendation, change portfolio sizing, upgrade incomplete evidence, or rewrite a thesis.

## Versioned policy

`operational-slo.v1` defines four objectives:

| Objective | Default | Required production evidence |
|---|---:|---|
| Authoritative provider freshness | 36 hours | Activated security-master catalog, catalog-chain integrity, operations-chain integrity, and source age |
| Full-universe cycle completion | 120 minutes after the 7:00 a.m. America/New_York weekday schedule | Terminal cycle record using the active catalog, an immutable universe snapshot, and 100% eligible-instrument screening coverage |
| Living-thesis review latency | 24 hours after `next_review_at` | Latest point-in-time thesis snapshots from the canonical CIO journal |
| Decision-evaluation latency | 48 hours after the frozen decision horizon ends | Decision-evidence snapshots and matching evaluation events from the canonical CIO journal |

All thresholds are environment configurable. A deadline is inclusive: completion exactly at the deadline is compliant, and breach begins after the deadline.

## States

- `met` — the required process completed within policy.
- `pending` — the expected process has not completed but its deadline has not passed.
- `breached` — timing, completeness, consistency, or integrity failed.
- `blocked` — an authoritative prerequisite is unavailable.
- `not_applicable` — no qualifying thesis or decision currently exists.

Only `met`, `pending`, and `not_applicable` are readiness-compatible. Required `blocked` or `breached` objectives return HTTP 503 from `/ready` and `/operations/slo`.

## Append-only evidence

`SQLiteOperationalSLOStore` retains two independent SHA-256 chains:

- terminal full-universe cycle records; and
- point-in-time SLO assessments.

Database triggers prevent update and delete operations. Reusing an identifier with different content is rejected. Assessment history is evidence of operational performance; it never modifies policy automatically.

## Interfaces

```bash
python run_slos.py
python run_slos.py --record-assessment --require-ready
```

The governed screening orchestrator appends terminal full-universe cycle evidence automatically. Completed cycles require the certified active catalog identifier, immutable universe-snapshot identifier, exact eligible and screened counts, and a persisted atomic publication. Failed cycles require an explicit error and produce no CIO candidate or opportunity-queue evidence. The SLO CLI can append independently verified terminal evidence for administrative recovery, but it is not the normal production screening path.

```text
GET /operations/slo
GET /ready
GET /metrics
```

`/operations/slo` and `/metrics` use the metrics bearer token when configured. Prometheus metrics expose overall readiness, per-objective readiness and state, actual values, and thresholds.

## Production configuration

```text
CAPITAL_INTELLIGENCE_REQUIRE_OPERATIONAL_SLOS=true
CAPITAL_INTELLIGENCE_SECURITY_MASTER_DATABASE=database/security_master.db
CAPITAL_INTELLIGENCE_OPERATIONAL_SLO_DATABASE=database/operational_slos.db
CAPITAL_INTELLIGENCE_SLO_PROVIDER_MAXIMUM_AGE_HOURS=36
CAPITAL_INTELLIGENCE_SLO_SCREENING_TIMEZONE=America/New_York
CAPITAL_INTELLIGENCE_SLO_SCREENING_HOUR=7
CAPITAL_INTELLIGENCE_SLO_SCREENING_DEADLINE_MINUTES=120
CAPITAL_INTELLIGENCE_SLO_THESIS_REVIEW_GRACE_HOURS=24
CAPITAL_INTELLIGENCE_SLO_EVALUATION_GRACE_HOURS=48
```

Production settings require SLO enforcement. Development, test, and staging may keep the component advisory while building the licensed data and full-universe operating history.

Thesis-review SLO evidence is normally produced automatically by `run_thesis_monitoring.py`, which appends a later immutable thesis snapshot after every successful scheduled or event-driven review. A stable no-action review is valid SLO completion and does not require a user notification.
