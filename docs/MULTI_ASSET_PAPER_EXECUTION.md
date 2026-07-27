# Multi-Asset Paper Execution

## Governing rule

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

## Purpose

The multi-asset execution authority measures whether an approved canonical construction can be implemented across crypto, spot FX, and global listed markets under their actual market-session, currency, liquidity, cost, and identity boundaries.

It is paper-only. It cannot connect to a broker, submit or cancel a live order, borrow, create margin, use leverage, trade derivatives, change the CIO action, or alter construction targets.

## Exact execution profiles

Every construction trade requires exactly one `InstrumentExecutionProfile`. Profiles preserve:

- stable instrument identity and display symbol;
- asset class and venue;
- approved session model;
- price and settlement currencies;
- asset-class governance approval;
- execution certification;
- quote freshness;
- volume participation;
- commissions;
- minimum trade value;
- maximum position weight; and
- fractional-quantity policy.

Expanded-market profiles require an asset-class approval. Any notional multiplier other than `1.0` is rejected.

## Session routing

- Crypto uses a continuous 24/7 session model.
- Spot FX uses a continuous 24/5 session model.
- International equities use their local exchange session.

A closed, holiday, or maintenance session holds the affected paper order. It does not manufacture a quote or route the order through the U.S. equity calendar. Other open-market orders may execute in the same batch, producing a reconciled partial batch that can be retried later.

## Quote and FX evidence

Every open profile requires one exact quote with:

- matching symbol, instrument, and venue;
- bid, ask, and last price;
- available base-currency notional;
- quote currency;
- point-in-time FX rate to portfolio base currency;
- quote and FX observation timestamps;
- quote and FX source identifiers;
- quote certification; and
- halt state.

Missing, extra, mismatched, stale, future-known, halted, or uncertified evidence blocks or rejects the affected activity. Base-currency quotes must use an FX rate of `1.0`.

## Unlevered fills

Requested notional is the construction trade weight multiplied by canonical base-currency NAV. Quantity is capped by:

- approved volume participation;
- available base-currency cash for buys;
- owned quantity for sells;
- maximum position weight; and
- fractional-quantity policy.

Cash cannot become negative. Spot FX is represented as an unlevered owned spot instrument; no synthetic or margin notional is permitted.

## Cross-currency state

Fills preserve local price, local gross value, base-currency gross value, commission, spread cost, FX rate, quote source, FX source, venue, instrument identity, and execution certification.

The ending state is appended to `SQLiteCanonicalPortfolioStore`, which remains the sole active portfolio authority.

## Reconciliation

Before state publication, the authority proves:

```text
ending NAV
= beginning NAV
+ point-in-time mark and FX change
- commissions
- bid/ask execution cost
```

An unreconciled batch publishes no canonical portfolio state.

## Durable retries

`SQLiteMultiAssetPaperExecutionStore` keeps an append-only SHA-256 event chain. Every resumed attempt receives a distinct immutable start record. A held batch may retry from the same state. A batch with fills must resume from the exact prior ending snapshot. Completed and no-action batches replay idempotently.

## Command

```bash
python run_multi_asset_paper_execution.py \
  --construction artifacts/construction.json \
  --profiles artifacts/execution-profiles.json \
  --decision-identifier decision:example \
  --session-provider production_multi_asset_sessions:create_provider \
  --quote-provider production_multi_asset_quotes:create_provider \
  --as-of 2026-07-27T16:00:00+00:00 \
  --require-complete
```

Providers and credentials remain deployment boundaries. The repository does not contain a broker adapter or claim that any real expanded market has been activated.
