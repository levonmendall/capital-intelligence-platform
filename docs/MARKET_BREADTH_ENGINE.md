# Market Breadth Intelligence Engine

## Purpose

PR30 adds the fourth reusable market engine: a deterministic, point-in-time
assessment of participation inside an explicitly identified equity universe.

The engine answers a narrow question:

> Are market gains or losses broadly shared across constituents, or are headline
> indexes being driven by a small number of securities?

Market breadth is not a price target, return forecast, or trading signal. It
cannot independently recommend or execute a portfolio transaction.

## Data truthfulness

Breadth requires cross-sectional constituent history. It must not be estimated
from macroeconomic series or a single capitalization-weighted index.

The engine consumes:

- one point-in-time universe snapshot;
- active constituent identifiers and venues;
- explicit constituent weights;
- canonical daily OHLCV bars bounded by the decision timestamp; and
- provider, observation, retrieval, quality, and source-fingerprint lineage.

The repository does not yet enable a licensed equity market-data provider.
Without a configured source, the engine publishes `unavailable` rather than using
sample prices or a current-universe survivorship shortcut.

A provider export may be configured through:

```bash
export CAPITAL_INTELLIGENCE_MARKET_BREADTH_FILE=/data/market_breadth.json
```

The file must use `market-breadth-input.v1`. Its complete SHA-256 fingerprint is
included in analytical evidence identifiers so a retained input artifact can be
matched to the resulting assessment.

## Versioned policy

`market-breadth-policy.v1` evaluates six components:

| Component | Interpretation |
|---|---|
| Daily participation | Share of moving constituents advancing over one session |
| 20-session participation | Share of constituents with positive medium-horizon returns |
| Above 50-session average | Short/intermediate trend participation |
| Above 200-session average | Long-term trend participation |
| New highs minus new lows | Balance of 52-week breakouts and breakdowns |
| Equal-weight leadership | Equal-weight return relative to capitalization-weighted return |

The equal-weight component prevents a rally concentrated in the largest
constituents from being described as healthy broad participation.

## Output

The shared `analytical-engine-result.v1` direction is:

- `expanding` — participation is broadening;
- `neutral` — evidence is mixed or narrowly led;
- `contracting` — participation is weakening;
- `stressed` — broad internal deterioration is confirmed; or
- `unavailable` — no defensible point-in-time conclusion.

Data status remains separate:

- `current`;
- `incomplete`;
- `stale`; or
- `unavailable`.

Missing constituents and insufficient lookback history reduce weighted coverage.
Stale bars or a stale universe snapshot lower data quality. Values are never
silently imputed.

## Stress confirmation

One weak breadth statistic is not enough to declare broad stress. The first
policy confirms stress when multiple internal measures deteriorate together,
such as:

- weak daily participation;
- fewer constituents above long-term trend; and
- materially more new lows than new highs.

A sufficiently weak composite may also produce a stressed result.

## Personal CIO integration

The latest Market Breadth result at or before the daily decision time contributes
to:

- **Why does it matter?** through a plain-language participation explanation;
- **How does it affect my portfolio?** through concentration and drawdown
  transmission;
- review conditions; and
- evidence lineage.

The engine does not independently change the formal action or no-action outcome
in PR30. It informs the investor without bypassing committee, mandate, objective,
or material-change policy.

## Scheduling and persistence

The daily worker runs:

1. Global Liquidity;
2. Business Cycle;
3. Credit Cycle;
4. Market Breadth; and
5. the canonical daily intelligence cycle.

All analytical results are persisted to the append-only
`database/analytical_engines.db` store. An unavailable breadth source does not
block the established daily cycle.

## API

```text
GET /v1/market-breadth/latest
GET /v1/market-breadth/history?limit=30
```

The endpoints are authenticated and read-only.

## Commands

Run the current configured engine:

```bash
python run_market_breadth.py
```

Run one retained provider export at a historical decision timestamp without
persisting it:

```bash
python run_market_breadth.py \
  --data-file /data/market_breadth-2026-01-31.json \
  --as-of 2026-01-31T21:00:00Z \
  --no-persist
```

## Provider-export schema

The top-level document contains:

```json
{
  "schema_version": "market-breadth-input.v1",
  "provider": "LICENSED_PROVIDER",
  "source_identifier": "provider-snapshot:2026-01-31",
  "universe": {
    "identifier": "US_EQUITY_CORE",
    "as_of": "2026-01-31T21:00:00Z",
    "observed_at": "2026-01-31T20:55:00Z",
    "retrieved_at": "2026-01-31T21:00:00Z",
    "quality_state": "cached",
    "members": []
  },
  "bars": []
}
```

Each member requires `instrument_id`, `venue`, and positive `weight`. Optional
`effective_from` and `effective_to` fields preserve historical membership. Each
bar follows the canonical daily `PriceBar` fields and retains its own observed,
retrieved, venue, and quality metadata.

## Safety boundaries

A result must not:

- use a universe snapshot or bar observed after the decision time;
- substitute a current universe for a historical one without disclosure;
- present missing or stale constituents as current;
- call concentrated capitalization-weighted leadership broad participation;
- alter the Capital Intelligence Score or committee weights in PR30;
- create a new primary dashboard; or
- recommend or execute a transaction by itself.
