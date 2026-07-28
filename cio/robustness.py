"""Robust, compounding-aware candidate assessment before capital is committed.

The canonical candidate schema contains scenario returns and probabilities.  This
module converts those inputs into a portfolio-slice geometric return, shrinks the
result toward the best available alternative when evidence is weak, penalizes
scenario dispersion, and repeats the calculation under an adverse probability
shift.  It is a qualification and abstention control, not a performance promise.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log1p, sqrt

from cio.models import CandidateDecisionRecord


def _finite(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


@dataclass(frozen=True, slots=True)
class RobustDecisionPolicy:
    """Versioned robustness rules applied before specialist review and CIO action."""

    version: str = "robust-decision.v1"
    reference_position_weight: float = 0.05
    minimum_reference_weight: float = 0.01
    evidence_shrinkage_floor: float = 0.10
    uncertainty_penalty: float = 0.10
    bear_probability_shift: float = 0.03
    minimum_robust_edge: float = 0.005
    minimum_stressed_edge: float = 0.0
    minimum_edge_to_uncertainty: float = 0.03
    maximum_probability_of_loss: float = 0.45
    maximum_probability_consistency_gap: float = 0.15
    minimum_worst_case_portfolio_return: float = -0.05

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version cannot be empty")
        for field_name in (
            "reference_position_weight",
            "minimum_reference_weight",
            "evidence_shrinkage_floor",
            "uncertainty_penalty",
            "bear_probability_shift",
            "minimum_edge_to_uncertainty",
            "maximum_probability_of_loss",
            "maximum_probability_consistency_gap",
        ):
            value = _finite(getattr(self, field_name), field_name=field_name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0.0 and 1.0")
        if self.minimum_reference_weight <= 0.0:
            raise ValueError("minimum_reference_weight must be positive")
        if self.reference_position_weight < self.minimum_reference_weight:
            raise ValueError(
                "reference_position_weight cannot be below minimum_reference_weight"
            )
        if self.minimum_worst_case_portfolio_return >= 0.0:
            raise ValueError("minimum_worst_case_portfolio_return must be negative")


@dataclass(frozen=True, slots=True)
class RobustCandidateAssessment:
    """Auditable robustness diagnostics for one candidate and capital alternative."""

    candidate_identifier: str
    policy_version: str
    reference_position_weight: float
    evidence_reliability: float
    annualized_geometric_return: float
    evidence_adjusted_return: float
    stressed_evidence_adjusted_return: float
    alternative_return: float
    robust_edge: float
    stressed_edge: float
    scenario_dispersion: float
    probability_of_loss: float
    probability_consistency_gap: float
    worst_case_portfolio_return: float
    edge_to_uncertainty: float
    passed: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.candidate_identifier.strip():
            raise ValueError("candidate_identifier cannot be empty")
        if not self.policy_version.strip():
            raise ValueError("policy_version cannot be empty")
        if self.passed and self.reasons:
            raise ValueError("a passing assessment cannot contain rejection reasons")
        if not self.passed and not self.reasons:
            raise ValueError("a failing assessment requires reasons")


class RobustCandidateAssessor:
    """Convert scenario forecasts into conservative capital-allocation evidence."""

    def __init__(self, policy: RobustDecisionPolicy | None = None) -> None:
        self.policy = policy or RobustDecisionPolicy()

    def assess(
        self,
        candidate: CandidateDecisionRecord,
        *,
        alternative_return: float,
    ) -> RobustCandidateAssessment:
        if not isinstance(candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be a CandidateDecisionRecord")
        alternative = _finite(alternative_return, field_name="alternative_return")
        weight = min(
            max(candidate.maximum_position_weight, self.policy.minimum_reference_weight),
            self.policy.reference_position_weight,
        )
        scenario_returns = (
            candidate.base_case_return,
            candidate.bull_case_return,
            candidate.bear_case_return,
        )
        probabilities = (
            candidate.base_case_probability,
            candidate.bull_case_probability,
            candidate.bear_case_probability,
        )
        reasons: list[str] = []
        if not (
            candidate.bear_case_return
            <= candidate.base_case_return
            <= candidate.bull_case_return
        ):
            reasons.append(
                "scenario ordering must satisfy bear case <= base case <= bull case"
            )

        annualized_scenarios, portfolio_scenarios, valid_wealth = self._scenario_values(
            candidate,
            scenario_returns=scenario_returns,
            weight=weight,
        )
        if not valid_wealth:
            reasons.append(
                "at least one scenario produces non-positive portfolio wealth at the reference weight"
            )

        geometric_return = self._geometric_equivalent(
            annualized_scenarios,
            probabilities=probabilities,
            weight=weight,
        )
        dispersion = self._weighted_dispersion(
            annualized_scenarios,
            probabilities=probabilities,
            center=geometric_return,
        )
        reliability = max(
            self.policy.evidence_shrinkage_floor,
            sqrt(
                candidate.evidence_quality.score
                * candidate.evidence_quality.ceiling
            ),
        )
        evidence_adjusted = (
            alternative + reliability * (geometric_return - alternative)
            - self.policy.uncertainty_penalty * dispersion
        )
        stressed_probabilities = self._stress_probabilities(probabilities)
        stressed_geometric = self._geometric_equivalent(
            annualized_scenarios,
            probabilities=stressed_probabilities,
            weight=weight,
        )
        stressed_adjusted = (
            alternative + reliability * (stressed_geometric - alternative)
            - self.policy.uncertainty_penalty * dispersion
        )
        robust_edge = evidence_adjusted - alternative
        stressed_edge = stressed_adjusted - alternative
        probability_of_loss = sum(
            probability
            for scenario_return, probability in zip(
                scenario_returns,
                probabilities,
                strict=True,
            )
            if scenario_return - candidate.implementation_cost_return < 0.0
        )
        implied_success_probability = sum(
            probability
            for scenario_return, probability in zip(
                scenario_returns,
                probabilities,
                strict=True,
            )
            if scenario_return - candidate.implementation_cost_return > 0.0
        )
        probability_gap = abs(
            candidate.probability_of_success - implied_success_probability
        )
        worst_portfolio_return = min(portfolio_scenarios)
        edge_to_uncertainty = robust_edge / max(dispersion, 0.000001)

        if robust_edge < self.policy.minimum_robust_edge:
            reasons.append(
                "evidence-adjusted geometric return does not clear the best alternative by the required margin"
            )
        if stressed_edge < self.policy.minimum_stressed_edge:
            reasons.append(
                "the candidate loses its opportunity edge after an adverse scenario-probability shift"
            )
        if edge_to_uncertainty < self.policy.minimum_edge_to_uncertainty:
            reasons.append(
                "the robust opportunity edge is too small relative to scenario uncertainty"
            )
        if probability_of_loss > self.policy.maximum_probability_of_loss:
            reasons.append("scenario-implied probability of loss exceeds policy")
        if probability_gap > self.policy.maximum_probability_consistency_gap:
            reasons.append(
                "stated probability of success is inconsistent with the disclosed scenarios"
            )
        if (
            worst_portfolio_return
            < self.policy.minimum_worst_case_portfolio_return
        ):
            reasons.append(
                "worst-case portfolio loss at the reference weight exceeds policy"
            )

        unique_reasons = tuple(dict.fromkeys(reasons))
        return RobustCandidateAssessment(
            candidate_identifier=candidate.identifier,
            policy_version=self.policy.version,
            reference_position_weight=round(weight, 10),
            evidence_reliability=round(reliability, 10),
            annualized_geometric_return=round(geometric_return, 10),
            evidence_adjusted_return=round(evidence_adjusted, 10),
            stressed_evidence_adjusted_return=round(stressed_adjusted, 10),
            alternative_return=round(alternative, 10),
            robust_edge=round(robust_edge, 10),
            stressed_edge=round(stressed_edge, 10),
            scenario_dispersion=round(dispersion, 10),
            probability_of_loss=round(probability_of_loss, 10),
            probability_consistency_gap=round(probability_gap, 10),
            worst_case_portfolio_return=round(worst_portfolio_return, 10),
            edge_to_uncertainty=round(edge_to_uncertainty, 10),
            passed=not unique_reasons,
            reasons=unique_reasons,
        )

    @staticmethod
    def _scenario_values(
        candidate: CandidateDecisionRecord,
        *,
        scenario_returns: tuple[float, float, float],
        weight: float,
    ) -> tuple[tuple[float, ...], tuple[float, ...], bool]:
        years = candidate.decision_horizon_days / 365.25
        annualized: list[float] = []
        portfolio_returns: list[float] = []
        valid_wealth = True
        for scenario_return in scenario_returns:
            portfolio_return = weight * (
                scenario_return - candidate.implementation_cost_return
            )
            portfolio_returns.append(portfolio_return)
            gross_wealth = 1.0 + portfolio_return
            if gross_wealth <= 0.0:
                valid_wealth = False
                annualized.append(-1.0 / weight)
                continue
            annualized_portfolio_return = exp(log1p(portfolio_return) / years) - 1.0
            annualized.append(annualized_portfolio_return / weight)
        return tuple(annualized), tuple(portfolio_returns), valid_wealth

    @staticmethod
    def _geometric_equivalent(
        annualized_scenarios: tuple[float, ...],
        *,
        probabilities: tuple[float, float, float],
        weight: float,
    ) -> float:
        expected_log = 0.0
        for scenario_return, probability in zip(
            annualized_scenarios,
            probabilities,
            strict=True,
        ):
            gross = 1.0 + weight * scenario_return
            if gross <= 0.0:
                return -1.0 / weight
            expected_log += probability * log1p(weight * scenario_return)
        return (exp(expected_log) - 1.0) / weight

    @staticmethod
    def _weighted_dispersion(
        values: tuple[float, ...],
        *,
        probabilities: tuple[float, float, float],
        center: float,
    ) -> float:
        variance = sum(
            probability * (value - center) ** 2
            for value, probability in zip(values, probabilities, strict=True)
        )
        return sqrt(max(variance, 0.0))

    def _stress_probabilities(
        self,
        probabilities: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        base, bull, bear = probabilities
        remaining = self.policy.bear_probability_shift
        bull_reduction = min(bull, remaining)
        bull -= bull_reduction
        remaining -= bull_reduction
        base_reduction = min(base, remaining)
        base -= base_reduction
        bear += bull_reduction + base_reduction
        return base, bull, bear


__all__ = [
    "RobustCandidateAssessment",
    "RobustCandidateAssessor",
    "RobustDecisionPolicy",
]
