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
  -> evaluate material-change triggers
  -> prepare certified complete-universe and production context
  -> run scheduled or triggered CanonicalCIOCycle
       opportunity qualification
       exactly six specialist analyses
       committee synthesis
       CIO-only decision and initial target
       independent portfolio construction
       CIO-to-construction reconciliation
  -> publish pending construction
  -> attempt governed internal paper implementation
  -> reconcile fills and publish canonical portfolio state
  -> publish alerts, thesis monitoring, learning evidence, and heartbeat
```

This is the only supported process that may implement paper transactions. Streamlit
and FastAPI project governed state but do not independently authorize or execute a
portfolio change. Live-money authority remains disabled.

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
- Fail-closed, point-in-time, append-only evidence and lineage.
- Reconciled paper-only execution.
- No live-money authority.
