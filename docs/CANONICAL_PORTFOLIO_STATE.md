# Canonical Portfolio State

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

`SQLiteCanonicalPortfolioStore` is the only active source for cash, positions, valuation history, and implementation events. Each complete snapshot is append-only, canonical-JSON encoded, and linked in a contiguous SHA-256 chain.

The authenticated application, production API, backups, and compatibility reporting facade read this store. They do not seed or mutate the retired mandate/trading database.

## Migration

```bash
python run_portfolio_migration.py \
  --legacy-db database/capital_intelligence.db \
  --canonical-db database/canonical_portfolio.db \
  --as-of 2026-07-27T00:00:00+00:00
```

Migration opens the legacy database in query-only mode and appends one complete canonical snapshot for each historical portfolio. Exact replay is idempotent. Conflicting reuse is rejected.

## Implementation updates

Canonical paper execution is the only implementation authority permitted to append a later state snapshot. Legacy `core.trading` remains offline migration/test code and is not imported by the active app, API, scheduler, or paper executor.
