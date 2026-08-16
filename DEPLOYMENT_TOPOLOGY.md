# Deployment Topology

## Canonical declared topologies

| Environment | Canonical command | Processes | Policy |
|---|---|---|---|
| Render | `python run_render_service.py` | API, headless operator, backfill, backup, Streamlit, readiness watchdog | automatic paper mode; one persistent disk |
| Docker API image | `python capital_intelligence_cli.py run api` | API | paper disabled unless a separate operator is explicitly started |
| Docker Compose | `docker compose up --build` | API, operator, backfill, backup, Streamlit | environment-explicit paper mode |
| Local | `python capital_intelligence_cli.py run ui` | Streamlit | paper disabled by default |
| CI | `python capital_intelligence_cli.py run validate` | deterministic validation | no execution |

The machine-readable authority is `config/runtime_topologies.json`. The CLI
validates all 89 root `run_*.py` entrypoints: 9 are active runtime commands, 80
are supported specialized compatibility tools, and none is silently classified
as legacy. Existing specialized scripts remain callable for one-release
compatibility; new operator-facing documentation uses the CLI gateway.

## Target canonical topologies

### Production / Render

One Render service is acceptable while one persistent disk is required, provided
`run_render_service.py` is the sole supervisor, the headless operator is the only
execution authority, each child emits a heartbeat, and service availability is
separate from investment readiness.

Render exposes Streamlit's built-in liveness endpoint on the single public
service port. The critical readiness watchdog probes the internal API `/ready`
contract after a bounded startup grace. `/ready` is now **SERVING_READY** only:
it verifies the canonical portfolio and CIO journal remain readable, identity is
ready when required, and production exposes an exact 40-character Git SHA. If
this serving contract stays blocked, or regresses after first becoming ready,
the watchdog exits and the supervisor terminates the service so Render can
restart a genuinely unhealthy application.

Provider availability, evidence freshness, complete-universe qualification,
operator evidence, reconciliation, backup freshness, alert delivery, historical
backfill, and execution prerequisites do **not** make the read-only product
unavailable. They remain fail-closed downstream gates:

- `/ready` — serving availability and restart boundary.
- `/ready/composite` — the prior strict operational/investment readiness contract.
- `/ready/layers` — credential-safe `SERVING_READY -> EVIDENCE_READY -> DECISION_READY -> EXECUTION_READY` state.
- `/v1/readiness/status` — administrator detail including the layered and strict reports.

A blocked evidence, decision, or execution layer means no new portfolio action
may advance through that layer. It does not invalidate the last reconciled
canonical portfolio and does not authorize a downstream component to repair an
upstream state synchronously.

Strict composite production readiness continues to require component heartbeats,
current operator evidence, reconciled operational evidence, a recent successful
encrypted backup, dependency readiness, and the exact deployed Git SHA. It is
preserved as an investment/operational safety diagnostic rather than the service
restart trigger.

### Local development

One documented CLI command starts API, Streamlit read-only UI, and optional
non-authoritative fixtures. Paper execution is disabled by default and requires
an explicit paper-only profile.

### Container integration

Compose starts separate API, UI, operator, backfill, and backup services against
explicit shared durable volumes. Commands and entrypoints must be generated from
or tested against the same topology manifest as Render.

### CI

CI runs behavioral unit/integration tests, architecture invariants, container
acceptance, API readiness, real Streamlit browser/mobile tests, golden end-to-end
scenarios, and chaos/idempotency tests. Credentialed provider/broker checks remain
separate required-or-advisory gates according to deployment policy.

## Deployment identity requirement

Every process must expose the same full deployed Git SHA. `SERVING_READY` fails
when the API's production release identity is `unknown` or not an exact
40-character SHA. Strict composite readiness continues to validate production
runtime identity across its operational evidence. Rollback selects an exact prior
SHA and does not modify persistent state in place.
