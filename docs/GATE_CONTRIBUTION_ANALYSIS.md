# Gate Contribution Analysis

## Purpose

Capital Intelligence already preserves point-in-time decision snapshots, realized
outcomes, selection/sizing/timing/cost attribution, missed opportunities, avoided
losses, evidence vetoes, implementation blocks, and CIO-to-construction
reconciliation.

The remaining accountability question is longitudinal:

> Which governed stages protected capital, added value, destroyed value, or
> caused costly restraint across completed decisions?

`evaluation.gate_contribution` answers that question without creating a new
investment engine.

## Evidence boundary

The analyzer accepts only completed pairs of:

- `DecisionEvidenceSnapshot`; and
- `PointInTimeDecisionEvaluation`.

It does not reconstruct the decision, introduce a hindsight alternative, or
change the original evaluation.

The exact portfolio contribution view uses only the four components already
reconciled by the point-in-time evaluator:

1. CIO selection;
2. construction sizing;
3. implementation timing; and
4. implementation cost.

Those exact components must reconcile to the recorded net active contribution.

## Veto and abstention boundary

Evidence vetoes, implementation blocks, and CIO abstentions do not always have a
defensible counterfactual portfolio weight. The analyzer therefore reports their
realized return spread against the best original capital alternative rather than
manufacturing a dollar or portfolio contribution.

Each restraint is classified as:

- `protected_capital`;
- `costly_restraint`; or
- `neutral`.

A later positive or negative outcome does not rewrite the original decision and
does not prove that a disciplined process was correct or flawed.

## Authority

Gate contribution analysis is permanently:

- research-only;
- unable to create candidates;
- unable to change thresholds;
- unable to promote a model or policy;
- unable to alter a CIO decision;
- unable to size or construct a portfolio;
- unable to authorize paper or real-money execution.

Historical findings may support a separately governed review. They cannot
automatically weaken a gate merely because it previously prevented a profitable
trade.

## Intended use

The report can support:

- persistent-cash diagnosis;
- gate-level avoided-loss and missed-opportunity review;
- comparison of CIO selection with construction sizing;
- implementation timing and cost monitoring;
- model- and policy-version governance;
- controlled shadow and paper evaluation.

It should be segmented by model version, decision-policy version, asset class,
regime, and horizon before any governance conclusion is considered.
