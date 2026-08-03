# Dead-code cleanup PR1

This change removes only code proven unreachable from the supported Render, API,
autonomous paper-operator, historical, backup, workflow, and operational-command
entrypoints.

Removed scope:

- discontinued investor goals, memory, Personal CIO briefs, alerts, history, and
  unmounted API routes;
- the disconnected Institutional Market Score v2, shadow approval, score guardrails,
  parallel committee submission, and legacy walk-forward package;
- isolated unused dashboard, formatter, mock-provider, process-lens, retired Today
  placement, and deprecated Streamlit paper-execution compatibility modules;
- one duplicate crypto venue example configuration;
- dedicated obsolete tests, while preserving the active portions of mixed integration
  tests.

No investment policy, threshold, market, committee role, CIO authority, construction
rule, provider gate, execution authority, or live-money boundary changes in this PR.
