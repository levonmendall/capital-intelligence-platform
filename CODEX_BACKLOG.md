# Codex Backlog

All PRs are ordered. No PR adds strategy engines or performs unrelated cleanup. Every merge requires the exact production entrypoint and required CI gates to pass.

## PR1 — Public viewer / private administrator split

- **Invariant:** anonymous access is read-only and can never acquire administrator, mutation, approval, execution, backup, smoke-test, or identity authority.
- **Files/state before edit:** `security/identity.py`, `security/__init__.py`, `api/dependencies.py`, `api/app.py`, `secure_app.py`, `app.py`, authorization/API/Streamlit tests; identity schema is unchanged.
- **Acceptance:** auth-off yields a stable anonymous principal with view-only canonical access; every non-safe HTTP method requires authenticated private authority; anonymous Streamlit has no private controls and cannot start execution; auth-on behavior remains intact.
- **Tests:** principal behavior, API GET/POST denial, direct private endpoint denial, Streamlit anonymous/admin behavioral smoke, execution-worker non-invocation.
- **Deployment/migration:** no DB migration; public mode becomes safe-by-default. Render currently keeps auth required.
- **Rollback:** revert PR; if rollback is necessary, keep authentication required and remove public exposure.
- **Authority change:** authentication/administrative access only. CIO, construction, governance, paper-execution semantics, and real-money authority unchanged.

## PR2 — Single headless paper-execution authority

- **Invariant:** exactly one leased headless process can implement a CIO-authorized construction; Streamlit only reads execution state.
- **Files/state:** `run_autonomous_paper_operator.py`, `streamlit_paper_execution_worker.py`, `app.py`/factory, execution runtime, leases/idempotency DB/report paths, tests.
- **Acceptance:** no UI import/callback starts execution; one durable authority/lease owner; duplicate/restart passes produce no duplicate fill/state append; Alpaca remains separate validation.
- **Tests:** concurrent process, restart, duplicate construction hash, UI read-only, paper endpoint/account, reconciliation integration.
- **Deployment/migration:** retire/ignore Streamlit worker state after proving no pending exclusive record; no portfolio-state rewrite.
- **Rollback:** stop service, restore prior image, keep UI private and execution mode paused until singularity is re-established.
- **Authority change:** consolidates existing paper implementation authority; CIO/construction/governance and real-money authority unchanged.

## PR3 — Normal application composition

- **Invariant:** UI composition cannot alter investment behavior or authorization and uses no runtime source reads/transforms/`exec`.
- **Files/state:** `render_app.py`, `secure_app.py`, `app.py`, `app_impl.py`, UI helpers, composition tests; no persistent-state changes.
- **Acceptance:** one explicit application factory with injected principal/read repositories; normal imports only; four screens and outputs behaviorally equivalent.
- **Tests:** import-architecture rule, authenticated/anonymous factory tests, golden screen data, no `exec`/source replacement in active entrypoint.
- **Deployment/migration:** canonical Streamlit entrypoint changes once; Render command tested against it.
- **Rollback:** restore prior image; no data rollback.
- **Authority change:** none.
- **Implementation record:** `app.py` and `render_app.py` now call
  `secure_app.create_streamlit_application`; `secure_app.py` injects typed,
  session-authorized `ApplicationDependencies`; and `app_impl.py` renders the
  four surfaces through direct helper calls. The active files contain no
  runtime source reads, transformations, reloads, monkey patches, or `exec`.
  The focused composition, authorization, Render AppTest, and presentation
  suite passes **41/41**. Persistent state and schemas are unchanged.

## PR4 — Composite production readiness and heartbeats

- **Invariant:** production is ready only when every required component, data gate, reconciliation gate, backup, and release identity is healthy.
- **Files/state:** supervisor, API readiness, operational settings/heartbeat store, operator/backfill/backup/UI heartbeat writers, `render.yaml`, tests; new append/update-safe operational heartbeat state.
- **Acceptance:** reports API/operator/backfill/backup/UI, data freshness, reconciliation, backup age, disk/DB integrity, and full Git SHA; required failure returns non-ready.
- **Tests:** stale/missing heartbeat, bad SHA, stale data, unreconciled state, old backup, component death.
- **Deployment/migration:** the single-port Streamlit liveness probe is bridged to composite readiness by a critical supervised watchdog; detailed diagnostics are private.
- **Rollback:** restore Streamlit probe only temporarily while pausing auto execution.
- **Authority change:** operational gating only; no investment or real-money authority.
- **Implementation record:** production `/ready` combines API dependencies
  with component heartbeats for API, Streamlit, the CIO paper operator,
  historical backfill, and encrypted backup; explicit data-freshness,
  reconciliation, backup-age, and exact-40-character Git-SHA gates are also
  required. Detailed readiness is administrator-only and public component
  details are sanitized. A critical watchdog gives startup grace and then
  makes sustained composite failure terminate the supervised Render service.
  New persistent state is limited to atomic JSON files under
  `database/component-heartbeats/`; no investment schema changes. Focused
  readiness, API, Render, backup, historical, and operator tests pass **35/35**,
  with an additional API/privacy gate passing **30/30**.

