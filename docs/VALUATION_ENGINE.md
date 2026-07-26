# Valuation Intelligence Engine

## Purpose

The Valuation engine explains whether a configured U.S. equity benchmark has
more or less valuation support than its own point-in-time history.

It is a market-context engine. It does not value individual companies, publish
price targets, forecast returns, recommend trades, or change committee policy.

## Why yield-oriented measures

The first policy uses measures where a higher number consistently represents
more valuation support:

- earnings yield;
- free-cash-flow yield;
- sales yield;
- book-value yield;
- dividend yield; and
- equity risk premium.

Using yields avoids mixing ratios whose direction is easy to misread. A lower
price-to-earnings ratio is equivalent to a higher earnings yield, while a
higher dividend yield already points in the same direction.

Negative or invalid operating denominators are not treated as cheap. For
example, a benchmark with negative aggregate earnings cannot produce a useful
earnings yield. That component becomes unavailable and reduces coverage.

## Data contract

The engine reads an immutable `valuation-input.v1` export configured through:

```bash
export CAPITAL_INTELLIGENCE_VALUATION_FILE=/data/valuation.json
```

The document contains:

```json
{
  "schema_version": "valuation-input.v1",
  "provider": "LICENSED_PROVIDER",
  "source_identifier": "us-equity-valuation:2026-01-31",
  "benchmark": "US_LARGE_MID_CAP",
  "currency": "USD",
  "methodology_version": "provider-aggregate.v1",
  "observations": [
    {
      "metric": "earnings_yield",
      "value": 0.048,
      "observation_date": "2026-01-30",
      "available_at": "2026-01-31T12:00:00Z",
      "retrieved_at": "2026-01-31T12:05:00Z",
      "quality_state": "cached",
      "source_identifier": "provider-series:earnings-yield"
    }
  ]
}
```

The complete file SHA-256 fingerprint is retained in analytical evidence
lineage.

The source must preserve one benchmark definition and one methodology version
through the comparison history. A current aggregate cannot be compared with a
historical series produced from a different constituent universe, weighting
method, earnings definition, or corporate-action policy without a new
methodology version.

## Point-in-time policy

Only observations whose `available_at` timestamp is no later than the requested
decision time are eligible.

The latest observation for each metric is ranked against earlier observations
that were also available at the decision time. The latest value is not compared
with future revisions or future benchmark membership.

At least 12 prior observations are required for a component. Missing history
does not receive an imputed percentile.

## Versioned scoring policy

`valuation-policy.v1` applies these weights:

| Component | Weight |
| --- | ---: |
| Earnings yield | 22% |
| Free-cash-flow yield | 22% |
| Sales yield | 13% |
| Book-value yield | 10% |
| Dividend yield | 13% |
| Equity risk premium | 20% |

Each latest value receives a percentile relative to its earlier point-in-time
history. The percentile is transformed to a `[-1, 1]` signal:

- values above historical median are positive;
- values below historical median are negative;
- higher yield always means more valuation support.

A single attractive multiple cannot classify the market as broadly attractive.
An expanding result requires at least three positive components.

A broadly stretched result requires a deeply negative composite and at least
four strongly negative components.

## Result meaning

The shared analytical direction is interpreted as valuation support:

- `expanding` — valuation support is broadly improving;
- `neutral` — evidence is mixed or near historical midpoint;
- `contracting` — valuation support is diminishing;
- `stressed` — valuation is broadly stretched;
- `unavailable` — no defensible point-in-time conclusion.

The score is not an expected return, fair value, or probability.

## Data status

- `current` — all six components are available and fresh;
- `incomplete` — one or more components are unavailable;
- `stale` — one or more latest observations exceed the freshness policy;
- `unavailable` — no component has enough defensible history.

The default freshness window is 120 days because aggregate fundamental
valuation measures generally update more slowly than market prices.

## Personal CIO integration

Valuation contributes to:

- **Why does it matter?**
- portfolio sensitivity to earnings and discount-rate disappointment;
- margin-of-safety explanations;
- evidence lineage; and
- review conditions.

It cannot independently change the formal action or no-action result.

An attractive valuation assessment does not imply that prices must rise soon.
A stretched assessment does not imply that prices must fall soon. Business
Cycle, Credit Cycle, Market Breadth, objectives, mandates, and portfolio
alignment remain separate evidence.

## Default unavailable behavior

The repository does not ship a licensed aggregate valuation history. When
`CAPITAL_INTELLIGENCE_VALUATION_FILE` is absent, the engine publishes an
explicit unavailable result and the core daily intelligence cycle continues.

## API

```text
GET /v1/valuation/latest
GET /v1/valuation/history?limit=30
```

Both routes are authenticated and read-only in the secured runtime.

## Command line

Run the configured source:

```bash
python run_valuation.py
```

Run a historical immutable export without persistence:

```bash
python run_valuation.py \
  --data-file /data/valuation-2026-01-31.json \
  --as-of 2026-01-31T21:00:00Z \
  --no-persist
```

## Safety boundaries

- no price target;
- no expected-return forecast;
- no market-timing signal;
- no individual-company valuation;
- no portfolio mutation;
- no order creation or trade execution;
- no change to the Capital Intelligence Score;
- no committee or mandate authority.
