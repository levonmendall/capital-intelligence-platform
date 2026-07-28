"""Compounding-aware robustness controls for canonical candidate decisions.

Scenario forecasts are converted into annualized portfolio-slice geometric
returns, shrunk toward the best alternative when evidence is weak, penalized for
uncertainty, and stressed by shifting probability toward the bear case.  The
result is an abstention control, not a performance promise.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log1p, sqrt

from cio.models import CandidateDecisionRecord


def _finite(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class RobustDecisionPolicy:
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
    maximum_probability_consistency_gap: float = 0.25
    minimum_worst_case_portfolio_return: float = -0.05

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version cannot be empty")
        for name in (
            "reference_position_weight",
            "minimum_reference_weight",
            "evidence_shrinkage_floor",
            "uncertainty_penalty",
            "bear_probability_shift",
            "minimum_edge_to_uncertainty",
            "maximum_probability_of_loss",
            "maximum_probability_consistency_gap",
        ):
            value = _finite(getattr(self, name), field_name=name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0.0 and 1.0")
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
        if not self.candidate_identifier.strip() or not self.policy_version.strip():
            raise ValueError("assessment identifiers cannot be empty")
        if self.passed == bool(self.reasons):
            raise ValueError("assessment pass state and reasons are inconsistent")


class RobustCandidateAssessor:
    """Create conservative robustness diagnostics from disclosed scenarios."""

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
        returns = (
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
        if not candidate.bear_case_return <= candidate.base_case_return <= candidate.bull_case_return:
            reasons.append(
                "scenario ordering must satisfy bear case <= base case <= bull case"
            )

        annualized, portfolio_returns, valid_wealth = self._annualized_scenarios(
            candidate,
            returns=returns,
            weight=weight,
        )
        if not valid_wealth:
            reasons.append(
                "at least one scenario produces non-positive portfolio wealth at the reference weight"
            )
        geometric = self._geometric(annualized, probabilities, weight)
        dispersion = sqrt(
            max(
                sum(
                    probability * (value - geometric) ** 2
                    for value, probability in zip(
                        annualized,
                        probabilities,
                        strict=True,
                    )
                ),
                0.0,
            )
        )
        reliability = max(
            self.policy.evidence_shrinkage_floor,
            sqrt(candidate.evidence_quality.score * candidate.evidence_quality.ceiling),
        )
        adjusted = (
            alternative
            + reliability * (geometric - alternative)
            - self.policy.uncertainty_penalty * dispersion
        )
        stressed_geometric = self._geometric(
            annualized,
            self._stress(probabilities),
            weight,
        )
        stressed_adjusted = (
            alternative
            + reliability * (stressed_geometric - alternative)
            - self.policy.uncertainty_penalty * dispersion
        )
        robust_edge = adjusted - alternative
        stressed_edge = stressed_adjusted - alternative
        probability_of_loss = sum(
            probability
            for value, probability in zip(returns, probabilities, strict=True)
            if value - candidate.implementation_cost_return < 0.0
        )
        implied_success = sum(
            probability
            for value, probability in zip(returns, probabilities, strict=True)
            if value - candidate.implementation_cost_return > 0.0
        )
        probability_gap = round(
            abs(candidate.probability_of_success - implied_success),
            10,
        )
        worst_portfolio_return = min(portfolio_returns)
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
        if worst_portfolio_return < self.policy.minimum_worst_case_portfolio_return:
            reasons.append(
                "worst-case portfolio loss at the reference weight exceeds policy"
            )

        unique_reasons = tuple(dict.fromkeys(reasons))
        return RobustCandidateAssessment(
            candidate_identifier=candidate.identifier,
            policy_version=self.policy.version,
            reference_position_weight=round(weight, 10),
            evidence_reliability=round(reliability, 10),
            annualized_geometric_return=round(geometric, 10),
            evidence_adjusted_return=round(adjusted, 10),
            stressed_evidence_adjusted_return=round(stressed_adjusted, 10),
            alternative_return=round(alternative, 10),
            robust_edge=round(robust_edge, 10),
            stressed_edge=round(stressed_edge, 10),
            scenario_dispersion=round(dispersion, 10),
            probability_of_loss=round(probability_of_loss, 10),
            probability_consistency_gap=probability_gap,
            worst_case_portfolio_return=round(worst_portfolio_return, 10),
            edge_to_uncertainty=round(edge_to_uncertainty, 10),
            passed=not unique_reasons,
            reasons=unique_reasons,
        )

    @staticmethod
    def _annualized_scenarios(
        candidate: CandidateDecisionRecord,
        *,
        returns: tuple[float, float, float],
        weight: float,
    ) -> tuple[tuple[float, ...], tuple[float, ...], bool]:
        years = candidate.decision_horizon_days / 365.25
        annualized: list[float] = []
        portfolio_returns: list[float] = []
        valid = True
        for scenario_return in returns:
            portfolio_return = weight * (
                scenario_return - candidate.implementation_cost_return
            )
            portfolio_returns.append(portfolio_return)
            gross = 1.0 + portfolio_return
            if gross <= 0.0:
                valid = False
                annualized.append(-1.0 / weight)
            else:
                annualized.append((exp(log1p(portfolio_return) / years) - 1.0) / weight)
        return tuple(annualized), tuple(portfolio_returns), valid

    @staticmethod
    def _geometric(
        returns: tuple[float, ...],
        probabilities: tuple[float, float, float],
        weight: float,
    ) -> float:
        expected_log = 0.0
        for value, probability in zip(returns, probabilities, strict=True):
            gross = 1.0 + weight * value
            if gross <= 0.0:
                return -1.0 / weight
            expected_log += probability * log1p(weight * value)
        return (exp(expected_log) - 1.0) / weight

    def _stress(
        self,
        probabilities: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        base, bull, bear = probabilities
        remaining = self.policy.bear_probability_shift
        reduction = min(bull, remaining)
        bull -= reduction
        bear += reduction
        remaining -= reduction
        reduction = min(base, remaining)
        base -= reduction
        bear += reduction
        return base, bull, bear


__all__ = [
    "RobustCandidateAssessment",
    "RobustCandidateAssessor",
    "RobustDecisionPolicy",
]