## PR5 — Canonical deployment topology and documentation

- **Invariant:** each supported environment has one tested topology and command set derived from a canonical declaration.
- **Files/state:** topology manifest/CLI, `render.yaml`, Dockerfile, Compose, README/deployment docs, root command inventory, tests; no investment state.
- **Acceptance:** Render/local/Compose/CI commands are explicit and tested; active/compatibility/legacy inventory complete; 87 scripts mapped to CLI or retained with rationale.
- **Tests:** container acceptance and command-manifest consistency; no source-text-only topology assertions.
- **Deployment/migration:** documented command changes; staged deprecation aliases.
- **Rollback:** retain prior command aliases for one release.
- **Authority change:** none.
- **Implementation record:** `config/runtime_topologies.json` is the
  machine-readable command/topology authority and `capital_intelligence_cli.py`
  is the supported gateway. Render, Docker API, Compose, local UI, and CI each
  have one explicit topology. Compose now uses `app.py`, includes historical
  backfill, and retains the sole headless operator. All **89/89** current root
  runners are classified exactly once (9 runtime-active, 80 specialized
  supported, 0 silently legacy). Focused manifest, Render, operator, release,
  and documentation tests pass **21/21**. No persistent state, CIO,
  construction, governance, execution semantics, or real-money authority
  changed. Rollback may restore the old direct commands because the underlying
  compatibility scripts remain present for one release.

## PR6 — Deterministic history and archive ordering

- **Invariant:** content timestamps and stable identifiers—not filesystem metadata—determine order everywhere.
- **Files/state:** pending/CIO/operating archives, smoke reports, backups, API repositories, schemas/tests; archive metadata may gain versioned embedded timestamps.
- **Acceptance:** copy/touch/restore does not reorder records; equal timestamps use stable IDs/hashes; invalid timestamp fails closed or is explicitly legacy-ranked.
- **Tests:** randomized mtimes, equal-time ties, timezone normalization, restore ordering.
- **Deployment/migration:** lazy/read-time compatibility plus optional append-only metadata index; no rewrite of canonical events.
- **Rollback:** old reader can consume unchanged payloads; do not delete generated index.
- **Authority change:** none.
- **Implementation record:** shared artifact ordering now requires an embedded
  timezone-aware timestamp normalized to UTC and uses an explicit stable ID or
  canonical payload SHA as the tie-breaker. Pending CIO reports, smoke-test
  execution attempts, live-console execution history, backup selection, and
  backup pruning no longer use filesystem metadata. Invalid archive ordering
  metadata fails closed; invalid backup metadata is never pruned. Focused
  deterministic, pending-report, backup, smoke, and console tests pass
  **25/25**. Existing payloads and backup schemas are unchanged, so rollback is
  reader-only and requires no data rewrite. No authority changed.

## PR7 — Scheduler, restart, idempotency, and reconciliation hardening

- **Invariant:** crash, overlap, or retry cannot produce an unauthorized/duplicate state change; only reconciled cycles advance canonical state.
- **Files/state:** scheduler/operator leases, stage bindings, execution/retry/reconciliation stores, CLI, tests.
- **Acceptance:** deterministic cycle/execution keys; durable checkpoints; takeover after lease expiry; partial state never canonical; recovery resumes or blocks predictably.
- **Tests:** kill at every checkpoint, overlapping schedulers, clock skew, provider timeout, partial fill, DB lock.
- **Deployment/migration:** versioned lease/checkpoint schema; operator paused during migration.
- **Rollback:** pause execution, restore binary, preserve new records for forensic compatibility.
- **Authority change:** reliability of existing paper authority only; no real-money authority.
- **Implementation record:** the daily scheduler's existing durable operation
  leases, stage leases, heartbeat renewal, fencing tokens, idempotency keys, and
  reconciliation checkpoints were retained. The remaining mtime lock in the
  exact paper executor is replaced by `paper_execution_leases.db`: atomic
  acquisition, monotonic fencing tokens, heartbeat renewal, expired-owner
  takeover, owner/token-qualified release, and a final ownership assertion
  before status publication. Lost ownership produces a reconciliation-required
  block and no new status publication. Focused scheduler, restart, overlap,
  daily-operation, autonomous-operator, and multi-asset reconciliation tests
  pass **42/42**. Deployment creates one mutable coordination table
  automatically; it is not canonical portfolio state and is not added to
  backups. Rollback requires pausing the operator first; the prior binary may
  ignore but must not delete the lease database. CIO, construction, governance,
  paper-only scope, and real-money authority are unchanged.

