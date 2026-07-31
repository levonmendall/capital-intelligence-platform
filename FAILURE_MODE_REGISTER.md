# Failure Mode Register

| Failure | Current detection | Required response | Owner PR |
|---|---|---|---|
| Auth disabled yields admin | None; behavior is intentional compatibility mode | Anonymous read-only principal; deny every mutation/admin path | PR1 |
| Streamlit and headless executor race | Idempotency/approval checks reduce but do not remove dual authority | Remove Streamlit writer; one leased headless authority | PR2 |
| UI source marker drift | Runtime exception if replacement count differs | Normal imports/factory; architectural import test | PR3 |
| API/operator/backfill/backup dead while Streamlit lives | Render health remains green | Composite readiness with per-component heartbeats | PR4 |
| Unknown/mixed deployed SHA | Sidebar may show `unknown` | Production readiness fails and reports full SHA | PR4 |
| Topology command drift | Source-text tests/documentation | One manifest/CLI plus container/integration tests | PR5 |
| Archive selected by mtime | Reproduced in the full suite: pending transaction history returned `held` before later `completed` after 196 earlier tests passed | Embedded UTC time + stable identifier tie-breaker | PR6 |
| Scheduler duplicate after restart | Partial lease/idempotency controls | Durable lease, cycle key, restart replay tests | PR7 |
| Partial fill or crash before reconciliation | Reconciliation may block | Resume/compensate deterministically; never publish partial canonical state | PR7/PR9 |
| Provider outage/stale data | Multiple readiness gates | Fail closed, identify missing domain, retain prior canonical state | PR9/PR11 |
| Event duplication or sensational single source | Fixed source scores | Cluster, novelty, corroboration, materiality, confirmation benchmark | PR10 |
| Monitored market mistaken as allocatable | Multiple manifests/labels | Three explicit scopes and decision certificate | PR11 |
| PIT leakage/survivorship bias | Point-in-time contracts exist | Dataset-era certification across all required domains | PR11 |
| Paper results tune policy opportunistically | Launch policy only | Frozen experiment protocol and governed review | PR12 |
| Backup absent/stale/unrestorable | Backup loop and smoke controls | Readiness age threshold plus restore-drill evidence | PR4/PR9 |
| Disk full/corrupt SQLite | Partial operational checks | Capacity, integrity, write-probe, restore rehearsal; fail closed | PR4/PR9 |
| Live broker endpoint/key misconfiguration | Paper base URL and assertions | Hard allowlist, paper-account verification, live endpoint prohibition tests | PR2/PR9 |

All failures default to no new portfolio change. The last reconciled canonical state remains authoritative.
