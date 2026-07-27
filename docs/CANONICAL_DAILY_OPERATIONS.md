# Canonical Daily Operations

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

## Purpose

The daily operations authority coordinates the complete investment process. It does not discover securities, fabricate evidence, change rankings, issue recommendations, resize positions, approve a market, or authorize live trading.

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

`CANONICAL_DAILY_STAGE_ORDER` is the only active sequence. Incomplete, failed, or unreconciled upstream work prevents every downstream stage from starting.

## Multi-worker ownership

The append-only event chain remains the audit authority. A separate SQLite coordination plane provides:

- one expiring operation lease;
- one expiring lock for the active stage;
- stable worker identity;
- operation and stage heartbeats;
- monotonically increasing operation fencing tokens;
- monotonically increasing stage fencing tokens; and
- atomic fence validation immediately before every authoritative event append.

An active lease excludes another worker. When a lease expires, a replacement worker receives a higher fencing token and resumes from the durable event history. The stale worker may finish local computation, but it cannot publish a heartbeat, completion, failure, or terminal result with its obsolete token.

The lease tables are mutable coordination state. `canonical_daily_operation_events` remains append-only and hash chained. Each authoritative event includes the worker, operation token, stage token where applicable, and lease-expiration boundary used for that publication.

## Stage execution isolation

The repository ships `deploy/canonical-daily-operations.json`, a complete version-2 plan containing all twelve stages. Each stage invokes `run_daily_stage_adapter.py`.

The adapter:

1. verifies the active operation and stage fence;
2. starts the configured delegate as an isolated Python subprocess;
3. enforces the stage wall-clock timeout;
4. requires one JSON object;
5. reconciles the configured persisted output identifiers;
6. verifies the fence again; and
7. emits one fenced stage-publication identifier.

Only that post-fence publication identifier is passed to the next stage. Output created by a delegate after its worker loses ownership cannot become canonical downstream input.

## Deployment files

The repository plan is:

```text
/app/deploy/canonical-daily-operations.json
```

Deployment injects the reviewed binding document at:

```text
/run/secrets/canonical-daily-stage-bindings.json
```

The binding document uses schema `canonical-daily-stage-bindings.v1` and must configure exactly the same twelve stages. It identifies the real repository command, arguments, persisted output fields, retryable exit codes, and timeout for each stage. Licensed-provider credentials and proprietary configuration remain secrets and are not committed.

`deploy/canonical-daily-stage-bindings.validation.json` is synthetic acceptance evidence only. Every delegate uses `run_daily_stage_fixture.py`, and every record states `fixture_only=true` and `real_money_authorized=false`. It must never be installed as a production binding secret.

## Startup validation

Before the scheduler loop starts, run:

```bash
python run_daily_operations.py --validate-plan
```

Validation fails when:

- the plan or binding schema is unsupported;
- any canonical stage is missing or duplicated;
- a command module cannot be imported;
- required output fields are absent;
- timeout or retry settings are invalid;
- the binding secret is unavailable; or
- environment substitutions remain unresolved.

Docker runs this validation before `--loop`. A missing reviewed binding file is a deployment error; Docker does not fall back to validation fixtures or a retired scheduler.

## Durable stage contract

Every stage records:

- operation and stage idempotency keys;
- dependency input identifiers;
- fenced canonical publication identifiers;
- worker ownership and fencing tokens;
- start, heartbeat, and completion timestamps;
- the exact point-in-time knowledge cutoff;
- retry attempts and backoff policy;
- typed failure classification;
- reconciliation status; and
- immutable detail and source lineage.

A successful stage must return at least one persisted identifier. Its cutoff must exactly match the operation cutoff. Its reconciliation status must be `reconciled` or `not_applicable`.

Failures are classified as `transient_provider`, `data_quality`, `dependency`, `integrity`, `configuration`, `reconciliation`, `execution`, `interrupted`, or `unknown`. Only explicitly retryable failures may consume another attempt.

## Commands

Run one worker:

```bash
export CAPITAL_INTELLIGENCE_DAILY_STAGE_BINDINGS_FILE=/secure/reviewed-bindings.json
export CAPITAL_INTELLIGENCE_DAILY_STAGE_BINDINGS=/run/secrets/canonical-daily-stage-bindings.json
python run_daily_operations.py --validate-plan
python run_daily_operations.py --loop
```

Run multiple workers against the same canonical database by giving each worker a stable name or allowing the default `hostname:pid` identity:

```bash
CAPITAL_INTELLIGENCE_DAILY_WORKER_IDENTIFIER=scheduler-a python run_daily_operations.py --loop
CAPITAL_INTELLIGENCE_DAILY_WORKER_IDENTIFIER=scheduler-b python run_daily_operations.py --loop
```

Only the lease owner executes. Nonowners report a healthy `lease_not_acquired` status rather than performing duplicate work.

Lease policy is configured through:

```text
CAPITAL_INTELLIGENCE_DAILY_LEASE_SECONDS=120
CAPITAL_INTELLIGENCE_DAILY_LEASE_HEARTBEAT_SECONDS=15
```

The heartbeat interval must be less than half the lease duration.

## Container acceptance

The Dockerfile has separate targets:

- `runtime` — locked production dependencies only;
- `validation` — runtime plus development test tools.

Run the deterministic acceptance command:

```bash
docker build --target validation -t capital-intelligence:validation .
docker run --rm capital-intelligence:validation
```

It performs two bounded checks:

1. all twelve fenced stages complete in order through isolated validation delegates; and
2. the persisted certified-universe → screening → production-context → real canonical CIO-cycle integration passes.

The validation delegates do not claim provider access, market readiness, performance, or real-money authority.

## Readiness boundary

A completed daily operation proves that one configured process instance ran and reconciled. It does not prove licensed provider coverage, market certification, resilience, elapsed burn-in, human governance approval, or paper-test readiness. Those statuses remain separately evaluated against an immutable baseline, exact process version, and exact code version.