## PR8 — Real Streamlit browser, mobile, and visual regression testing

- **Invariant:** public/private controls and four-screen explanations remain usable and correctly separated on desktop and current iPhone-sized viewports.
- **Files/state:** browser test harness, fixtures, visual baselines, accessibility selectors, CI; no production state.
- **Acceptance:** real Streamlit server tested at desktop and mobile widths; anonymous sees no private controls; key text/layout and navigation stable; no horizontal-blocking critical controls.
- **Tests:** browser interaction, screenshots/visual diff, accessibility, session transition.
- **Deployment/migration:** new CI gate only.
- **Rollback:** make visual gate advisory only for a documented tooling incident, never remove authorization tests.
- **Authority change:** none.
- **Implementation record:** CI now installs Playwright Chromium, starts a real
  Streamlit server, and tests desktop `1440×1000` plus current compact-iPhone
  `390×844` viewports. It traverses all four screens, checks the anonymous
  viewer/private-control boundary on every screen, measures horizontal
  overflow and mobile navigation target height against the versioned
  `streamlit-layout-v1` baseline, and uploads full-page screenshots plus layout
  JSON. Mobile navigation targets are raised to at least 42 px. The ordinary
  local suite passes **18** related tests and skips the **2** opt-in browser
  cases. This workspace could not download Chromium because its proxy returned
  a truncated zero-byte archive; therefore the real-browser GitHub Actions gate
  remains mandatory before merge. No production state or authority changes.
  Rollback may revert the CSS/baseline and make only the visual comparison
  advisory for a documented browser-tool outage; authorization interaction
  checks must remain required.

## PR9 — Golden end-to-end and chaos scenarios

- **Invariant:** the complete path either appends one correct reconciled paper state or makes no change.
- **Files/state:** golden fixtures, test harness, chaos injectors, all path adapters; isolated temporary DBs only.
- **Acceptance:** buy/increase/hold/reduce/exit/no-change; stale/missing data; provider outage; crash/restart; partial fill; backup/restore; Alpaca separation; live endpoint denial.
- **Tests:** behavioral end-to-end and failure-mode tests, not source assertions.
- **Deployment/migration:** required CI gate; no production migration.
- **Rollback:** revert harness only if invalid, preserving the failing scenario as an issue/fixture.
- **Authority change:** none.

- **Implementation record:** `config/golden_end_to_end_scenarios.json` is the
  executable scenario authority and the CLI `golden-gate` command derives its
  result from 15 explicit behavioral pytest nodes. The gate covers CIO buy,
  increase, reduce, exit and no-opportunity outcomes; construction through
  canonical reconciled fills; exact replay; partial-fill recovery; stale and
  provider failure; point-in-time mismatch; overlap/lost-fence restart safety;
  encrypted restoration; separate Alpaca paper transport; and live Alpaca
  endpoint rejection. The report records the executed nodes and cannot accept
  a self-declared pass. The focused gate passes **15/15** plus **3/3** harness
  contract tests. It is now an explicit release-validation step and produces a
  retained CI artifact. Only isolated test databases are affected; there is no
  migration and no CIO, construction, governance, execution, or real-money
  authority change. Rollback removes the gate while preserving any failing
  scenario evidence for diagnosis.

## PR10 — Event-intelligence quality and portfolio-impact mapping

- **Invariant:** events remain educational evidence and reach CIO context only through benchmarked, provenance-preserving quality gates; they never authorize a change.
- **Files/state:** public information models/pipeline, daily intelligence, exposure map, benchmark dataset/annotations, UI explanation, evaluation tests; new append-only event-cluster/version records.
- **Acceptance:** semantic clusters, novelty, independent-source corroboration, event materiality, market confirmation, entity/asset/portfolio exposure, plain-language portfolio lens; benchmark precision/recall and calibration thresholds recorded.
- **Tests:** duplicate/syndicated stories, conflicting sources, false entity match, no market confirmation, benchmark regression, non-authorization.
- **Deployment/migration:** versioned quality schema; old records remain readable but uncertified.
- **Rollback:** disable new intelligence version and fall back to educational unclustered display; CIO gate remains fail closed.
- **Authority change:** information quality only; CIO/construction/execution/real-money authority unchanged.
- **Implementation record:** `intelligence/event_quality.py` provides
  deterministic semantic clustering, novelty, independent-source
  corroboration, event materiality, market confirmation, exact entity and
  instrument exposure mapping, simple portfolio explanations, and an
  idempotent append-only cluster store. The educational UI uses clustered
  representatives but never consumes the CIO-review flag as authority. The
  versioned five-case benchmark scores precision/recall above its 0.80 floors.
  Product owner LeVon Mendall approved all five labels on 2026-07-31, so the
  release command now passes `--require-certified`. Focused event and briefing
  tests pass **13/13**. Persistent state is a new append-only event-cluster DB
  only when explicitly configured; old records stay readable. Rollback removes
  the clustering/ranking adapter and leaves unclustered educational display;
  it cannot relax CIO readiness. No CIO, construction, execution, or
  real-money authority changed.

