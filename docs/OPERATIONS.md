# Deployment and Operations

## Runtime topology

The Version 1 production topology contains four independently restartable services built from the same immutable image:

- `api` — authenticated FastAPI boundary;
- `web` — authenticated Streamlit experience;
- `scheduler` — canonical daily cycle and selective-alert worker; and
- `backup` — encrypted SQLite backup loop.

All services run as an unprivileged user with dropped Linux capabilities, a read-only root filesystem, and explicit writable data, backup, and temporary mounts. TLS terminates at a trusted reverse proxy or managed ingress. The application rejects non-HTTPS requests in production using the forwarded protocol header.

## Start a staging stack

```bash
cp deploy/staging.env.example deploy/staging.env
# Replace every placeholder secret.
docker compose up --build -d
```

Expose ports only through a TLS reverse proxy in shared environments. The compose defaults bind API and Streamlit to loopback.

## Health contracts

- `GET /health` — process liveness and release identity;
- `GET /ready` — required stores, authentication, alert persistence, backup target, and operational-policy readiness;
- `GET /live` — minimal process liveness;
- `GET /worker/health` — scheduler heartbeat freshness and last cycle status;
- `GET /operations/slo` — current governed operational-objective assessment, protected by the metrics bearer token when configured;
- `GET /metrics` — Prometheus text format, protected by the metrics bearer token when configured.

A stale or failed scheduler heartbeat returns HTTP 503 without marking the API process itself dead.

## Security-master readiness

The security master has a separate operational authority from ordinary store readiness. Catalog ingestion, activation, and source freshness can be inspected without contacting a provider:

```bash
python run_security_master.py --status
```

Monitor `screening_ready`, both integrity flags, the active catalog identifier, active source age, and blocking reasons. A catalog can remain stored while `screening_ready` is false. This is expected for the public SEC current feed and for any stale or incomplete provider delivery.

Production full-universe screening must call the activated-catalog boundary. It must not read the latest catalog row directly. Alert on catalog-chain failure, operation-chain failure, source age above policy, activation rejection, reconciliation conflict, and an absent active catalog after the licensed provider's delivery window.

See [Security-master ingestion and activation](SECURITY_MASTER_OPERATIONS.md).

## Governed operational SLOs

Production readiness evaluates four process objectives from authoritative stores:

1. the activated security-master source is intact and within the configured freshness limit;
2. the complete eligible universe is screened by the scheduled deadline using the currently active catalog;
3. every monitored living thesis is reviewed within its configured grace period; and
4. every frozen decision-evidence snapshot is evaluated within its configured grace period after the decision horizon ends.

Run an assessment without mutating history:

```bash
python run_slos.py
```

Record an immutable assessment and fail the command when required objectives are not ready:

```bash
python run_slos.py --record-assessment --require-ready
```

`run_full_universe_screening.py` records completed and failed terminal cycle evidence automatically. A completed cycle includes the certified active catalog, immutable universe snapshot, exact eligible and screened counts, publication identifier, and completion timestamp. A failed or incomplete cycle records its error but cannot publish candidates, an opportunity queue, or CIO-journal evidence. `run_slos.py --cycle-status` remains an administrative repair interface for independently verified historical evidence, not the normal screening path. In production, `CAPITAL_INTELLIGENCE_REQUIRE_OPERATIONAL_SLOS=true` makes the assessment a required `/ready` component. Missing authoritative stores, invalid hash chains, stale providers, late or incomplete cycles, overdue thesis reviews, and overdue evaluations fail closed.

Deadline boundaries are inclusive: an action completed exactly at its deadline is compliant; it becomes breached only after the deadline passes. Historical late records remain auditable, while current readiness reflects the latest required process state.

See [Operational service-level objectives](OPERATIONAL_SLOS.md).

## Logs and correlation

Every API request receives an `X-Request-ID`. A valid inbound ID is preserved; otherwise a new UUID is generated. JSON logs include timestamp, severity, service, environment, release, request ID, path, status, duration, and client address. Passwords, tokens, authorization headers, and secrets are never added as structured fields.

## Metrics

The API exports request counts, duration sums, rate-limit rejections, unhandled exceptions, overall operational-SLO readiness, objective readiness, objective state, actual latency or age, and configured thresholds. Scrape `/metrics` using:

