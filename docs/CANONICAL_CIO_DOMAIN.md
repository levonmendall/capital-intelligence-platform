# Canonical CIO Decision Domain

The `cio` package and `committee.cio` facade implement the first enforceable domain boundary from `GOVERNING_SPECIFICATION.md`.

## Ownership

- `cio.models` owns the common quantitative candidate and final CIO decision records.
- `cio.universe` owns Version 1 direct-recommendation eligibility.
- `cio.committee` owns the five independent specialist-analysis packet.
- `cio.service` owns CIO synthesis and final user-facing action authority.
- `committee.cio` is the canonical committee-facing import surface.

Legacy briefing meetings, regime governance, and weighted recommendation consensus remain compatibility paths. New candidate and capital-allocation callers must use the canonical CIO domain.

## Version 1 universe

`RecommendationUniversePolicy` distinguishes:

- `direct_recommendation` — qualified liquid U.S.-listed equities, U.S.-listed ETFs, and short-duration U.S. Treasury equivalents;
- `intelligence_only` — broader markets that may inform evidence but cannot receive direct actions; and
- `ineligible` — nominally in-scope instruments that fail liquidity, freshness, or analytical-coverage requirements.

The policy result is required by CIO synthesis. A specialist majority cannot override it.

## Common candidate schema

`CandidateDecisionRecord` requires point-in-time instrument identity, price, horizon, base/bull/bear returns and probabilities, fair value, upside, downside, probability of success, catalysts, risks, assumptions, invalidation conditions, supporting and contradictory evidence, six evidence-quality dimensions, liquidity, transaction costs, slippage, opportunity cost, portfolio contribution, current and maximum weight, monitoring indicators, review timing, evidence identifiers, and model versions.

It calculates:

- probability-weighted expected return;
- implementation-cost return;
- cost-adjusted expected return; and
- opportunity edge over the recorded alternative use of capital.

Categorical labels may summarize this record but cannot replace it.

## Specialist independence and authority

`IndependentSpecialistPacket` requires exactly one independent first-pass analysis from each governing role:

1. Macro & Economic Strategist
2. Market Strategist
3. Fundamental & Valuation Analyst
4. Portfolio & Risk Manager
5. Evidence & Governance Officer

The packet rejects duplicate or missing roles, mismatched candidates, analyses predating the candidate evidence boundary, and analyses that were not explicitly completed independently.

Only the Evidence & Governance Officer can issue evidence vetoes. Only the Portfolio & Risk Manager can issue implementation blocks, propose position size, or name a funding source.

The strongest opposing conclusion is preserved as structured material dissent with evidence that could resolve it.

## CIO synthesis

`ChiefInvestmentOfficer` is the sole service that returns a `CIODecision` and `CIOAction`.

It evaluates:

- universe eligibility;
- evidence vetoes;
- evidence quality and weakest-dimension ceilings;
- implementation blocks;
- unresolved high-confidence dissent;
- cost-adjusted expected return;
- opportunity edge;
- current portfolio weight; and
- the feasible position proposal from the Portfolio & Risk Manager.

Permitted actions are Buy, Increase, Hold, Reduce, Exit, Watch, Insufficient evidence, No superior opportunity, and No material change.

Specialist support ratio and median confidence are reliability diagnostics. They do not map directly to an action. A fully supportive packet still produces `no_superior_opportunity` when expected return or opportunity edge is inadequate.

## Confidence

Final confidence combines disclosed evidence quality, median specialist confidence, and support ratio. It is capped by the weakest evidence dimension and further capped when material dissent, vetoes, or implementation blocks are present.

Confidence describes evidence and process reliability. It is not a return guarantee.

## Portfolio boundary

The Portfolio & Risk Manager proposes a feasible size and funding source. The CIO may approve that proposal as part of Buy, Increase, or Reduce, but the decision remains subject to final portfolio construction and execution controls.

The CIO domain does not execute trades and does not consume individual financial goals.

## Migration

The next integration steps are:

1. adapt analytical and company evidence into `CandidateDecisionRecord`;
2. migrate committee callers to `committee.cio`;
3. persist candidate, specialist, dissent, and CIO decision records in the append-only institutional journal;
4. render the canonical `CIODecision` in Daily Capital Intelligence; and
5. deprecate weighted consensus as a final-action path after all callers migrate.