## PR11 — Provider coverage and historical certification

- **Invariant:** monitored, decision-certified, and allocatable scopes are distinct and every historical decision uses only then-available certified data.
- **Files/state:** provider manifests/certificates, security master, PIT evaluation, historical sources, coverage UI/API, certification ledger/tests.
- **Acceptance:** domain/market/provider/era matrix; macro vintages, filings/revisions, delistings, actions, membership, liquidity, calendars and provider-availability boundaries certified or explicitly blocked; pilot scope labeled.
- **Tests:** future-data leakage, survivorship, revision, action, membership, provider-before-availability, blocked-market allocation.
- **Deployment/migration:** append-only certification versions; no market becomes allocatable merely by migration.
- **Rollback:** deactivate certificate version and fail closed.
- **Authority change:** governance/data eligibility only; CIO remains sole action authority; no real-money authority.
- **Implementation record:** `governance/coverage_certification.py` and two
  versioned registries make monitored, decision-certified, and allocatable
  scope machine-distinct. Only the 15 explicitly named U.S.-listed pilot
  wrappers are allocatable; direct crypto and every other broad direct market
  remain monitored and blocked. Historical certification now requires all
  eight named domains and rejects missing boundaries, future-known revisions,
  provider use before availability, weak revision safety, and survivorship
  gaps. The honest production baseline marks every unresolved domain blocked,
  research-only, and ineligible for performance claims/policy promotion.
  Read-only API routes disclose both matrices. Focused behavioral and
  failure-mode tests cover each domain, blocked allocation, future leakage,
  revision, survivorship, provider boundaries, API disclosure, and append-only
  persistence. Deployment adds optional append-only coverage evidence state;
  no existing data is rewritten. Rollback removes the readers/registry version
  and must retain the blocked historical posture. CIO authority and real-money
  authority are unchanged.

## PR12 — Formal paper experiment and multi-week soak-test launch

- **Invariant:** paper results cannot change thresholds/policies or support performance claims outside a pre-registered, versioned, governed experiment.
- **Files/state:** experiment protocol/schema/store, launch/readiness policy, reporting/evaluation, soak operations, tests; append-only experiment registrations and observations.
- **Acceptance:** frozen hypothesis, universe, providers, costs, schedule, metrics, benchmark, duration/cycle minimums, failure/missing-data rules, change-control, review/promotion prohibition; readiness passes before start.
- **Tests:** mid-run config drift, missing observation, restart, benchmark reconstruction, attempted automatic threshold promotion.
- **Deployment/migration:** launch new experiment ID only after PR1-PR11 production gates and exact deployed SHA verification.
- **Rollback:** pause experiment, preserve observations, record termination; never erase or silently restart.
- **Authority change:** governed research protocol only; no direct policy promotion, CIO change, or real-money authority.
- **Implementation record:** `config/paper_experiment_protocol.v1.json` freezes
  one six-week, 30-cycle experiment for the $250,000 `COMPOUNDING` portfolio,
  including the 15-instrument universe, provider manifest, costs, benchmark,
  schedule, metrics, missing-data rules, eleven failure scenarios, and
  terminate-and-reregister change control. Registration requires every PR1-PR11
  gate, real desktop/mobile browser evidence, a human-approved event benchmark,
  and equality between the exact Render SHA and experiment code SHA. The
  append-only store is restart-idempotent; evaluation blocks protocol/code
  drift, duplicate dates, excess missing data, unreconciled state, and an
  unreconstructable benchmark. Completion still awaits human review and cannot
  tune thresholds, promote policy, make performance claims, or authorize real
  money. Focused experiment/campaign/launch tests pass **25/25**. Deployment
  creates `paper-experiment.db` only after all launch prerequisites pass; no
  experiment has been launched prematurely. Rollback terminates the
  registration, preserves all events, and registers a new version.
