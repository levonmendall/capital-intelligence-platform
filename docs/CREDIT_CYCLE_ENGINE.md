# Credit Cycle Intelligence Engine

## Purpose

PR29 adds a deterministic, point-in-time assessment of United States corporate
and bank credit conditions. It answers whether credit is broadly expanding,
mixed, tightening, stressed, or unavailable.

The engine does not forecast defaults, recessions, portfolio returns, or goal
success. It summarizes observable credit conditions and explains how those
conditions can transmit to a portfolio.

## Inputs

The first policy version evaluates six independent channels:

| Component | FRED series | Credit interpretation |
|---|---|---|
| High-yield option-adjusted spread | `BAMLH0A0HYM2` | Wider spreads indicate greater compensation for lower-quality credit risk |
| Investment-grade option-adjusted spread | `BAMLC0A0CM` | Wider spreads indicate broader corporate financing pressure |
| C&I lending standards | `DRTSCILM` | Positive values indicate more banks tightening lending standards |
| Commercial and industrial loans | `BUSLOANS` | Growth indicates greater bank credit availability |
| Business-loan delinquency rate | `DRBLACBS` | Higher delinquencies indicate borrower deterioration |
| High-yield effective yield | `BAMLH0A0HYM2EY` | Higher yields increase refinancing pressure |

Each component has a versioned weight, comparison rule, neutral level, and
sensitivity in `credit-cycle-policy.v1`.

## Outputs

The engine publishes the shared `analytical-engine-result.v1` contract:

- `expanding`
- `neutral`
- `contracting`
- `stressed`
- `unavailable`

Data status remains separate:

- `current`
- `incomplete`
- `stale`
- `unavailable`

The engine score is independent from the Capital Intelligence Score. PR29 does
not add engine weights to the signature score or grant the engine committee
authority.

## Stress confirmation

One market spread can move sharply without representing broad credit stress.
The first policy therefore requires confirmation across channels before a
market-spread shock can force a stressed classification.

Examples of confirming evidence include:

- tightening lending standards;
- rising business-loan delinquencies; or
- sharply higher refinancing costs.

A sufficiently weak composite can also produce a stressed result.

## Point-in-time discipline

Every result:

- uses only observations available by the decision timestamp;
- preserves provider, series, observation date, release time, retrieval time,
  vintage, and quality state;
- reduces coverage and confidence when evidence is missing;
- marks stale evidence explicitly;
- discloses contradictory market, bank, and borrower evidence; and
- uses no synthetic fallback values.

## Portfolio transmission

Credit conditions enter the Personal CIO Brief through:

- **Why does it matter?**
- **How does it affect my portfolio?**
- evidence lineage; and
- review conditions.

Expanding credit can support refinancing and risk appetite. Tightening credit
can pressure leveraged, lower-quality, small-company, and capital-intensive
exposures. Stressed credit raises the importance of liquidity reserves,
concentration limits, and counterparty review.

PR29 does not independently change a formal action or no-action outcome.

## Scheduling and persistence

The durable daily worker runs:

1. Global Liquidity
2. Business Cycle
3. Credit Cycle
4. The canonical daily intelligence cycle

All analytical results are stored in the existing append-only
`database/analytical_engines.db` database. The database remains covered by
encrypted backups and optional readiness reporting.

## API

```text
GET /v1/credit-cycle/latest
GET /v1/credit-cycle/history?limit=30
```

Both endpoints are read-only.

## Commands

Run and persist the current engine:

```bash
python run_credit_cycle.py
```

Run a historical point-in-time assessment without persistence:

```bash
python run_credit_cycle.py --as-of 2026-01-31T20:00:00Z --no-persist
```

## Safety boundaries

The Credit Cycle engine cannot:

- change the Capital Intelligence Score in PR29;
- override committee or mandate policy;
- publish a default, recession, profit, or goal-success probability;
- mutate a portfolio;
- create an order; or
- execute a trade.