```http
Authorization: Bearer <CAPITAL_INTELLIGENCE_METRICS_TOKEN>
```

Create alerts for sustained 5xx responses, stale worker heartbeat, failed scheduled cycles, repeated delivery failures, backup failure, and missing daily snapshots after the configured cycle window.

## Request hardening

The API enforces:

- trusted host allowlists;
- optional production HTTPS enforcement;
- request body size limits;
- per-process sliding-window rate limits;
- no-store, frame-denial, referrer, content-type, permissions, and CSP headers;
- HSTS when HTTPS enforcement is enabled.

Rate limiting is intentionally local to one API process. A future horizontally scaled deployment should replace it with an ingress or shared-store limiter.

## Secrets

Use a secret manager or orchestrator secret facility. Do not commit populated `.env` files. Remove the bootstrap administrator password after the initial account is created. Rotate metrics, backup-encryption, SMTP, provider, and administrator credentials independently.

## Release procedure

1. Merge only after tests, image build, and security workflows pass.
2. Tag the image with the immutable commit SHA.
3. Back up production stores and verify the archive.
4. Deploy to staging and check `/ready`, `/worker/health`, login, daily snapshot, and alert inbox.
5. Promote the identical image to production.
6. Monitor errors, cycle completion, worker freshness, and backup completion.
7. Roll back to the prior image if readiness or user-critical checks fail.

## Thesis-monitoring cycle

```bash
python run_thesis_monitoring.py \
  --evidence-provider production_thesis_provider:create_provider \
  --as-of 2026-07-27T00:00:00+00:00 \
  --require-all-success
```

Scheduled and event-driven reviews are append-only. Stable reviews satisfy the thesis-review SLO without notifying the user. Material reviews create a CIO queue item but cannot alter portfolio construction or execution. See [Production thesis monitoring](THESIS_MONITORING_OPERATIONS.md).

## Paper execution cycle

```bash
python run_paper_execution.py \
  --construction artifacts/latest_construction.json \
  --portfolio artifacts/current_paper_portfolio.json \
  --decision-identifier decision:example \
  --session-provider production_calendar:create_provider \
  --quote-provider production_paper_quotes:create_provider \
  --as-of 2026-07-27T15:00:00+00:00 \
  --require-complete
```

The cycle is paper-only. It sequences funding sells before dependent buys, holds orders outside configured sessions, caps fills by participation and cash or ownership, applies bid/ask and commissions, and publishes canonical paper fills only after the virtual ledger reconciles. A held or partial batch should be retried from the exact ending portfolio state or explicitly cancelled. See [Paper execution orchestration](PAPER_EXECUTION_ORCHESTRATION.md).

## Extended paper-operation evidence

Append one or more immutable evidence observations and assess the current release sample:

```bash
python run_paper_operation_review.py \
  --observation artifacts/paper-operation-observation.json \
  --record-report
```

Scheduled release checks should use a reviewed policy file and fail unless the sample is ready for human governance review:

```bash
python run_paper_operation_review.py \
  --policy deploy/paper-operation-policy.json \
  --record-report \
  --require-governance-ready
```

A blocked assessment indicates an operating or evidence-quality failure. An insufficient assessment indicates that the process may be functioning but lacks adequate duration, regime diversity, decisions, calibration samples, implementations, or alert feedback. Ready-for-review never authorizes real-money trading or performance claims. See [Extended paper-operation evidence](PAPER_OPERATION_EVIDENCE.md).

## Resilience exercise campaign

```bash
python run_resilience_exercises.py \
  --suite deploy/resilience-suite.json \
  --provider production_resilience_adapter:create_provider \
  --record \
  --require-passed
```

The campaign must run in an isolated environment and prove fault injection, timely detection, controlled recovery, and exact reconciliation for provider outages, stale or conflicting data, database corruption, missed universe cycles, failed thesis reviews, delayed evaluations, partial paper execution, backup restoration, and model rollback. Production mutations, missing evidence, late recovery, or invariant mismatch fail closed. See [Incident, recovery, and reconciliation exercises](RESILIENCE_EXERCISES.md).
