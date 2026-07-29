# Robust decision and learning framework

## Purpose

The canonical framework already enforces point-in-time evidence, complete capital-alternative comparison, independent specialist review, CIO-only action authority, portfolio construction, paper implementation, living theses, and hindsight-free evaluation.

This layer closes the remaining analytical inconsistencies:

1. a high arithmetic expected return could look attractive even when compounding, horizon, scenario dispersion, evidence uncertainty, or a modest adverse probability shift makes the opportunity fragile;
2. a deteriorating current holding could be filtered out by acquisition rules before the CIO reached Reduce or Exit;
3. specialist conclusions could affect confidence without producing a reconciled expected-return distribution;
4. repeated evidence origins, preliminary portfolio-contribution estimates, and caller-supplied success probabilities could appear more authoritative than warranted; and
5. completed outcomes could be pooled across incompatible assets, horizons, and regimes.

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
- derives effective probability of success from the same outcome distribution, measured against the horizon-matched best alternative, while retaining any stated value only as a consistency diagnostic;
- measures the probability of loss, worst-case portfolio loss, robust edge, stressed edge, and edge relative to uncertainty; and
- fails closed when any required robustness gate is not met.

The opportunity engine uses these diagnostics for the acquisition lane. Preliminary portfolio-contribution estimates are neutral at this stage and cannot determine qualification or rank.

Every current holding enters a separate mandatory review lane even when it fails acquisition thresholds. The CIO therefore always has authority to issue Hold, Reduce, Exit, or replacement decisions for deteriorating or no-longer-supported ownership.

## Specialist return reconciliation

The six specialists remain independent first-pass reviewers. Macro, market, cross-asset forecast, and asset-specific valuation impacts are then reconciled conservatively into the candidate's full outcome distribution.

The reconciler:

- excludes abstentions and never treats narrative repetition as new information;
- groups evidence by originating-fact identifiers and resolves disclosed upstream evidence dependencies;
- discounts direct and inherited overlap;
- applies confidence-weighted per-role and total adjustment caps;
- preserves every original outcome label while allowing governed scenario-specific return and probability changes;
- preserves expected path-drawdown adjustments by scenario;
- normalizes probabilities and records any bounds correction; and
- derives final expected return, downside, and probability of beating the horizon-matched alternative from that same distribution.

For fixed income, FX, commodities, crypto, real estate, futures, options, volatility, and alternatives, the Fundamental & Valuation role requires a genuine asset-specific evidence context. Without one it abstains instead of restating the candidate model.

## Nonlinear instruments and typed metrics

Options and volatility candidates require a simulated payoff distribution with at least three governed outcomes. The distribution preserves nonlinear and bounded-loss behavior through CIO synthesis and evaluation.

Asset-specific metrics retain a semantic definition containing unit, directionality, and applicable horizon. Their source observations, model versions, limitations, and originating facts remain attached to the evidence packet.

## Portfolio-aware ordering and joint risk

Analytical qualification determines which acquisition candidates deserve review; it does not allow a caller-supplied portfolio-contribution estimate to create authority. The canonical cycle supplies governed marginal contribution, diversification, thesis clarity, invalidation clarity, and forecast-durability inputs for ranking.

After specialist preview, final construction preserves exits and reductions first and evaluates multiple deterministic positive-allocation orderings. It selects the strongest complete feasible portfolio rather than accepting one greedy sequence. Common portfolio scenarios measure expected geometric return, expected shortfall, stressed drawdown, probability of improving on the current portfolio, and liquidity-adjusted tail loss. Positive allocations are removed when they fail any required complete-portfolio improvement gate.


## Policy profiles and decision stability

`cio.policy_matrix.DecisionPolicyMatrix` resolves a versioned asset-class and horizon profile for every candidate. Diversified liquid assets, standard assets, tactical forecasts, speculative assets, and nonlinear derivatives receive distinct return, opportunity-edge, probability, downside, position-size, robustness, persistence, cooldown, durability, and annualization controls. The strictest applicable acquisition hurdle governs.

The CIO may receive a `PriorDecisionContext` containing the previous action, target, thesis state, consecutive confirming cycles, and last material change. Non-urgent changes require the applicable persistence and cooldown controls. Evidence vetoes, explicit invalidation, severe downside, or emergency overrides bypass those delays.

## Why geometric return is separate from arithmetic return

Arithmetic scenario return remains visible and useful. It is not sufficient for a compounding objective because outcomes compound multiplicatively and asymmetric losses can reduce long-run wealth even when a simple average looks attractive.

The robust assessor therefore retains both views:

- arithmetic expected return for transparent reconciliation with the original candidate record; and
- geometric, evidence-adjusted, uncertainty-penalized return for positive allocation authority.

## Action and inaction evaluation

Point-in-time evaluation treats action and inaction symmetrically. A mature zero-allocation decision can be classified as correct abstention, avoided loss, missed opportunity, confirmed insufficient evidence, a costly implementation block, or review timing that was too slow. This prevents a conservative process from appearing successful merely because it declined to act.

Forecast calibration is measured against whether the candidate beat the original governing alternative. Scenario log score evaluates the realized return against the reconciled distribution. Decision-confidence calibration, sizing efficiency, timing efficiency, implementation cost, and abstention value remain separate so one good or bad implementation cannot rewrite forecast quality.

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

The report evaluates the exact model and policy version both in aggregate and in separate asset-class, market-regime, and horizon buckets. Segments below their own minimum sample remain explicitly insufficient rather than borrowing confidence from unrelated observations.

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
