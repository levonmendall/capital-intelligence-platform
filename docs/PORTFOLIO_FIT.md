# Portfolio Fit and Constraint Gate

## Purpose

The portfolio-fit gate answers one question:

> Does this committee-approved idea belong in this portfolio, under this
> mandate, at the requested size?

It is not an optimizer, order generator, brokerage integration, or performance
forecast.

## Inputs

1. A governed committee decision.
2. A separate, non-executing portfolio proposal.
3. A complete point-in-time portfolio snapshot.
4. A versioned mandate.
5. A versioned fit policy.

The proposal identifies the target, asset bucket, requested portfolio-weight
change, estimated risk-budget change, liquidity score, and exposure tags.

## Decision order

1. Require final committee approval.
2. Require proposal direction to match the recommendation.
3. Permit risk-reducing proposals without requiring new capacity.
4. Apply prohibited-investment, exposure, and liquidity rules.
5. Calculate headroom under position, asset-bucket, minimum-cash, and
   risk-budget limits.
6. Detect material overlap with existing positions.
7. Return the full permitted size, a smaller bounded size, a replacement
   review, or a blocking outcome.

## Outcomes

| Outcome | Meaning |
| --- | --- |
| `fit` | The requested proposal stays within every tested constraint. |
| `fit_smaller` | A smaller weight stays within the binding limits. |
| `replace_overlap` | Similar risk already exists and should be reviewed for replacement. |
| `policy_blocked` | A hard mandate, direction, or liquidity rule prevents the proposal. |
| `no_risk_budget` | No meaningful capacity remains for the addition. |
| `no_action` | Committee approval is incomplete or no current exposure exists to reduce. |

## Non-negotiable boundaries

- Committee confidence never becomes a position size.
- A fit decision never executes a trade.
- Reductions cannot exceed the current position.
- New additions are assumed to consume cash and risk capacity.
- Crypto is governed through an explicit asset-bucket limit rather than hidden
  inside alternatives.
- Every result identifies the portfolio snapshot, mandate version, fit-policy
  version, proposal, source decision, constraints, and permitted delta.
