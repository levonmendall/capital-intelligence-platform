# Removed legacy code — 2026-08-03

This manifest records code intentionally removed from the active repository after a
repository-wide import, runtime-entrypoint, workflow, and test-ownership audit. Git
history remains the source archive; no executable Python is retained under `archive/`.

## Removed product surfaces

- Investor-specific goals, memory, Personal CIO briefs, alerts, history, and unmounted
  API routes. The product now governs one `COMPOUNDING` paper portfolio with one
  institutional objective.
- The disconnected Institutional Market Score v2, shadow approval, score guardrails,
  parallel committee submission, and legacy walk-forward package.
- Unused dashboard, report-formatting, mock-provider, process-lens, retired Today-story
  placement, and deprecated Streamlit paper-execution compatibility modules.
- The duplicate `config/crypto_venue_bindings.example.json`; the active
  `config/crypto_venue_bindings.free.json` remains canonical.

## Preserved boundaries

This removal does not change investment thresholds, the six-specialist committee,
CIO-only authority, fail-closed evidence, independent portfolio construction,
append-only lineage, reconciled paper execution, or the prohibition on live money.

## Validation requirement

The cleanup is valid only when the complete repository validation, browser/mobile,
historical, provider, paper-readiness, and security gates pass on the cleanup branch.
