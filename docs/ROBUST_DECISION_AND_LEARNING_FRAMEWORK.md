# Robust decision and learning framework

## Purpose

The canonical framework already enforces point-in-time evidence, complete capital-alternative comparison, independent specialist review, CIO-only action authority, portfolio construction, paper implementation, living theses, and hindsight-free evaluation.

This layer closes two remaining weaknesses:

1. a high arithmetic expected return could look attractive even when compounding, scenario dispersion, evidence uncertainty, or a modest adverse probability shift makes the opportunity fragile; and
2. completed outcomes could be measured without a single version-specific process for deciding whether a model should be retained, watched, suspended, or submitted for human governance review.

The framework improves robustness and expected net decision quality. It does not guarantee profit, authorize live trading, or permit performance claims.

## Pre-decision robustness

`cio.robustness.RobustCandidateAssessor` evaluates the same disclosed base, bull, and bear scenarios used by the canonical candidate record.

It:

- converts horizon returns into annualized portfolio-slice geometric returns;
- includes estimated transaction cost and slippage;
- compares the result with the strongest point-in-time alternative;
- shrinks the estimated advantage toward that alternative when evidence quality is weak;
- penalizes scenario dispersion;
- shifts probability from favorable scenarios toward the bear case and repeats the calculation;
- reconciles the stated probability of success with the probabilities implied by positive and negative scenarios;
- measures the probability of loss, worst-case portfolio loss, robust edge, stressed edge, and edge relative to uncertainty; and
- fails closed when any required robustness gate is not met.

The opportunity engine uses these diagnostics in qualification, ranking, and tie-breaking. The CIO independently applies the same gate before issuing a positive allocation action. A current holding can still be reduced or exited when its expected return has deteriorated.

## Why geometric return is separate from arithmetic return

Arithmetic scenario return remains visible and useful. It is not sufficient for a compounding objective because outcomes compound multiplicatively and asymmetric losses can reduce long-run wealth even when a simple average looks attractive.

The robust assessor therefore retains both views:

- arithmetic expected return for transparent reconciliation with the original candidate record; and
- geometric, evidence-adjusted, uncertainty-penalized return for positive allocation authority.

## Outcome learning

`evaluation.decision_learning.DecisionLearningEvaluator` consumes matured, out-of-sample observations from one exact model version and one exact decision-policy version.

Each observation preserves:

- decision and evaluation identifiers;
- model and policy versions;
- asset class and market regime;
- decision and evaluation timestamps;
- complete horizon;
- forecast probability and realized success;
- net value added versus the best original alternative and cash;
- implementation cost;
- realized drawdown;
- number of candidates considered; and
- evidence lineage.

The report evaluates:

- observation count, duration, regime breadth, and asset-class breadth;
- Brier score, log loss, and calibration gap;
- posterior success probability and a conservative lower bound;
- mean and median net value added versus the best original alternative;
- a multiple-testing-adjusted lower confidence bound on value added;
- value added versus cash;
- implementation drag; and
- worst realized drawdown.

Reports are reproducible only from the exact frozen decision, evaluation, model, policy, and evidence versions recorded in their observations.

## Governance states

| State | Meaning |
| --- | --- |
| `insufficient_evidence` | The out-of-sample sample, duration, or breadth is not adequate for a conclusion |
| `retain` | Reserved for a governed retained baseline when no promotion claim is made |
| `watch` | The sample is mature but one or more quality gates need investigation |
| `suspend` | A material value-added, calibration, cost, or drawdown failure requires the version to stop receiving new authority |
| `eligible_for_governance_review` | Every quantitative gate passed; human governance review is still required |

No state automatically changes model weights, qualification thresholds, CIO policy, portfolio state, or execution authority. Any promotion requires a new reviewed version, independent validation, and the existing release and paper-readiness gates.

## Selection-bias control

The learning report treats the number of candidates considered as an effective selection-trial count. Its lower bound on value added uses a Bonferroni-style one-sided significance adjustment. This is intentionally conservative: searching more opportunities creates more chances to select an apparently strong result by luck.

This control does not replace full walk-forward validation. It complements the existing point-in-time universe, non-overlapping research windows, look-ahead rejection, survivorship controls, calibration, paper-operation evidence, and formal governance process.

## Safety boundary

The following values remain permanently false in every decision-learning report:

```text
automatic_model_change = false
real_money_authorized = false
performance_claims_permitted = false
```

The objective is to improve the probability of disciplined, profitable paper decisions after costs—not to imply certainty or proven alpha.
