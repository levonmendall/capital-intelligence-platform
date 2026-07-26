# Risk Intelligence Engine

## Purpose

The Risk Intelligence Engine describes whether broad market-risk pressure is
easing, mixed, rising, or under confirmed stress. It is designed to improve the
Personal CIO explanation of portfolio fragility without becoming a loss
forecast, trading signal, or automatic de-risking rule.

The engine uses the shared `analytical-engine-result.v1` contract. Its score is
a **risk-support score**: higher values indicate lower observed risk pressure
and greater market resilience; lower values indicate greater fragility.

## Scope

`risk-policy.v1` evaluates a configured point-in-time market-risk scope. A
source must identify its scope and methodology explicitly, for example:

- U.S. multi-asset market risk;
- global developed-market risk;
- a named institutional benchmark set; or
- another provider-defined scope with stable methodology.

The engine does not combine unrelated sources or silently change its scope.

## Components

The first policy evaluates seven independent risk pressures:

1. **Realized volatility** — the magnitude of recent market fluctuations.
2. **Downside volatility** — volatility concentrated in negative returns.
3. **Cross-asset correlation** — whether normally distinct assets are moving
   together, reducing diversification.
4. **Drawdown depth** — the magnitude of decline from a prior peak.
5. **Market concentration** — dependence on a smaller set of return drivers.
6. **Liquidity stress** — pressure on spreads, market depth, and the cost of
   changing positions.
7. **Tail-loss frequency** — how often unusually negative outcomes are
   appearing relative to history.

Each component is ranked against its own prior point-in-time history. Higher
metric values always mean more risk pressure. The engine converts the
percentile into a common `[-1, 1]` signal where positive values mean easing risk
pressure and negative values mean rising pressure.

At least 12 prior observations are required for a component under the default
policy. Missing history is disclosed and never imputed.

## Direction policy

The engine publishes:

- `expanding` — risk pressure is easing across several independent measures;
- `neutral` — evidence is mixed or transitional;
- `contracting` — risk pressure is rising but broad stress is not confirmed;
- `stressed` — both realized market behavior and structural fragility confirm
  broad stress; or
- `unavailable` — no defensible point-in-time conclusion can be produced.

Data quality remains a separate field: `current`, `incomplete`, `stale`, or
`unavailable`.

## Stress confirmation

A stressed conclusion cannot be produced from one volatility spike, one large
down day, or one deteriorating component.

`risk-policy.v1` requires:

- a deeply negative weighted composite;
- at least four severely negative components;
- confirmation from at least two realized-market measures; and
- confirmation from at least two structural-fragility measures.

This prevents the engine from treating ordinary market volatility as systemic
fragility.

## Point-in-time source contract

The immutable provider format is `risk-input.v1`:

```json
{
  "schema_version": "risk-input.v1",
  "provider": "LICENSED_PROVIDER",
  "source_identifier": "provider:risk:2026-01-31",
  "scope": "US_MULTI_ASSET",
  "methodology_version": "provider-risk.v1",
  "retrieved_at": "2026-01-31T21:00:00Z",
  "observations": [
    {
      "metric": "realized_volatility",
      "value": 0.184,
      "observation_date": "2026-01-30",
      "available_at": "2026-01-31T13:00:00Z",
      "retrieved_at": "2026-01-31T21:00:00Z",
      "quality_state": "live"
    }
  ]
}
```

The engine retains:

- provider and source identity;
- scope and methodology version;
- observation date;
- availability and retrieval timestamps;
- quality state;
- historical percentile and normalized signal; and
- a SHA-256 fingerprint for the complete source file.

Observations available after the decision timestamp are excluded.

## Configuration

The repository does not enable a licensed risk-history source by default. The
engine therefore publishes `unavailable` until a source is configured:

```bash
export CAPITAL_INTELLIGENCE_RISK_FILE=/data/risk.json
```

An unavailable source does not block the core daily intelligence cycle.

## Running the engine

Current configured source:

```bash
python run_risk.py
```

One historical point-in-time run without persistence:

```bash
python run_risk.py \
  --data-file /data/risk-2026-01-31.json \
  --as-of 2026-01-31T21:00:00Z \
  --no-persist
```

Results are appended to `analytical_engines.db` unless `--no-persist` is used.
The store remains append-only and is included in the existing encrypted backup
process.

## API

Authenticated read-only endpoints:

```text
GET /v1/risk/latest
GET /v1/risk/history?limit=30
```

No write route is exposed.

## Personal CIO integration

Risk intelligence contributes to:

- **Why does it matter?** — explains whether fragility is rising or easing;
- **How does it affect my portfolio?** — explains volatility, drawdown,
  diversification, concentration, and liquidity transmission;
- evidence lineage;
- review conditions; and
- objective-aware alert explanations.

The Personal CIO should compare the result with the investor's recorded
maximum tolerable drawdown, risk capacity, liquidity needs, and time horizon.
The engine itself does not alter the formal action or no-action outcome.

## Safety boundaries

The engine does not produce:

- a probability of loss;
- a forecast loss amount;
- Value at Risk presented as certainty;
- a crash prediction;
- a buy, sell, hedge, or de-risk instruction;
- an allocation change;
- an order or transaction;
- a change to the Capital Intelligence Score; or
- committee recommendation authority.

Risk pressure is evidence for governed judgment, not a substitute for it.

## Validation expectations

Fixtures must cover:

- broadly easing risk pressure;
- confirmed cross-channel stress;
- a single volatility shock that cannot force stress;
- rising risk without structural confirmation;
- mixed evidence;
- incomplete coverage;
- stale evidence;
- future-data exclusion;
- explicit unconfigured behavior; and
- source fingerprinting.

Integration tests must prove seven-engine persistence, unchanged canonical
cycle return behavior, read-only API access, and Personal CIO context without
independent action authority.
