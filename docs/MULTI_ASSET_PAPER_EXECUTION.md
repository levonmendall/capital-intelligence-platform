# Multi-Asset Paper Execution

## Governing rule

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

## Purpose

The multi-asset execution authority measures whether a governed canonical construction can be implemented across crypto, unlevered spot FX, and international listed markets under their actual session, currency, liquidity, cost, custody, and identity boundaries.

It is paper-only. It cannot connect to a broker, submit or cancel a live order, borrow, create margin, use leverage, trade derivatives, change the CIO action, or alter construction targets.

## One instrument authority

Execution consumes the same `MultiAssetInstrumentProfile` used by governed portfolio construction. It does not create a second execution profile with competing identity or approval fields.

The shared profile preserves:

- stable instrument identity and symbol;
- asset class, venue, and jurisdiction;
- price and settlement currencies;
- paper-eligibility approval;
- unlevered and spot-only boundaries;
- custody or settlement authority; and
- execution-model version.

`MultiAssetExecutionPolicy` owns only paper-fill assumptions such as quote freshness, volume participation, commissions, fractional quantity behavior, minimum trade value, and reconciliation tolerance. It cannot change instrument eligibility or construction targets.

## Session routing

- Crypto uses a continuous 24/7 session model.
- Spot FX uses a continuous 24/5 session model.
- International equities use their local exchange session.

A closed, holiday, or maintenance session holds the affected paper order. It does not manufacture a quote or route the order through the U.S. equity calendar. Other open-market orders may execute in the same batch, producing a reconciled partial batch that can later resume from the exact canonical ending state.

## Quote and FX evidence

Every open instrument requires one exact quote with:

- matching symbol, instrument, and venue;
- bid, ask, and last price;
- available base-currency notional;
- quote currency;
- point-in-time FX rate to portfolio base currency;
- quote and FX observation timestamps;
- quote and FX source identifiers;
- quote certification; and
- halt state.

Missing, extra, mismatched, stale, future-known, or identity-inconsistent evidence blocks execution. A halted instrument is rejected without creating a fill. Base-currency quotes must use an FX rate of `1.0`.

## Unlevered fills

Requested notional is the construction trade weight multiplied by canonical base-currency NAV. Quantity is capped by:

- approved volume participation;
- available base-currency cash for buys;
- owned quantity for sells;
- the construction result already approved by the multi-asset construction authority; and
- the execution policy's fractional-quantity rule.

Cash cannot become negative. Spot FX remains an unlevered owned paper instrument; no synthetic or margin notional is permitted.

## Cross-currency state and lineage

Fills preserve local price, local gross value, base-currency gross value, commission, spread cost, FX rate, quote source, FX source, quote certification, venue, instrument identity, approval, custody or settlement identity, and execution-model version.

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

`SQLiteMultiAssetPaperExecutionStore` keeps an append-only SHA-256 event chain. Every attempt has a distinct immutable start and completion record.

A held batch may retry from the same portfolio state. A partially filled batch must resume from its exact prior ending snapshot. Fully filled trades are not repeated, remaining notional is calculated from the original request, and completed or no-action batches replay idempotently.

## Command

```bash
python run_multi_asset_paper_execution.py \
  --construction artifacts/construction.json \
  --profiles artifacts/multi-asset-instrument-profiles.json \
  --decision-identifier decision:example \
  --session-provider production_multi_asset_sessions:create_provider \
  --quote-provider production_multi_asset_quotes:create_provider \
  --as-of 2026-07-27T16:00:00+00:00 \
  --require-complete
```

Providers and credentials remain deployment boundaries. The repository does not contain a broker adapter or claim that any real expanded market has been activated. Development remains open, real-money execution remains unavailable, and test readiness must be evaluated against an immutable baseline rather than inferred from this implementation alone.
