# Portfolio Construction and Implementation

The canonical portfolio construction boundary is `portfolio.construction_api`.

The Chief Investment Officer determines what should be owned and may approve a proposed target weight. The `PortfolioConstructionEngine` determines whether that expression is feasible in the actual portfolio and produces non-executing trade proposals.

The engine does not analyze company evidence, rank opportunities, vote on recommendations, change a CIO action, use individual financial goals, infer risk preferences, or execute orders.

## Inputs

`PortfolioConstructionRequest` is point-in-time and requires:

- portfolio value;
- current cash weight and expected cash return;
- every current position and weight;
- expected return for each current position;
- sector, factor, and correlation-bucket exposure metadata;
- average daily dollar volume;
- transaction-cost and slippage estimates;
- minimum retained weights and explicit funding eligibility; and
- approved CIO construction intents in opportunity-priority order.

Portfolio weights and cash must sum to one.

## CIO construction intent

`ConstructionIntent` translates an approved `CIODecision` and its `CandidateDecisionRecord` into the implementation boundary.

It preserves:

- action;
- requested target weight;
- cost-adjusted expected return;
- opportunity edge;
- candidate maximum position weight;
- sector, factor, and correlation classification;
- liquidity and cost inputs; and
- opportunity rank.

CIO confidence is intentionally absent from the construction engine. Confidence describes evidence reliability and cannot become position size.

Abstention outcomes cannot request target weights. Exit must target zero. Buy, Increase, Reduce, and Exit require an explicit target supplied by the approved decision path.

## Construction order

The engine applies decisions in this order:

1. approved Exit instructions;
2. approved Reduce instructions;
3. approved Buy and Increase instructions ordered by opportunity rank, then opportunity edge and expected return.

For positive allocations, it:

1. uses cash above the minimum reserve;
2. tests the complete allocation against all constraints;
3. considers reductions only from holdings explicitly marked as funding eligible;
4. requires the candidate to exceed the funding holding’s expected return by the replacement-edge threshold;
5. evaluates funding reductions on a temporary copy;
6. commits funding changes only when they create a feasible candidate allocation; and
7. restores unnecessary funding reductions before producing trades.

A failed or infeasible candidate cannot leave an orphaned funding sale in the proposal.

## Constraints

Every proposed target is checked against:

- minimum cash;
- maximum position size;
- sector limits;
- absolute factor-exposure limits;
- correlated-exposure bucket limits;
- maximum turnover;
- maximum total transaction-cost and slippage return;
- execution liquidity based on portfolio value, average daily dollar volume, maximum daily participation, and execution days; and
- funding-source minimum retained weights.

The initial engine is deterministic. A binary search finds the maximum feasible increase or reduction under the complete constraint set.

## Costs and expected return

Trade cost is estimated as:

```text
absolute portfolio weight change
× (transaction cost bps + slippage bps)
÷ 10,000
```

The result reports:

- expected portfolio return before construction;
- expected portfolio return after estimated implementation cost;
- expected-return improvement;
- total turnover;
- total implementation cost;
- target cash and position weights;
- each proposed buy or sell;
- each funding relationship;
- every constraint check; and
- all partial-allocation or blocking explanations.

## Result states

- `feasible` — every requested change was implemented within policy;
- `partial` — at least one executable trade exists, but one or more approved targets were reduced or blocked by constraints;
- `blocked` — no executable change can be produced;
- `no_action` — the approved decisions require no portfolio change.

If the final target fails any constraint, the engine returns the current portfolio with no trades rather than exposing blocked trades as executable.

## Execution boundary

`TradeProposal` is a paper implementation instruction. It has no order identifier, fill, broker, venue-routing instruction, or submission method.

A future execution layer must separately provide:

- approval and idempotency boundaries;
- order type and scheduling policy;
- broker integration;
- market-hours and venue checks;
- pre-trade and post-trade controls;
- realized slippage and transaction-cost measurement; and
- complete implementation audit events.

Live execution remains out of scope until paper trading and walk-forward validation demonstrate that the analytical, CIO, and construction process creates value after costs.