# Deployment Topology

## Current declared topologies

| Environment | Current command | Current processes | Conflict |
|---|---|---|---|
| Render | `python run_render_service.py` | API, headless operator, backfill, backup, `render_app.py` | Health checks only Streamlit |
| Docker image default | `python initialize.py && uvicorn ...` | API only | Does not match Render supervisor |
| Docker Compose | separate API, scheduler, backup, `secure_app.py` web | Four services | Different UI entrypoint; no historical loop |
| README/local | multiple direct commands including `streamlit run secure_app.py` | Operator-selected | Not a single canonical topology |

## Target canonical topologies

### Production / Render

One Render service is acceptable while one persistent disk is required, provided `run_render_service.py` is the sole supervisor, the headless operator is the only execution authority, each child emits a heartbeat, and a composite readiness endpoint gates deployment.

Render exposes Streamlit's built-in liveness endpoint on the single public
service port. A critical `composite-readiness-watchdog` probes the internal API
readiness contract after a bounded startup grace. If composite readiness stays
blocked, or regresses after first becoming ready, the watchdog exits and the
supervisor terminates the service so the public liveness probe fails and Render
restarts it. This bridges the single-port constraint without exposing private
diagnostics.

Composite production readiness requires component heartbeats, current operator
evidence, reconciled operational evidence, a recent successful encrypted backup,
and the exact deployed 40-character Git SHA.

### Local development

One documented CLI command starts API, Streamlit read-only UI, and optional non-authoritative fixtures. Paper execution is disabled by default and requires an explicit paper-only profile.

### Container integration

Compose starts separate API, UI, operator, backfill, and backup services against explicit shared durable volumes. Commands and entrypoints must be generated from or tested against the same topology manifest as Render.

### CI

CI runs behavioral unit/integration tests, architecture invariants, container acceptance, API readiness, real Streamlit browser/mobile tests, golden end-to-end scenarios, and chaos/idempotency tests. Credentialed provider/broker checks remain separate required-or-advisory gates according to deployment policy.

## Deployment identity requirement

Every process must expose the same full deployed Git SHA. Composite readiness fails when SHAs disagree or are `unknown` in production. Rollback selects an exact prior SHA and does not modify persistent state in place.
