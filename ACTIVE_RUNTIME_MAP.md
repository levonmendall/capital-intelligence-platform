# Active Runtime Map

## Render configured runtime

```text
Render branch main / Docker build context .
  -> dockerCommand: python run_render_service.py
  -> initialize.py (must succeed)
  -> supervisor children sharing /app/database
       api                  uvicorn api.app:create_app --factory :8000
       cio-paper-operator   python run_autonomous_paper_operator.py --loop
       historical-backfill python run_historical_backfill.py --loop
       encrypted-backup    python run_backup.py --loop
       streamlit            python -m streamlit run render_app.py :$PORT
```

API, autonomous paper operator, and Streamlit are critical supervisor children.
Historical backfill and encrypted backup are restarted after bounded delay. Render's
external health probe targets the Streamlit `/_stcore/health` endpoint; the supervisor
also owns child-process health and restart behavior.

### Layered readiness control plane

Readiness is explicitly separated into four dependency-closed observational layers:

```text
SERVING_READY
  -> EVIDENCE_READY
       -> DECISION_READY
            -> EXECUTION_READY
```

`SERVING_READY` is the watchdog/restart boundary. It requires the canonical
portfolio and CIO journal to remain readable, required identity state to be ready,
and an exact production Git SHA. Provider degradation, stale evidence, an
incomplete universe, stale operator evidence, reconciliation blockers, backup
freshness, alert delivery, or execution conditions cannot by themselves take the
read-only product offline.

`EVIDENCE_READY` reports whether the currently required evidence/universe inputs are
available and fresh. `DECISION_READY` additionally requires the CIO/operator decision
boundary to be available against that certified evidence and canonical state.
`EXECUTION_READY` retains reconciliation, backup, dependency, and the prior strict
composite production-operational gates. Dependency closure is fail-closed: a blocked
upstream layer forces all dependent downstream layers blocked. The report grants no
authority and always records `paper_only=true`, `real_money_authorized=false`, and
`downstream_repair_authorized=false`.

The API contracts are:

- `/ready` — credential-safe `SERVING_READY`, used by the production watchdog.
- `/ready/composite` — the previous strict readiness semantics, retained for
  operational/investment diagnostics.
- `/ready/layers` — credential-safe four-layer state; only `SERVING_READY=false`
  returns HTTP 503.
- `/v1/readiness/status` — administrator detail including strict and layered state.

No downstream consumer may make itself ready by synchronously repairing an upstream
state. The evidence owner refreshes evidence; the CIO consumes certified state;
construction consumes a CIO action; execution consumes approved construction.

## Active Streamlit composition

```text
render_app.py
  -> imports secure_app, app_impl, presentation refinements, and read adapters
  -> secure_app.create_streamlit_application(...)
       -> authenticate and bind the authorized session principal
       -> provide typed, read-only portfolio and operating dependencies
       -> render_app composes the four product surfaces through ordinary calls
            Portfolio | Today | Environment | History
       -> read current canonical portfolio, CIO, market, event, and operating state
       -> expose paper-status and administrator controls without trade authority
```

No active Streamlit entrypoint reads, rewrites, compiles, monkey-patches, or executes
another Python source file. `render_app.py`, `secure_app.py`, and `app_impl.py` are
ordinary imported modules. The removed `streamlit_paper_execution_worker.py` is not an
execution path; paper implementation is owned by the headless operator.

### Canonical presentation ownership

| Surface / concern | Active owner | Supporting runtime boundary |
| --- | --- | --- |
| Today presentation | `today_trust_ui_runtime.py` | `today_story_retention_runtime.py` owns retained-story data lifecycle only; `today_event_alignment_runtime.py` and public-event recency supply aligned source context. |
| Environment presentation | `environment_mobile_clarity_runtime.py` | `environment_story_placement_refinement.py` provides the base story API. `environment_driver_education_runtime.py` and `environment_actionable_learning_refinement.py` remain helper providers and do not install presentation from the entrypoints. |
| Portfolio presentation | `portfolio_ui_refinement.py` | No `portfolio_first_ui_refinement.py` runtime fallback remains in the canonical entrypoints. |
| History presentation | `history_ui_refinement.py` / historical navigation runtime | Historical reads remain presentation-only and do not authorize portfolio changes. |
| Primary-surface route isolation | `surface_route_isolation_runtime.py` | Owns navigation tracking, stale-fragment suppression, and synchronous Render targets only. It does not install Today or Environment presentation. |

Both `app.py` and `render_app.py` explicitly install the final Environment renderer,
then Today retention adapters, then the final Today renderer, before route isolation.
The superseded `today_development_card_format_runtime.py` presentation layer has been
removed. Retention, recency, educational helpers, and route guards remain separate
from final surface presentation so each concern has one runtime owner.

### Non-authoritative compounding aspiration

`compounding_aspiration.py` defines a 5% monthly stretch-compounding reference for
performance review and investor education. `portfolio_ui_refinement.py` consumes that
reference only for Portfolio presentation. The governed objective remains maximizing
long-term compounded returns after costs.

The aspiration is not an input to opportunity qualification, CIO ranking, sizing,
portfolio construction, or execution. Falling behind the reference triggers process
review only: opportunity capture, evidence quality, construction efficiency, and
possible false conservatism may be examined, but the reference cannot force a trade,
override cash, relax risk or evidence standards, lower thresholds, or authorize
catch-up risk-taking.

