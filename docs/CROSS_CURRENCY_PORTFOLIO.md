# Canonical Cross-Currency Portfolio State

## Governing rule

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

Crypto, FX, and global listed markets can be compared fairly only when every holding and cash balance is valued in one canonical portfolio base currency while preserving its local economic facts.

## Authority

`SQLiteCanonicalPortfolioStore` remains the only active authority for portfolio cash, currency balances, holdings, valuation history, and implementation lineage. This change extends that authority; it does not create a second multi-asset portfolio database.

The default portfolio base currency is `USD`. A snapshot preserves:

- base-currency cash;
- non-base cash or unlevered currency balances;
- stable instrument identifier;
- venue;
- asset class;
- local price and settlement currencies;
- local quantity, mark, acquisition cost, and value;
- point-in-time FX conversion rate;
- FX observation timestamp and source identifier;
- preserved acquisition cost in base currency;
- base-currency market value, cost basis, and unrealized result; and
- the same information for paper implementation records.

## Valuation

The canonical NAV is:

```text
base-currency cash
+ translated non-base cash balances
+ translated position market values
```

The system does not overwrite local prices with converted prices. Both are retained so later attribution can separate asset return from currency return.

For a non-base-currency position, the snapshot fails closed unless it has:

- an FX rate to the base currency;
- an FX observation timestamp not later than the portfolio timestamp;
- an immutable FX source identifier; and
- the original acquisition cost already preserved in base currency.

Using the current FX rate to reconstruct historical acquisition cost is prohibited.

## Cash and spot FX boundary

`cash_amount` is base-currency cash only. `CanonicalCurrencyBalance` stores a non-base, unlevered cash balance. The base currency may not also appear in `currency_balances`, preventing double counting.

This is the required state substrate for later spot-FX paper execution. It does not yet authorize margin, leverage, forward points, swaps, options, or synthetic notional exposure.

## Identity boundary

A position may preserve both a display symbol and a stable instrument identifier plus venue. Stable instrument identifiers must be unique within a snapshot. This prevents the same symbol on different venues—or different economic instruments with similar symbols—from being silently merged.

Legacy USD snapshots remain readable. Missing new fields default to USD, an FX rate of 1.0, and unknown asset metadata. New non-USD positions cannot use those defaults.

## Product boundary

Portfolio and History read models now expose local and base values, currency balances, conversion lineage, and base-currency implementation costs. The user must be able to distinguish:

- local asset performance;
- currency translation;
- base-currency portfolio contribution; and
- paper implementation costs.

The system remains paper-only, development remains open, and this state contract does not declare any expanded market test ready.
