# Global Liquidity Intelligence Engine

## Purpose

PR27 adds the first reusable macro engine beyond the existing economic-regime
model. It measures **U.S.-led global liquidity conditions** and translates the
result into plain-language investment context.

The engine does not claim to measure every source of liquidity in the world.
Its coverage is explicitly limited to the point-in-time series available through
the configured FRED provider.

## Shared analytical-engine contract

Every engine result publishes:

- engine and policy version;
- point-in-time `as_of` and generation timestamps;
- direction, score, confidence, weighted coverage, and data status;
- supporting evidence with provider, series, observation date, release time,
  retrieval time, vintage, and quality state;
- contradictory evidence and missing-series risks;
- portfolio transmission channels; and
- review conditions.

This contract is intended for the later business-cycle, credit-cycle, breadth,
valuation, momentum, and risk engines.

## Inputs

The first policy version uses:

| Component | FRED series | Liquidity interpretation |
|---|---|---|
| Federal Reserve total assets | `WALCL` | Expansion is supportive |
| Reserve balances | `WRESBAL` | Expansion is supportive |
| Treasury General Account | `WTREGEN` | A decline releases liquidity |
| Overnight reverse repo | `RRPONTSYD` | A decline releases liquidity |
| Broad money | `M2SL` | Expansion is supportive |
| Broad U.S. dollar index | `DTWEXBGS` | A decline eases global dollar funding |
| National Financial Conditions Index | `NFCI` | Lower values indicate easier conditions |

Each component has a versioned weight, comparison horizon, direction, and
sensitivity threshold in `global-liquidity-policy.v1`.

## Outputs

The engine reports one of:

- `expanding`
- `neutral`
- `contracting`
- `stressed`
- `unavailable`

The 0–100 engine score is separate from the Capital Intelligence Score. PR27
does **not** change the signature score or committee weights.

Data status is reported independently:

- `current`
- `incomplete`
- `stale`
- `unavailable`

Missing series reduce weighted coverage and confidence. They are never replaced
with synthetic values.

## Personal CIO integration

The latest result at or before the daily decision time is added to:

- the explanation of why the market change matters;
- a plain-language portfolio transmission statement;
- review conditions; and
- evidence lineage.

Liquidity context cannot independently change the formal action outcome in PR27.
It informs the brief without bypassing committee governance, portfolio policy, or
the material-change gate.

## Persistence and operations

Results are stored in the append-only
`database/analytical_engines.db` database. The scheduler runs and stores the
liquidity engine before selective alert planning, allowing the same point-in-time
result to appear in Personal CIO alerts.

The database is:

- included in encrypted backups;
- exposed as an optional readiness component; and
- queried through read-only API endpoints.

## API

```text
GET /v1/liquidity/latest
GET /v1/liquidity/history?limit=30
```

No liquidity endpoint mutates portfolios or executes trades.

## Commands

Run and persist the current engine:

```bash
python run_liquidity.py
```

Run a historical point-in-time assessment without persisting it:

```bash
python run_liquidity.py --as-of 2026-01-31T20:00:00Z --no-persist
```

## Validation boundaries

A result must not:

- use an observation released after its decision time;
- present unavailable inputs as current;
- claim a probability of investment success;
- alter the Capital Intelligence Score in PR27; or
- recommend or execute a transaction by itself.
