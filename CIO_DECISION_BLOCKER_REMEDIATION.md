# CIO Decision-Blocker Remediation — Capital Competition

## Scope

This correction addresses two production opportunity-context defects that could stop a valid candidate before the six-specialist committee and CIO. It does not change the canonical investment strategy, an investment threshold, specialist authority, CIO authority, construction limits, execution authority, or the paper-only boundary.

## Defect 1 — stale cash hurdle after the portfolio becomes invested

Candidate evidence is created independently and initially records the observable cash return as its opportunity cost. The production opportunity context subsequently includes current holdings. The opportunity engine correctly requires the candidate record to match the strongest point-in-time baseline among cash and holdings.

Before this correction, production publication did not reconcile those two stages. When a current holding exceeded cash by more than the existing tolerance, a new candidate could be hard-rejected for a stale opportunity-cost value even when the candidate was genuinely superior to that holding.

### Correction

Production publication now:

1. builds a baseline context containing cash and current holdings only;
2. calculates the strongest governed point-in-time baseline using the existing alternative-comparison rule;
3. immutably aligns every candidate record to that same baseline; and
4. preserves the engine's stale-opportunity-cost integrity check for genuinely inconsistent records.

## Defect 2 — unqualified candidates treated as qualified alternatives

The production publisher previously labeled every raw candidate as `QUALIFIED_CANDIDATE` before universe eligibility, evidence, liquidity, downside, cost, and robustness qualification completed. A high-return but stale, illiquid, unsupported, or otherwise ineligible candidate could therefore become the governing best alternative and suppress a valid candidate.

### Correction

Opportunity competition is now two-pass:

1. All candidates are evaluated against cash and current holdings.
2. Only candidates that pass the first governed qualification may enter the candidate-alternative set.
3. Existing holdings are not duplicated as candidate alternatives.
4. Candidate alternatives use a net, horizon-normalized, evidence-adjusted, uncertainty-penalized comparable return and do not receive a second implementation-cost charge.
5. The final queue is rebuilt with the vetted competitive set before specialist context is persisted.

## Production confirmation

Regression coverage establishes that:

- a valid candidate remains eligible when an existing holding is stronger than cash;
- the candidate's immutable opportunity-cost field is aligned to the actual holding baseline;
- an unqualified high-return candidate cannot pollute the competitive alternative set;
- current holdings are not duplicated as candidate alternatives;
- implementation costs are not deducted twice; and
- a valid post-investment GOVT candidate reaches all six specialists, receives a persisted CIO decision, and is recorded in the persistent-cash funnel as reaching specialist analysis and CIO consideration.

## Persistent state and migration

No historical record, CIO journal event, portfolio snapshot, or screening publication is rewritten. The change applies prospectively when a new production context is published.

## Authority boundary

- Canonical investment strategy changed: **no**
- Qualification thresholds changed: **no**
- Evidence or liquidity thresholds changed: **no**
- Cash hurdle lowered: **no**
- Specialist authority changed: **no**
- CIO authority changed: **no**
- Construction authority changed: **no**
- Paper execution authority changed: **no**
- Real-money authority added: **no**

## Rollback

Revert the remediation commit. No database migration, portfolio reset, or historical rewrite is required.
