# Canonical State Map

## Authoritative persistent state

| State | Render path/default | Writer | Readers | Authority |
|---|---|---|---|---|
| Portfolio events/state | `/app/database/canonical_portfolio.db` | Reconciled internal paper execution/state service | CIO context, API, Streamlit, evaluation | Canonical holdings/cash/NAV lineage |
| CIO journal | `/app/database/institutional_journal.db` | Canonical CIO cycle | API, UI, evaluation | Canonical decision lineage, not holdings |
| Identity/session audit | `/app/database/identity.db` | Authentication/admin service | Auth guards/admin | Identity only |
| Alerts/delivery | `/app/database/alerts.db` | Delivery service/user preferences | Authenticated user UI/API | Notification state only |
| Paper execution evidence | `/app/database/multi_asset_paper_execution.db` and governed reports | Headless executor | Reconciler/UI/evaluation | Implementation evidence, not independent portfolio authority |
| Public information | `/app/database/public-live-information-*.json` | Headless collection runtime | CIO context/UI | Evidence only |
| CIO report archive | `/app/database/cio_reports/` | Reporting cycle | UI/API | Presentation archive |
| Historical replay | `/app/database/historical_replay/` | Backfill/replay loop | Certification/evaluation | Research evidence only |
| Backups | `/app/database/backups/` | Backup loop/admin control | Restore drills | Recovery copies only |
| Heartbeats/readiness | `/app/database/...` configured operational paths | Each component (target state) | Composite readiness | Operational state only |
| Paper execution leases | `/app/database/paper_execution_leases.db` | Sole headless executor | Executor fencing checks | Mutable coordination only; never portfolio or decision authority |

## Publication rule

Only an internally simulated, paper-only execution that matches a CIO-authorized construction and passes reconciliation may append portfolio state. Alpaca paper transport validation records broker evidence separately and must never become the portfolio ledger writer.

## Append-only expectations

- Canonical portfolio events and CIO journal events are immutable after append.
- Archive selection must use embedded UTC timestamps plus stable identifiers, never filesystem modification time.
- Derived read models are rebuildable and must never be treated as primary state.
- Backups preserve activated authorities and are not writable runtime databases.
- Historical learning produces new versioned evaluation/proposal records; it never edits prior decisions.
