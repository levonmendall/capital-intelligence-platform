# Decision-Stage Contribution Analysis

## Purpose

Capital Intelligence already preserves point-in-time decision snapshots, realized
outcomes, missed opportunities, avoided losses, evidence vetoes, implementation
blocks, and CIO-to-construction reconciliation. Phase 7 separately adds advisory
value reporting for evidence vetoes, implementation blocks, and hysteresis.

`evaluation.gate_contribution` does not duplicate that work. It answers two
remaining questions:

1. How much exact portfolio contribution came from CIO selection, construction
   sizing, implementation timing, and implementation cost?
2. Across completed CIO abstentions, how often did restraint protect capital or
   prove costly relative to the original capital alternatives?

## Exact contribution boundary

The analyzer accepts only completed pairs of:

- `DecisionEvidenceSnapshot`; and
- `PointInTimeDecisionEvaluation`.

It uses only the four contribution components already reconciled by the canonical
point-in-time evaluator:

1. CIO selection;
2. construction sizing;
3. implementation timing; and
4. implementation cost.

Their longitudinal total must reconcile exactly to recorded net active portfolio
contribution. The analyzer does not recalculate or reinterpret those components.

## CIO abstention boundary

An abstention does not have a defensible counterfactual portfolio weight. The
analyzer therefore does not manufacture a dollar or portfolio contribution for
WATCH, INSUFFICIENT_EVIDENCE, NO_SUPERIOR_OPPORTUNITY, or NO_MATERIAL_CHANGE.

It records only the realized return spread between the abstained candidate and
the best capital alternative that was actually available at the original
decision boundary, classifying the completed outcome as:

- `protected_capital`;
- `costly_restraint`; or
- `neutral`.

This classification does not rewrite the original decision and does not prove
that a disciplined process was correct or flawed.

## Non-overlap boundary

This module intentionally does not evaluate the value of:

- evidence vetoes;
- implementation blocks; or
- hysteresis.

Those controls belong to the separate advisory decision-value evaluation. This
module also does not add forecast calibration, missed-opportunity collection,
policy resolution, evidence-outage aging, specialist analysis, or risk
intelligence.

## Authority

Decision-stage contribution analysis is permanently:

- research-only;
- unable to create candidates;
- unable to change thresholds;
- unable to promote a model or policy;
- unable to alter a CIO decision;
- unable to size or construct a portfolio;
- unable to authorize paper or real-money execution.

Historical findings may support a separately governed review. They cannot
automatically weaken a control merely because restraint previously prevented a
profitable trade.

## Intended use

The report supports:

- separating CIO selection quality from construction sizing quality;
- identifying implementation timing and cost drag;
- evaluating CIO abstention outcomes;
- persistent-cash accountability;
- controlled shadow and paper evaluation;
- model- and policy-version governance.

Reports should be segmented by model version, policy version, asset class,
regime, and horizon before any governance conclusion is considered.
