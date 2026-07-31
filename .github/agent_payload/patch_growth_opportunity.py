from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected 1 match, found {count}: {old[:100]!r}")
    write(path, content.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str) -> None:
    content = read(path)
    updated, count = re.subn(pattern, replacement, content, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{path}: expected 1 regex match, found {count}")
    write(path, updated)


replace_once(
    "cio/__init__.py",
    '    "DecisionPolicyProfile": ("cio.policy_matrix", "DecisionPolicyProfile"),\n',
    '    "DecisionPolicyProfile": ("cio.policy_matrix", "DecisionPolicyProfile"),\n'
    '    "AdaptiveRobustGrowthEnsemble": ("cio.growth_ensemble", "AdaptiveRobustGrowthEnsemble"),\n'
    '    "GrowthEnsembleAssessment": ("cio.growth_ensemble", "GrowthEnsembleAssessment"),\n'
    '    "GrowthEnsemblePolicy": ("cio.growth_ensemble", "GrowthEnsemblePolicy"),\n'
    '    "GrowthStage": ("cio.growth_ensemble", "GrowthStage"),\n',
)
replace_once(
    "cio/__init__.py",
    '    "CIOAction",\n',
    '    "AdaptiveRobustGrowthEnsemble",\n    "CIOAction",\n',
)
replace_once(
    "cio/__init__.py",
    '    "HistoricalLearningStatus",\n',
    '    "HistoricalLearningStatus",\n'
    '    "GrowthEnsembleAssessment",\n'
    '    "GrowthEnsemblePolicy",\n'
    '    "GrowthStage",\n',
)

replace_once(
    "opportunity/models.py",
    '    ACQUISITION = "acquisition"\n    HOLDING_REVIEW = "holding_review"\n',
    '    ACQUISITION = "acquisition"\n'
    '    PARTICIPATION = "participation"\n'
    '    EXPLORATION = "exploration"\n'
    '    HOLDING_REVIEW = "holding_review"\n',
)

replace_once(
    "opportunity/engine.py",
    '    version: str = "opportunity-qualification.v5"\n'
    '    minimum_net_expected_return: float = 0.05\n'
    '    minimum_probability_of_success: float = 0.55\n',
    '    version: str = "opportunity-qualification.v6-growth"\n'
    '    minimum_net_expected_return: float = 0.03\n'
    '    minimum_probability_of_success: float = 0.52\n',
)
replace_once(
    "opportunity/engine.py",
    '    minimum_opportunity_edge: float = 0.01\n'
    '    maximum_expected_downside: float = -0.35\n',
    '    minimum_opportunity_edge: float = 0.005\n'
    '    maximum_expected_downside: float = -0.45\n',
)
replace_once(
    "opportunity/engine.py",
    '    alternative_uncertainty_penalty: float = 0.02\n'
    '    alternative_liquidity_penalty: float = 0.01\n',
    '    alternative_uncertainty_penalty: float = 0.0075\n'
    '    alternative_liquidity_penalty: float = 0.005\n',
)
replace_once(
    "opportunity/engine.py",
    '    expected_return_weight: float = 0.21\n'
    '    probability_weight: float = 0.10\n'
    '    downside_weight: float = 0.10\n'
    '    evidence_weight: float = 0.14\n'
    '    freshness_weight: float = 0.05\n'
    '    independence_weight: float = 0.05\n'
    '    liquidity_weight: float = 0.07\n'
    '    opportunity_edge_weight: float = 0.10\n'
    '    portfolio_contribution_weight: float = 0.07\n'
    '    thesis_clarity_weight: float = 0.04\n'
    '    invalidation_clarity_weight: float = 0.03\n'
    '    forecast_durability_weight: float = 0.02\n'
    '    cost_efficiency_weight: float = 0.02\n',
    '    expected_return_weight: float = 0.18\n'
    '    probability_weight: float = 0.08\n'
    '    downside_weight: float = 0.10\n'
    '    evidence_weight: float = 0.12\n'
    '    freshness_weight: float = 0.04\n'
    '    independence_weight: float = 0.04\n'
    '    liquidity_weight: float = 0.06\n'
    '    opportunity_edge_weight: float = 0.09\n'
    '    portfolio_contribution_weight: float = 0.16\n'
    '    thesis_clarity_weight: float = 0.04\n'
    '    invalidation_clarity_weight: float = 0.03\n'
    '    forecast_durability_weight: float = 0.03\n'
    '    cost_efficiency_weight: float = 0.03\n',
)

regex_once(
    "opportunity/engine.py",
    r'''        holding_review = candidate\.current_portfolio_weight > 0\.0
        reasons: list\[str\] = \[\]
.*?        reasons\.extend\(robustness\.reasons\)

        if holding_review:''',
    '''        holding_review = candidate.current_portfolio_weight > 0.0
        hard_reasons: list[str] = []
        soft_reasons: list[str] = []
        if not universe.direct_recommendation_allowed:
            hard_reasons.extend(universe.reasons)
        if (
            abs(candidate.opportunity_cost_return - baseline_opportunity_cost)
            > self.policy.opportunity_cost_tolerance
        ):
            hard_reasons.append(
                "recorded candidate opportunity cost does not match the point-in-time opportunity set baseline alternatives"
            )
        if candidate.evidence_quality.score < self.policy.minimum_evidence_score:
            hard_reasons.append("aggregate evidence quality is below threshold")
        if candidate.evidence_quality.ceiling < self.policy.minimum_evidence_dimension:
            hard_reasons.append("at least one evidence-quality dimension is below threshold")
        if candidate.liquidity_score < self.policy.minimum_liquidity_score:
            hard_reasons.append("candidate liquidity is below threshold")
        if robustness.evidence_adjusted_return < minimum_net_expected_return:
            soft_reasons.append(
                "horizon-normalized evidence-adjusted expected return is below the full-conviction threshold"
            )
        if robustness.robust_edge < minimum_opportunity_edge:
            soft_reasons.append(
                "horizon-normalized opportunity edge is below the full-conviction margin"
            )
        scenario_downside = min(
            item.total_return for item in candidate.scenario_distribution
        ) - candidate.implementation_cost_return
        if scenario_downside < maximum_downside:
            hard_reasons.append("expected downside exceeds the qualification limit")
        if robustness.effective_probability_of_success < minimum_probability:
            soft_reasons.append(
                "scenario-derived probability of outperforming the best alternative is below the full-conviction threshold"
            )
        if (
            candidate.implementation_cost_return
            > self.policy.maximum_implementation_cost_return
        ):
            hard_reasons.append("implementation costs exceed the qualification limit")
        if robustness.evidence_adjusted_return <= effective_opportunity_cost:
            soft_reasons.append(
                "horizon-normalized expected return does not clearly exceed the best capital alternative"
            )
        hard_robustness_markers = (
            "scenario ordering",
            "non-positive portfolio wealth",
            "inconsistent with the disclosed scenarios",
            "worst-case portfolio loss",
        )
        for reason in robustness.reasons:
            if any(marker in reason for marker in hard_robustness_markers):
                hard_reasons.append(reason)
            else:
                soft_reasons.append(reason)
        reasons = tuple(dict.fromkeys((*hard_reasons, *soft_reasons)))

        if holding_review:''',
)

regex_once(
    "opportunity/engine.py",
    r'''        if reasons:
            return \(
                CandidateQualification\(
                    candidate_identifier=candidate\.identifier,
                    outcome=QualificationOutcome\.REJECTED,
.*?            robustness,
        \)
''',
    '''        if hard_reasons:
            return (
                CandidateQualification(
                    candidate_identifier=candidate.identifier,
                    outcome=QualificationOutcome.REJECTED,
                    policy_version=self.policy.version,
                    universe=universe,
                    effective_opportunity_cost=effective_opportunity_cost,
                    opportunity_edge=opportunity_edge,
                    best_alternative_identifier=best_alternative.identifier,
                    best_alternative_kind=best_alternative.kind,
                    baseline_alternative_identifier=baseline_alternative.identifier,
                    baseline_opportunity_cost=baseline_opportunity_cost,
                    resolved_policy_profile=profile.identifier,
                    reasons=tuple(dict.fromkeys(hard_reasons)),
                ),
                robustness,
            )

        if soft_reasons:
            wrapper = (
                candidate.instrument.replication_method
                == "us-listed-economic-exposure-wrapper"
            )
            minimally_positive = (
                robustness.evidence_adjusted_return
                > effective_opportunity_cost - 0.005
                and candidate.net_expected_return > -0.01
            )
            lane = (
                AnalysisLane.PARTICIPATION
                if wrapper and minimally_positive
                else AnalysisLane.EXPLORATION
            )
            exploratory_viable = (
                robustness.robust_edge > -0.01
                and robustness.effective_probability_of_success >= 0.40
            )
            if not minimally_positive and not exploratory_viable:
                return (
                    CandidateQualification(
                        candidate_identifier=candidate.identifier,
                        outcome=QualificationOutcome.REJECTED,
                        policy_version=self.policy.version,
                        universe=universe,
                        effective_opportunity_cost=effective_opportunity_cost,
                        opportunity_edge=opportunity_edge,
                        best_alternative_identifier=best_alternative.identifier,
                        best_alternative_kind=best_alternative.kind,
                        baseline_alternative_identifier=baseline_alternative.identifier,
                        baseline_opportunity_cost=baseline_opportunity_cost,
                        resolved_policy_profile=profile.identifier,
                        reasons=tuple(dict.fromkeys(soft_reasons)),
                    ),
                    robustness,
                )
            return (
                CandidateQualification(
                    candidate_identifier=candidate.identifier,
                    outcome=QualificationOutcome.QUALIFIED,
                    policy_version=self.policy.version,
                    universe=universe,
                    effective_opportunity_cost=effective_opportunity_cost,
                    opportunity_edge=opportunity_edge,
                    best_alternative_identifier=best_alternative.identifier,
                    best_alternative_kind=best_alternative.kind,
                    baseline_alternative_identifier=baseline_alternative.identifier,
                    baseline_opportunity_cost=baseline_opportunity_cost,
                    resolved_policy_profile=profile.identifier,
                    reasons=(
                        f"{lane.value} lane: hard evidence, liquidity, downside, cost, and integrity controls passed",
                        *tuple(dict.fromkeys(soft_reasons)),
                    ),
                    analysis_lane=lane,
                ),
                robustness,
            )
        return (
            CandidateQualification(
                candidate_identifier=candidate.identifier,
                outcome=QualificationOutcome.QUALIFIED,
                policy_version=self.policy.version,
                universe=universe,
                effective_opportunity_cost=effective_opportunity_cost,
                opportunity_edge=opportunity_edge,
                best_alternative_identifier=best_alternative.identifier,
                best_alternative_kind=best_alternative.kind,
                baseline_alternative_identifier=baseline_alternative.identifier,
                resolved_policy_profile=profile.identifier,
                reasons=(
                    "candidate clears full-conviction acquisition requirements; portfolio contribution and final size remain subject to the growth ensemble and independent construction",
                ),
            ),
            robustness,
        )
''',
)
replace_once(
    "opportunity/engine.py",
    '        reliability = max(\n            0.10,\n',
    '        reliability = max(\n            0.35,\n',
)
print("growth opportunity integration patched")
