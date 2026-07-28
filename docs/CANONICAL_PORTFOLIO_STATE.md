# Canonical Portfolio State

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

`SQLiteCanonicalPortfolioStore` is the only active source for cash, positions, valuation history, and implementation events. Each complete snapshot is append-only, canonical-JSON encoded, and linked in a contiguous SHA-256 chain.

The authenticated application, production API, construction engine, rebalancing, paper execution, backups, and reporting read or append through this canonical authority. They do not seed, mutate, or treat the retired mandate/trading database as current state.

All active portfolio decisions use the sole `COMPOUNDING` investment mandate. Cash, concentration, liquidity, leverage, turnover, cost, and restricted-exposure rules are implementation constraints recorded with portfolio state; they are not separate portfolio objectives.

## Migration

```bash
python run_portfolio_migration.py \
  --legacy-db database/capital_intelligence.db \
  --canonical-db database/canonical_portfolio.db \
  --as-of 2026-07-27T00:00:00+00:00
```

Migration opens the legacy database in query-only mode and appends one complete canonical snapshot for each historical portfolio record. Exact replay is idempotent. Conflicting reuse is rejected. Historical strategy labels remain migration evidence only and cannot create a new active mandate or portfolio authority.

## Implementation and valuation updates

Canonical paper execution appends reconciled fill snapshots. The governed mark-to-market service may append a later valuation-only snapshot after validating complete current quote and FX coverage. Governed cash-flow and position-adjustment services may append evidenced income, expense, external-flow, lifecycle-cash, and share-split snapshots. Each path preserves the same append-only authority and accounting identity.

Legacy `core.trading` remains offline migration/test code and is not imported by the active app, API, scheduler, construction engine, rebalancer, paper executor, backup path, or reporting facade.

See [Canonical performance accounting](PERFORMANCE_ACCOUNTING.md).

## Failure boundary

Missing, incomplete, or chain-invalid canonical portfolio state must fail closed. Active services may not reconstruct a substitute from the retired database, synthetic holdings, or a goal-oriented mandate configuration.
