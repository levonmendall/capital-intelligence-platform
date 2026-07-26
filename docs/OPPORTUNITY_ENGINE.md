# Opportunity Qualification and Ranking

The `opportunity` package is the formal boundary between evidence generation and independent specialist analysis.

Its purpose is to prevent the committee from reviewing every interesting asset. Only candidates that represent plausible superior uses of capital reach specialist review.

## Point-in-time opportunity set

`OpportunitySetContext` records the competing uses of capital available at one decision timestamp:

- cash or short-duration Treasury equivalents;
- current portfolio holdings; and
- other already qualified candidates.

At least one cash alternative is required. Alternative identifiers are unique, current weights cannot exceed the portfolio, and expected returns are reduced by implementation cost before comparison.

## Qualification

`OpportunityEngine.qualify` applies:

1. Version 1 recommendation-universe policy;
2. consistency between the candidate’s recorded opportunity cost and the actual opportunity set;
3. minimum cost-adjusted expected return;
4. minimum probability of success;
5. minimum aggregate evidence quality;
6. minimum weakest evidence dimension;
7. minimum candidate liquidity;
8. minimum advantage over the strongest available use of capital;
9. maximum expected downside;
10. maximum implementation cost; and
11. positive expected portfolio contribution.

A rejection records every applicable reason. Rejected candidates do not receive a committee rank and cannot be passed silently as neutral.

## Ranking

Qualified candidates are ranked using disclosed components whose weights sum to one:

| Component | Weight |
| --- | ---: |
| Cost-adjusted expected return | 25% |
| Probability of success | 12% |
| Downside protection | 12% |
| Evidence quality | 16% |
| Evidence freshness | 6% |
| Evidence independence | 6% |
| Liquidity | 8% |
| Opportunity edge | 10% |
| Expected portfolio contribution | 3% |
| Cost efficiency | 2% |

Each `RankedOpportunity` stores the raw value, normalized score, weight, and weighted contribution for every component. The final score must reconcile exactly to those contributions.

The score is a committee-attention ordering mechanism. It is not a CIO action, confidence guarantee, or position size.

## Decision boundaries

- Evidence engines create `CandidateDecisionRecord` values.
- The Opportunity Engine qualifies and ranks them.
- The five independent specialists analyze only qualified candidates.
- The CIO compares the candidate, specialist packet, opportunity cost, and portfolio implementation before issuing an action.

A fully supportive committee cannot restore a candidate rejected for universe scope, evidence quality, stale opportunity cost, inadequate return, excessive downside, poor liquidity, or implementation cost.

## No opportunity outcome

An empty qualified queue is an explicit valid result. It supports `no_superior_opportunity` and prevents pressure to manufacture a recommendation when cash or an existing holding remains the best use of capital.