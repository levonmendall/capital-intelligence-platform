# Compounding allocation core

## Objective

The canonical portfolio objective is to maximize long-term geometric return after
costs while preserving the ability to survive adverse outcomes.  The portfolio may
hold cash, but cash must compete with feasible productive-risk and defensive
portfolios rather than win automatically because no isolated candidate is perfect.

## Active sequence

1. Complete governed market discovery and candidate evidence.
2. Derive one causal portfolio posture from common macro and market evidence.
3. Express the posture as allocation-search ranges across productive risk,
   defensive income, dollar liquidity, inflation-sensitive real assets, and
   diversifiers.
4. Classify every qualified candidate into one sleeve.
5. Preserve the existing opportunity, six-specialist, robust-return, CIO, and
   construction path.
6. Permit the CIO to authorize a small staged position when the ordinary acquisition
   path abstains solely because of ordinary uncertainty or one bounded independent
   disagreement.
7. Compare current, cash, posture-consistent, productive-risk, defensive,
   diversified-exploratory, and actual constructed portfolios.
8. Persist posture and alternatives in a separate append-only hash chain.

## Staged-participation boundary

A favorable posture never overrides a hard control.  A new position requires all of
the following:

- current capability authority permits a positive recommendation;
- aggregate evidence quality is at least 70 percent;
- every evidence dimension is at least 50 percent;
- no evidence veto remains;
- no implementation block remains;
- reconciled return exceeds the best capital alternative;
- robust edge is positive;
- stressed edge is non-negative;
- loss probability and scenario-consistency remain inside bounded policy;
- no more than one independent high-confidence objection remains;
- the adaptive growth ensemble is above Observe;
- Portfolio and Risk identifies a positive feasible target and funding source.

The initial staged target is capped at one percent and remains subject to independent
portfolio construction.  Construction may reduce or eliminate it.

## Regime causality

The posture engine does not use `risk-on = equities` or `risk-off = bonds` as a
universal rule.  It distinguishes:

- growth-led risk-on;
- disinflationary risk-on;
- recessionary risk-off;
- inflationary risk-off; and
- funding-stress risk-off.

Inflationary risk-off can discourage ordinary nominal duration while favoring dollar
liquidity, inflation-sensitive real assets, or diversifiers.  Funding stress raises
the required dollar-liquidity range.  A strong-dollar forward regime also increases
the dollar-liquidity search range.

## Authority boundaries

- The posture engine has no candidate, decision, construction, or execution authority.
- Portfolio alternatives are advisory comparisons and cannot bypass the committee.
- Exactly six specialists remain.
- The CIO remains the sole investment-decision authority.
- Portfolio construction remains independently authoritative over feasible targets.
- Paper execution remains the only implementation mode.
- No live-money capability is introduced.

## Persistence

`SQLiteCompoundingAllocationStore` creates a separate append-only table in the
existing journal database.  Each event contains the posture, competing portfolio
alternatives, code version, paper-only declaration, previous hash, and content hash.
It does not rewrite or weaken the canonical CIO journal chain.

## Next phases

The core provides the allocation bridge.  Subsequent phases should add:

1. point-in-time capital-flow and positioning evidence;
2. market-expectations and priced-in analysis;
3. view-to-expression candidate generation;
4. incremental flow, credit, volatility, breadth, thesis, and catalyst triggers;
5. horizon-specific lifecycle management; and
6. empirical attribution of cash opportunity cost, false negatives, rotation,
   sizing, timing, and realized geometric return.