## Active FastAPI composition

```text
uvicorn api.app:create_app --factory
  -> ApiSettings + explicit repository resources
  -> AuthenticationService and identity store
  -> operational middleware, metrics, and SLO service
  -> public health / operations / provider-validation routes
  -> authenticated CIO, daily, environment, analytical, governance,
     decision, replay, alert, and canonical-portfolio read surfaces
```

Discontinued Personal CIO, investor-objective, and personalization routes are not
mounted and have been removed from the active repository.

## Headless investment and paper-operating graph

```text
run_autonomous_paper_operator.py --loop
  -> collect public information when due
  -> evaluate material-change and cross-market leadership triggers
  -> prepare certified complete-universe and production context
       -> broad/global discovery and cheap first-pass screening
       -> persist exact active-paper-universe publication
       -> persist completed full-universe screening publication
       -> ProductionCapabilityAuthority
            -> build exact point-in-time InstrumentCapabilityEvidence
            -> Universal Capability Graph evaluation
            -> append certification/suspension through AutomaticInstrumentEligibilityFactory
            -> persist production-capability-authority.json
  -> bind production decision authority at the exact CIO timestamp
       -> bootstrap instruments OR currently active exact capability certifications
       -> provider visibility/profile completeness alone cannot create ownership authority
  -> run scheduled or triggered GlobalOpportunityRotationCanonicalCIOCycle
       -> opportunity qualification
       -> common annualized marginal-compounding-value comparison across asset families
       -> cross-market/global opportunity ranking
       -> exactly six specialist analyses
       -> committee synthesis
       -> CIO-only decision and initial target
       -> joint marginal-capital preview
       -> independent portfolio construction
       -> CIO-to-construction reconciliation
  -> publish pending construction
  -> attempt governed internal paper implementation
       -> preserve complete active publication for safe reduction/exit continuity
       -> new/increased dynamic exposure requires active exact capability certification
       -> normalize paper intent by structural asset family
            equities/funds -> shares
            fixed income   -> face-value units
            futures/options -> contracts
            FX             -> base-currency units
            crypto         -> asset units
       -> canonical multi-asset session/quote/liquidity/cash/fill/accounting controls
       -> universal quantity/lifecycle invariant must reconcile to the actual fill
  -> reconcile fills and publish canonical portfolio state
  -> publish alerts, thesis monitoring, learning evidence, and heartbeat
```

This is the only supported process that may implement paper transactions. Streamlit
and FastAPI project governed state but do not independently authorize or execute a
portfolio change. The Universal Capability Graph and automatic eligibility factory
may grant or suspend *paper eligibility* only; they cannot issue a CIO action or size
capital. The universal paper contract constrains paper execution but cannot originate
a trade. Live-money authority remains disabled.

### Global opportunity reassessment

The live reassessment scanner retains its schedule, deduplication, cooldown, market,
company, and thesis-dependency controls and additionally measures relative leadership
across the active opportunity set. A sufficiently large change in cross-market
leadership may request a fresh canonical CIO cycle. It cannot manufacture a candidate,
recommendation, target weight, construction, or fill.

Global rotation readiness is audited across both economic domains and geography. The
domain matrix covers equity, fixed income, credit, currencies, commodities, crypto,
real estate, volatility/derivatives, and alternatives. The geographic matrix separately
tracks North America, Europe, Japan, developed Asia-Pacific, and emerging markets,
with global/non-geographic exposures tracked independently. Coverage reporting has no
investment authority.

## Historical, backup, and operational paths

```text
run_historical_backfill.py --loop
  -> point-in-time historical replay and advisory learning
  -> no automatic threshold or policy promotion

run_backup.py --loop
  -> encrypted backup of canonical databases and required evidence stores

Documented CLI / CI commands
  -> provider certification, replay, recovery, smoke, and readiness operations
  -> operational tools only; they are not resident investment authorities
```

## Active versus retired classification rule

- **Active:** reachable from a declared deployment entrypoint, application factory,
  canonical stage binding, or imported production module.
- **Operational tool:** intentionally invoked through a documented CLI or CI workflow
  but not resident in the Render supervisor.
- **Compatibility:** still imported to preserve a supported contract; compatibility
  code may be consolidated but is not dead code.
- **Retired:** unreachable from supported topology and no longer required by an active
  behavioral contract. Retired executable code is deleted and preserved through Git
  history, with a Markdown removal manifest under `archive/`.
- **Unknown:** not yet proven active, operational, compatible, or retired. Unknown code
  may not be deleted without import, entrypoint, workflow, and test-ownership evidence.

## Current authority boundaries

- One canonical `$250,000` `COMPOUNDING` paper portfolio.
- Exactly six advisory specialists.
- CIO-only investment authority.
- Risk-adjusted CIO initial target followed by independent construction.
- Universal Capability Graph can grant/suspend dynamic *paper eligibility* only.
- Universal paper contract constrains structural paper quantity/lifecycle only.
- Fail-closed, point-in-time, append-only evidence and lineage.
- Reconciled paper-only execution with safe exit continuity.
- No live-money authority.
