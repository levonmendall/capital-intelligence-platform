# Canonical Daily Operations

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

## Purpose

The canonical daily operations authority turns the repository's independently governed commands into one durable investment process. It coordinates stages; it does not perform analysis, discover securities, infer missing evidence, change rankings, issue recommendations, resize positions, or authorize live trading.

```text
Provider freshness and certification
        ↓
Security-master activation
        ↓
Certified eligible-universe publication
        ↓
Complete-universe screening
        ↓
Production context assembly
        ↓
Canonical CIO cycle
        ↓
Paper construction and execution
        ↓
Living-thesis monitoring
        ↓
Point-in-time outcome evaluation
        ↓
Paper-operation evidence review
        ↓
Canonical alert delivery
        ↓
Operational SLO assessment
```

A failed or unreconciled upstream stage prevents every downstream stage from starting. Incomplete screening therefore produces no CIO cycle and no paper activity.

## Durable stage contract

Every stage records:

- an operation-level and stage-level idempotency key;
- dependency input identifiers;
- canonical output identifiers;
- start and completion timestamps;
- one or more heartbeats;
- the exact point-in-time knowledge cutoff;
- the configured runner identity;
- retry attempts and backoff policy;
- typed failure classification;
- reconciliation status; and
- the stage's immutable detail record.

`SQLiteCanonicalDailyOperationsStore` keeps operation claims and a global append-only SHA-256 event chain. SQLite triggers prohibit updates and deletes. The idempotency claim prevents another operation identifier from reusing the same daily operation key.

## Stage order and failure behavior

`CANONICAL_DAILY_STAGE_ORDER` is the only active sequence. The orchestrator requires one runner for every stage and rejects missing or additional stages.

A successful stage must return at least one persisted output identifier. Its cutoff must exactly match the daily operation cutoff, and its reconciliation status must be `reconciled` or `not_applicable`. A mismatched cutoff, missing identifier, failed reconciliation, or invalid timestamp is a stage failure.

Failures are classified as:

- `transient_provider`;
- `data_quality`;
- `dependency`;
- `integrity`;
- `configuration`;
- `reconciliation`;
- `execution`;
- `interrupted`; or
- `unknown`.

Only failures explicitly marked retryable may consume another configured attempt. Exhausted or non-retryable failures append one failure record, block all downstream stages, and terminate the operation without investment activity.

## Command plan

`run_daily_operations.py` accepts a versioned JSON plan. The plan must configure every stage exactly once.

```json
{
  "schema_version": "canonical-daily-operations.v1",
  "identifier": "licensed-production-plan-v1",
  "stages": {
    "provider_certification": {
      "module": "run_provider_certification",
      "argv": ["--provider-factory", "licensed_provider:create_provider"],
      "output_fields": ["identifier"],
      "retryable_exit_codes": [4],
      "retry": {
        "maximum_attempts": 3,
        "initial_backoff_seconds": 30,
        "multiplier": 2,
        "maximum_backoff_seconds": 300
      }
    }
  }
}
```

The abbreviated example above is not a valid complete plan. A deployed plan must contain all twelve canonical stage names. Each command module must expose `main(argv)` and print one JSON object. `output_fields` are dotted paths to persisted identifiers in that output.

The runner substitutes these tokens in command arguments:

- `{operation_identifier}`;
- `{operation_idempotency_key}`;
- `{stage_idempotency_key}`;
- `{attempt}`;
- `{scheduled_for}`;
- `{decision_timestamp}`;
- `{knowledge_cutoff}`;
- `{portfolio_code}`;
- `{process_version}`;
- `{code_version}`; and
- `{input_identifiers_json}`.

Provider credentials and licensed data configuration remain deployment secrets. They are not stored in the plan committed to source control.

## Command

Run one operation:

```bash
python run_daily_operations.py \
  --plan /run/secrets/canonical-daily-operations.json \
  --operation-id canonical-daily:COMPOUNDING:2026-07-27 \
  --idempotency-key canonical-daily:COMPOUNDING:2026-07-27:process-v1 \
  --scheduled-for 2026-07-27T07:00:00-04:00 \
  --decision-timestamp 2026-07-27T07:00:00-04:00 \
  --knowledge-cutoff 2026-07-27T06:59:59-04:00
```

Run the durable daily loop:

```bash
python run_daily_operations.py --loop
```

The loop uses `CAPITAL_INTELLIGENCE_DAILY_OPERATION_PLAN`, the configured timezone and hour, and one date-based idempotency key. Repeated polling cannot create duplicate daily operations.

## Deployment boundary

The deployment scheduler runs this orchestrator instead of the CIO-only worker. The orchestrator deliberately refuses to start without a complete stage plan. This is a fail-closed configuration error, not a reason to fall back to the retired scheduler or legacy analytical paths.

PR6 provides the operating control plane. It does not claim that a licensed production provider, broad certified data, or sufficient elapsed paper evidence exists. Those remain later data and validation dependencies.
