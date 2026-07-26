# Technical and Momentum Intelligence Engine

## Purpose

The Technical and Momentum engine measures the observed persistence, breadth of
time horizons, volatility pressure, and drawdown state of one explicitly
configured benchmark.

It answers:

> Are price trends reinforcing or weakening the current market environment, and
> how dependable is that evidence?

It does not answer:

- what the benchmark is worth;
- what return the benchmark will earn;
- whether an investor should buy or sell;
- what trade should be placed; or
- whether a portfolio is suitable for an investor.

Those decisions remain governed by the Personal CIO, investor objectives,
portfolio constraints, committee policy, and later multi-engine synthesis.

## Versioned policy

The first policy is:

```text
technical-momentum-policy.v1
```

Changing a horizon, scale, component weight, confirmation rule, or stress rule
requires a new version. Historical results are not silently recalculated under
new rules.

## Data contract

The engine consumes an immutable provider export using:

```text
technical-momentum-input.v1
```

The export contains:

```json
{
  "schema_version": "technical-momentum-input.v1",
  "provider": "licensed_provider",
  "source_identifier": "benchmark-history:2026-01-31",
  "benchmark": "US_EQUITY_BENCHMARK",
  "instrument_id": "provider-neutral-instrument-id",
  "venue": "XNYS",
  "currency": "USD",
  "methodology_version": "raw-close.v1",
  "retrieved_at": "2026-01-31T21:00:00+00:00",
  "bars": []
}
```

Each bar must retain:

- instrument identity;
- venue;
- currency;
- interval start and end;
- open, high, low, close, and volume;
- observation timestamp;
- retrieval timestamp;
- provider quality state; and
- provider record identity when available.

The complete file receives a SHA-256 fingerprint. That fingerprint is included
in analytical evidence lineage.

## Point-in-time rules

The engine uses only bars whose interval and observation timestamp are at or
before the requested decision time.

When two records share an interval end, the record with the later retrieval
timestamp is selected. Future bars are excluded.

No synthetic price, interpolation, current-market substitution, or sample quote
is used when evidence is absent.

The configured history must disclose its adjustment methodology. The first
engine does not independently reconstruct split- or dividend-adjusted history.
A licensed provider export must identify the named methodology used.

## Components

### One-month momentum

Measures the total close-to-close return over 20 sessions.

The signal reaches its positive or negative bound at approximately an 8% move.
The scale is a scoring convention, not a forecast threshold.

### Three-month momentum

Measures the total return over 63 sessions with a 15% scoring scale.

### Six-month momentum

Measures the total return over 126 sessions with a 25% scoring scale.

### Twelve-month momentum

Measures the total return over 252 sessions with a 40% scoring scale.

### Trend alignment

Combines:

- price relative to its 50-session average;
- price relative to its 200-session average; and
- the 50-session average relative to the 200-session average.

This prevents a single moving-average relationship from defining the whole
trend conclusion.

### Volatility pressure

Calculates 20-session annualized realized volatility and ranks it against prior
20-session volatility windows available in the same point-in-time history.

Higher volatility pressure reduces technical support. Low volatility may
support trend persistence, but it cannot independently create an expanding
conclusion.

### Drawdown state

Measures the current close relative to the highest close in the latest
252-session window.

A benchmark close to its high receives more technical support. A material
drawdown reduces support and contributes to the confirmed-stress rule.

## Classification

The shared directional contract is retained:

- `expanding`: technical support is broad and persistent;
- `neutral`: evidence is mixed or transitional;
- `contracting`: trend and momentum support are weakening;
- `stressed`: a broad technical breakdown is confirmed; or
- `unavailable`: no defensible point-in-time conclusion can be produced.

An expanding conclusion requires:

- a sufficiently positive composite;
- at least four supportive components;
- positive trend alignment;
- confirmation from six- or twelve-month momentum; and
- no materially negative drawdown state.

A short-term rebound cannot independently produce an expanding conclusion.

A stressed conclusion requires:

- a deeply negative composite;
- at least four negative components;
- negative trend alignment; and
- material drawdown pressure.

One weak horizon or one volatile session cannot independently produce stress.

## Coverage, quality, and confidence

Each component has a fixed policy weight.

Missing history removes that component from scoring and lowers total coverage.
It is never imputed.

The result is:

- `current` when coverage is complete and evidence is fresh;
- `incomplete` when one or more components lack sufficient history;
- `stale` when the latest observation is too old or explicitly stale; or
- `unavailable` when no defensible assessment can be produced.

Confidence combines:

- weighted coverage;
- provider quality; and
- agreement between components.

Confidence is not a probability that the trend will continue.

## Production configuration

The repository does not yet enable a licensed benchmark price-history feed.
Without one, the engine publishes an explicit unavailable result and the core
daily cycle continues.

Configure an immutable source with:

```bash
export CAPITAL_INTELLIGENCE_TECHNICAL_MOMENTUM_FILE=/data/technical-momentum.json
```

Run the configured engine:

```bash
python run_technical_momentum.py
```

Run a historical point-in-time assessment without persistence:

```bash
python run_technical_momentum.py \
  --data-file /data/technical-momentum-2026-01-31.json \
  --as-of 2026-01-31T21:00:00Z \
  --no-persist
```

## API

Authenticated read-only routes:

```text
GET /v1/technical-momentum/latest
GET /v1/technical-momentum/history?limit=30
```

The API does not expose a mutation or execution route.

## Personal CIO integration

The result contributes to:

- why the market path matters;
- how momentum, volatility, and drawdown can affect portfolio behavior;
- review conditions;
- evidence lineage; and
- objective-aware alert explanations.

It does not independently change the formal action or no-action outcome.

## Safety boundaries

The engine produces no:

- buy or sell instruction;
- entry or exit level;
- stop-loss level;
- price target;
- expected-return forecast;
- market-timing promise;
- portfolio mutation;
- order;
- trade; or
- committee decision.

Technical conditions describe the observed market path. They do not replace
valuation, macroeconomic evidence, portfolio policy, or human judgment.
