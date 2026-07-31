# Security Threat Model

## Assets

- Canonical portfolio and decision lineage.
- Administrator credentials, sessions, provider keys, Alpaca paper keys, backup key, metrics token.
- Execution approvals and idempotency/lease state.
- Private operational telemetry, backup/restore controls, and smoke tests.
- Public read models that must not leak secrets, internal identifiers, or private administrative data.

## Trust boundaries

1. Anonymous internet to public Streamlit/read API.
2. Authenticated administrator session to private controls.
3. UI/API processes to shared persistent storage.
4. Headless operator to execution state and external providers.
5. Provider/broker responses to internal normalized evidence.
6. Backup process to encrypted archives.
7. CI/GitHub/Render build identity to deployed runtime.

## Principal threats and controls

| Threat | Risk | Required control |
|---|---|---|
| Anonymous administrator principal | Full operational/mutation exposure when auth is off | Dedicated anonymous principal with no role and view-only canonical grant; method-aware API denial; hidden and server-guarded controls |
| UI-triggered execution | Public/session process becomes execution authority | Remove writer from Streamlit; headless lease authority only |
| Confused deputy between CIO/construction/executor | Downstream creates authority | Typed authorization artifacts and invariant tests |
| Source rewriting/`exec` | Unexpected code path and authorization bypass | Normal imports, explicit dependencies, one factory |
| CSRF/session fixation/brute force | Admin control abuse | Same-site secure sessions/tokens, rate limits, rotation, audit events; no mutation in anonymous mode |
| Secret leakage | Credential compromise | Environment-only secrets, redaction tests, private metrics/readiness detail, no secrets in archives/logs |
| Broker endpoint substitution | Accidental live-money route | Paper hostname/account allowlist and real-money hard false at transport boundary |
| Replay/duplicate execution | Repeated portfolio mutation | Durable idempotency key, construction hash, lease, reconciliation checkpoint |
| State tampering | False holdings/history | Append-only DB triggers/hash lineage, integrity checks, encrypted backups |
| Stale/poisoned data | Incorrect CIO action | Provenance, corroboration, freshness, provider certification, fail-closed readiness |
| Deployment supply-chain drift | Unreviewed code runs | Exact Git SHA, checks-passed auto-deploy, pinned actions/dependencies, composite post-deploy check |

## PR1 security invariant

Anonymous access can observe only approved read models. It cannot mutate alert state, identity, preferences, approvals, execution, backups, smoke tests, or administrative/operational state even if a client calls private endpoints directly.

## Readiness information disclosure

`/health` remains minimal liveness. `/ready` exposes only sanitized component
states and the deployed SHA needed for release verification. Full operational,
paper-test, dependency, and composite evidence under `/v1/readiness/status` is
administrator-only. None of these endpoints grants execution or investment
authority.
