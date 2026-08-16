# Failure Mode Register

| Failure | Current detection | Required response | Owner PR |
|---|---|---|---|
| Auth disabled yields admin | None; behavior is intentional compatibility mode | Anonymous read-only principal; deny every mutation/admin path | PR1 |
| Streamlit and headless executor race | Idempotency/approval checks reduce but do not remove dual authority | Remove Streamlit writer; one leased headless authority | PR2 |
| UI source marker drift | Runtime exception if replacement count differs | Normal imports/factory; architectural import test | PR3 |
| API or canonical read authority unavailable while Streamlit lives | `SERVING_READY` checks canonical portfolio, CIO journal, required identity and production release identity | Critical serving watchdog fails and permits Render restart; do not synthesize read state | layered readiness |
| Operator/backfill/backup degraded while API and canonical reads remain healthy | Layered and strict composite readiness | Keep `SERVING_READY=true`; block the affected evidence/decision/execution layer and preserve last reconciled canonical state | layered readiness |
| Unknown/mixed deployed SHA | Serving and strict production release checks | `SERVING_READY=false` for a non-exact API production SHA; preserve strict runtime identity diagnostics | PR4 / layered readiness |
| Serving gate never becomes ready | Critical watchdog after startup grace and sustained failed probes | Inspect the named serving dependency and restart without bypassing canonical-state integrity | layered readiness |
| Serving gate regresses | Sustained `/ready` failures terminate the supervisor and trigger Render restart | Preserve readiness evidence and repair the serving blocker | layered readiness |
| Strict composite gate never becomes ready or later regresses | `/ready/composite` and `EXECUTION_READY` | Do not restart a healthy read-only product solely for this condition; fail closed for new execution and repair the named operational dependency | layered readiness |
| Topology command drift | Source-text tests/documentation | One manifest/CLI plus container/integration tests | PR5 |
| Archive selected by mtime | Reproduced in the full suite: pending transaction history returned `held` before later `completed` after 196 earlier tests passed | Embedded UTC time + stable identifier tie-breaker | PR6 |
| Scheduler duplicate after restart | Partial lease/idempotency controls | Durable lease, cycle key, restart replay tests | PR7 |
| Partial fill or crash before reconciliation | Reconciliation may block | Resume/compensate deterministically; never publish partial canonical state | PR7/PR9 |
| Provider outage/stale data | `EVIDENCE_READY` plus strict evidence/readiness provenance | Set `EVIDENCE_READY=false`, which forces `DECISION_READY=false` and `EXECUTION_READY=false`; retain `SERVING_READY` and the prior canonical portfolio unless an independent serving failure exists | PR9/PR11 / layered readiness |
| Event duplication or sensational single source | Fixed source scores | Cluster, novelty, corroboration, materiality, confirmation benchmark | PR10 |
| Monitored market mistaken as allocatable | Multiple manifests/labels | Three explicit scopes and decision certificate | PR11 |
| PIT leakage/survivorship bias | Point-in-time contracts exist | Dataset-era certification across all required domains | PR11 |
| Paper results tune policy opportunistically | Launch policy only | Frozen experiment protocol and governed review | PR12 |
| Backup absent/stale/unrestorable | Backup loop, strict composite readiness and smoke controls | Keep serving available when canonical reads are sound; set `EXECUTION_READY=false` under the strict policy and require restore-drill evidence | PR4/PR9 / layered readiness |
| Disk full/corrupt canonical SQLite | Serving/readiness and operational integrity checks | `SERVING_READY=false` when canonical read authority is corrupt/unreadable; fail closed, restore/reconcile, never reset canonical state | PR4/PR9 / layered readiness |
| Live broker endpoint/key misconfiguration | Paper base URL and assertions | Hard allowlist, paper-account verification, live endpoint prohibition tests | PR2/PR9 |

All failures default to no new portfolio change. The last reconciled canonical state remains authoritative whenever it is itself valid and readable. A downstream readiness layer may not repair, recreate, or override a blocked upstream state synchronously.
