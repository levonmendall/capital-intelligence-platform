# Removed legacy intelligence stack — 2026-08-03

The following disconnected pre-canonical investment architecture was removed after a
repository-wide import and runtime-entrypoint audit:

- the parallel `intelligence.cio` guidance synthesizer;
- legacy recommendation builder, rules, and recommendation engine;
- forecast, strategy, state, theme, and thesis engines and contracts;
- legacy portfolio-manager and rebalancer contracts;
- old point-in-time observation adapters and decision-discipline helper;
- dedicated tests that exercised only those retired contracts.

The active `intelligence.recommendation` evidence model remains because current
committee, portfolio-fit, monitoring, and reporting paths still use it. The current
`cio` package remains the sole canonical CIO decision authority.

Git history is the source archive. No executable copy is kept under `archive/`.

This cleanup does not alter thresholds, market scope, specialist count, CIO authority,
construction authority, evidence governance, paper execution, or the prohibition on
live money.
