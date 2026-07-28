# Canonical performance accounting

## Purpose

The canonical portfolio now separates portfolio value from the accounting components that created it. Every reported gain or loss is derived from append-only portfolio snapshots, preserved average cost, exact fills, point-in-time marks, FX evidence, and evidenced non-trade cash events.

This is paper-performance accounting. It is not tax accounting, a brokerage statement, or real-money authority.

## Accounting basis

The system uses **average-cost book accounting** for paper positions. Every buy updates local- and base-currency average cost, including commission. Every sell relieves the proportional average cost and records net realized profit or loss after commission.

For each open position:

```text
unrealized P&L = current base-currency market value - preserved base-currency cost basis
```

For each sell:

```text
realized P&L = base-currency sale proceeds - commission - relieved base-currency cost basis
```

For the portfolio:

```text
total P&L = NAV - starting capital - net external capital flows
```

The portfolio also preserves:

- realized P&L;
- unrealized P&L;
- non-base-currency cash FX P&L;
- dividends, interest, coupons, fees, taxes, corporate-action cash, and variation margin;
- contributions and withdrawals, which change NAV but are excluded from investment P&L;
- total fees;
- snapshot-to-snapshot and same-day P&L; and
- an accounting residual that must remain within policy tolerance.


## Existing portfolio history

Portfolio snapshots created before realized-P&L fields existed may contain complete buy and sell fills but show a non-zero accounting residual. Run the deterministic average-cost migration before the first new valuation:

```bash
python run_portfolio_accounting_migration.py \
  --portfolio-database database/canonical_portfolio.db \
  --source-identifier canonical-average-cost-accounting-migration.v1 \
  --output reports/portfolio-accounting-migration.json
```

The migration replays historical buys, sells, and recorded splits, verifies ending quantity and cost basis against the current positions, enriches sell events with relieved basis and realized P&L, and appends a new snapshot. It fails closed when historical fills, income, external flows, or lifecycle events are incomplete; it never invents a balancing gain or loss.

## Continuous mark-to-market

Trade execution is not a sufficient valuation schedule. `run_portfolio_mark_to_market.py` fetches one complete quote set for every current position, validates instrument identity, venue, currency, contract multiplier, quote age, FX age, halt state, and source lineage, then appends a new complete canonical snapshot without requiring a trade.

```bash
python run_portfolio_mark_to_market.py \
  --profiles artifacts/multi-asset-instrument-profiles.json \
  --quote-provider providers.alpaca_paper:create_alpaca_paper_quote_provider \
  --as-of 2026-07-28T20:00:00+00:00 \
  --output reports/portfolio-valuation.json \
  --require-complete
```

The deployment worker should run valuation:

1. before a decision cycle that consumes portfolio state;
2. after any completed or partially completed paper implementation;
3. at least once after the applicable market close; and
4. more frequently during active paper testing when the chosen provider and rate limits permit.

Missing, extra, stale, future-known, halted, or identity-inconsistent marks block publication. Non-base cash requires an exact currency-rate provider. A failed valuation never replaces the latest valid snapshot.

## Non-trade cash effects

Use `run_portfolio_cash_flow.py` to book evidenced cash effects:

```bash
python run_portfolio_cash_flow.py \
  --event-identifier corporate-action:VTI:dividend:2026-07-28 \
  --kind dividend \
  --amount-base 125.40 \
  --source-identifier issuer-distribution:VTI:2026-07-28 \
  --rationale "Qualified cash distribution" \
  --symbol VTI \
  --instrument-identifier instrument:us-etf:vti \
  --as-of 2026-07-28T20:05:00+00:00
```

Supported classifications are dividend, interest, coupon, fee, tax, corporate action, variation margin, contribution, and withdrawal. Contributions and withdrawals are excluded from investment return.

## Share splits

Use `run_portfolio_position_adjustment.py` for evidenced share splits. Quantity and per-unit cost and price change by the split ratio while total market value, total cost basis, and P&L remain unchanged.

```bash
python run_portfolio_position_adjustment.py \
  --event-identifier corporate-action:VTI:split:2026-07-28 \
  --symbol VTI \
  --instrument-identifier instrument:us-etf:vti \
  --split-ratio 2 \
  --source-identifier issuer-action:VTI:split \
  --rationale "Two-for-one share split" \
  --as-of 2026-07-28T20:05:00+00:00
```

Mergers, spin-offs, symbol changes, expirations, exercises, assignments, and physical settlements still require exact instrument-identity and lifecycle adapters. They may not be approximated as ordinary trades.

## Reconciliation boundary

Every paper execution now reconciles both:

- cash and NAV; and
- the change in unexplained accounting residual.

A new execution may preserve a documented legacy residual, but it may not increase or otherwise alter it. Fresh canonical operation is expected to maintain a zero residual within the configured tolerance.

## User-facing reporting

The Portfolio surface exposes:

- NAV;
- total P&L and return;
- realized and unrealized P&L;
- valuation timestamp and residual;
- per-position cost basis, market value, unrealized P&L, and unrealized return;
- per-trade relieved basis, realized P&L, and costs; and
- NAV and P&L history.

The Today surface shows current NAV, cash, total P&L, and same-day P&L.
