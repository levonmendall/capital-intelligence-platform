# Active Runtime Map

## Render configured runtime

```text
Render branch main / Docker build context .
  -> dockerCommand: python run_render_service.py
  -> initialize.py (must succeed)
  -> supervisor children sharing /app/database
       api                 uvicorn api.app:create_app --factory :8000
       cio-paper-operator  python run_autonomous_paper_operator.py --loop
       historical-backfill python run_historical_backfill.py --loop
       encrypted-backup    python run_backup.py --loop
       streamlit            python -m streamlit run render_app.py :$PORT
```

API, operator, and Streamlit are marked critical by the supervisor. Backfill and backup are restarted after bounded delay. Render currently probes only the Streamlit endpoint `/_stcore/health`.

## Streamlit call graph on main

```text
render_app.py
  read/compile/exec secure_app.py
    AuthenticationService + session handling
    rewrite/compile/exec app.py with authorized portfolio bindings
      reload + monkey-patch premium_ui
      read/transform/compile/exec app_impl.py
        Today | Environment | Portfolio | History
      invoke streamlit_paper_execution_worker
  append Render deployment identity + administrator smoke-test dialog
```

This graph is active technical debt. PR3 must replace it with normal imports and one application factory without changing investment behavior.

## Headless operating graph

```text
run_autonomous_paper_operator.py --loop
  -> public information collection if due
  -> material-change reassessment
  -> production context preparation / complete-universe gate
  -> scheduled or triggered CanonicalCIOCycle
  -> pending construction publication
  -> governed internal paper execution attempt
  -> reconciliation and canonical state publication
  -> alerts, after-close learning, heartbeat
```

PR2 must make this the only process allowed to implement paper transactions. Streamlit becomes a read-only projection.

## Active versus legacy classification rule

- Active: reachable from a declared environment entrypoint, stage binding, application factory, or imported production module.
- Operational tool: intentionally invoked through a documented CLI/CI workflow but not resident.
- Compatibility: imported only to maintain an old module contract.
- Legacy: not reachable from a supported topology and not required by a behavioral test.
- Unknown: not yet proven either way; unknown code may not be deleted.

The repository-wide classification is a PR5/PR7 deliverable. Root-script count at this baseline is 87.
