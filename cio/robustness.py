"""Compounding-aware robustness controls for canonical candidate decisions.

Scenario forecasts are converted into annualized portfolio-slice geometric
returns, shrunk toward the best alternative when evidence is weak, penalized for
uncertainty, and stressed by shifting probability toward the bear case.  The
result is an abstention control, not a performance promise.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, floor, isfinite, log1p, sqrt

from cio.models import CandidateDecisionRecord
from cio.policy_matrix import DecisionPolicyProfile


def _finite(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class RobustDecisionPolicy:
    version: str = "robust-decision.v3"
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
    horizon_alternative_return: float
    effective_probability_of_success: float
    robust_edge: float
    stressed_edge: float
    scenario_dispersion: float
    probability_of_loss: float
    probability_consistency_gap: float
    worst_case_portfolio_return: float
    edge_to_uncertainty: float
    durability_factor: float
    durability_adjusted_return: float
    resolved_policy_profile: str | None
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
        position_weight: float | None = None,
        policy_profile: DecisionPolicyProfile | None = None,
    ) -> RobustCandidateAssessment:
        if not isinstance(candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be a CandidateDecisionRecord")
        alternative = _finite(alternative_return, field_name="alternative_return")
        weight = self._position_weight(candidate, position_weight=position_weight)
        distribution = candidate.scenario_distribution
        returns = tuple(item.total_return for item in distribution)
        probabilities = tuple(item.probability for item in distribution)
        labels = {item.label.lower(): item.total_return for item in distribution}
        reasons: list[str] = []
        if {"base", "bull", "bear"}.issubset(labels) and not (
            labels["bear"] <= labels["base"] <= labels["bull"]
        ):
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
        durability = self._durability_factor(candidate, policy_profile=policy_profile)
        annualization_cap = (
            policy_profile.annualization_cap
            if policy_profile is not None
            else 1.0
        )
        capped_geometric = max(-annualization_cap, min(annualization_cap, geometric))
        durable_geometric = alternative + durability * (capped_geometric - alternative)
        dispersion = sqrt(
            max(
                sum(
                    probability * (value - durable_geometric) ** 2
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
            + reliability * (durable_geometric - alternative)
            - self.policy.uncertainty_penalty * dispersion
        )
        stressed_geometric_raw = self._geometric(
            annualized,
            self._stress(probabilities, returns=returns),
            weight,
        )
        stressed_geometric_capped = max(
            -annualization_cap, min(annualization_cap, stressed_geometric_raw)
        )
        stressed_geometric = alternative + durability * (
            stressed_geometric_capped - alternative
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
        horizon_alternative = self.horizon_return(
            alternative,
            horizon_days=candidate.decision_horizon_days,
        )
        implied_success = sum(
            probability
            for value, probability in zip(returns, probabilities, strict=True)
            if value - candidate.implementation_cost_return > horizon_alternative
        )
        probability_gap = round(
            abs(candidate.probability_of_success - implied_success),
            10,
        )
        worst_portfolio_return = min(portfolio_returns)
        edge_to_uncertainty = robust_edge / max(dispersion, 0.000001)

        minimum_robust_edge = (
            policy_profile.minimum_robust_edge
            if policy_profile is not None
            else self.policy.minimum_robust_edge
        )
        maximum_probability_of_loss = (
            policy_profile.maximum_probability_of_loss
            if policy_profile is not None
            else self.policy.maximum_probability_of_loss
        )
        minimum_worst_case = (
            policy_profile.minimum_worst_case_portfolio_return
            if policy_profile is not None
            else self.policy.minimum_worst_case_portfolio_return
        )
        if robust_edge < minimum_robust_edge:
            reasons.append(
                "evidence-adjusted geometric return does not clear the best alternative by the required margin"
            )
        stressed_floor = self.policy.minimum_stressed_edge
        if policy_profile is not None:
            stressed_floor = min(stressed_floor, -0.001)
        if stressed_edge < stressed_floor:
            reasons.append(
                "the candidate loses its opportunity edge after an adverse scenario-probability shift"
            )
        if edge_to_uncertainty < self.policy.minimum_edge_to_uncertainty:
            reasons.append(
                "the robust opportunity edge is too small relative to scenario uncertainty"
            )
        if probability_of_loss > maximum_probability_of_loss:
            reasons.append("scenario-implied probability of loss exceeds policy")
        if probability_gap > self.policy.maximum_probability_consistency_gap:
            reasons.append(
                "stated probability of success is inconsistent with the disclosed scenarios"
            )
        if worst_portfolio_return < minimum_worst_case:
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
            horizon_alternative_return=round(horizon_alternative, 10),
            effective_probability_of_success=round(implied_success, 10),
            robust_edge=round(robust_edge, 10),
            stressed_edge=round(stressed_edge, 10),
            scenario_dispersion=round(dispersion, 10),
            probability_of_loss=round(probability_of_loss, 10),
            probability_consistency_gap=probability_gap,
            worst_case_portfolio_return=round(worst_portfolio_return, 10),
            edge_to_uncertainty=round(edge_to_uncertainty, 10),
            durability_factor=round(durability, 10),
            durability_adjusted_return=round(durable_geometric, 10),
            resolved_policy_profile=(
                None if policy_profile is None else policy_profile.identifier
            ),
            passed=not unique_reasons,
            reasons=unique_reasons,
        )


    def maximum_supported_weight(
        self,
        candidate: CandidateDecisionRecord,
        *,
        alternative_return: float,
        maximum_weight: float | None = None,
        policy_profile: DecisionPolicyProfile | None = None,
    ) -> float:
        """Return the largest target that passes the complete robustness policy.

        The search evaluates the final candidate distribution at the actual target
        weight.  It is intentionally conservative: when even the smallest feasible
        test weight fails, no positive robust allocation is returned.
        """

        if not isinstance(candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be a CandidateDecisionRecord")
        cap = candidate.maximum_position_weight
        if policy_profile is not None:
            cap = min(cap, policy_profile.maximum_position_weight)
        if maximum_weight is not None:
            requested = _finite(maximum_weight, field_name="maximum_weight")
            if not 0.0 <= requested <= 1.0:
                raise ValueError("maximum_weight must be between 0.0 and 1.0")
            cap = min(cap, requested)
        if cap <= 0.0:
            return 0.0

        if self.assess(
            candidate,
            alternative_return=alternative_return,
            position_weight=cap,
            policy_profile=policy_profile,
        ).passed:
            return round(cap, 8)

        floor_weight = min(self.policy.minimum_reference_weight, cap)
        if not self.assess(
            candidate,
            alternative_return=alternative_return,
            position_weight=floor_weight,
            policy_profile=policy_profile,
        ).passed:
            return 0.0

        low = floor_weight
        high = cap
        for _ in range(50):
            middle = (low + high) / 2.0
            if self.assess(
                candidate,
                alternative_return=alternative_return,
                position_weight=middle,
                policy_profile=policy_profile,
            ).passed:
                low = middle
            else:
                high = middle
        supported = floor(low * 100_000_000) / 100_000_000
        while supported > 0.0:
            if self.assess(
                candidate,
                alternative_return=alternative_return,
                position_weight=supported,
                policy_profile=policy_profile,
            ).passed:
                return round(supported, 8)
            supported = round(max(0.0, supported - 0.00000001), 8)
        return 0.0


    @staticmethod
    def _durability_factor(
        candidate: CandidateDecisionRecord,
        *,
        policy_profile: DecisionPolicyProfile | None,
    ) -> float:
        """Penalize fragile annualized short-horizon forecasts.

        A forecast should not dominate a long-horizon compounding opportunity merely
        because a small total return annualizes to an extreme number.  Evidence
        reliability remains handled separately; this factor captures forecast half-life.
        """

        horizon_factor = min(1.0, max(0.15, candidate.decision_horizon_days / 90.0))
        floor = (
            policy_profile.forecast_durability_floor
            if policy_profile is not None
            else 0.50
        )
        evidence_factor = (
            0.50 * candidate.evidence_quality.freshness
            + 0.30 * candidate.evidence_quality.completeness
            + 0.20 * candidate.evidence_quality.independence
        )
        return max(floor, min(1.0, horizon_factor * evidence_factor))

    def _position_weight(
        self,
        candidate: CandidateDecisionRecord,
        *,
        position_weight: float | None,
    ) -> float:
        if position_weight is None:
            return min(
                max(
                    candidate.maximum_position_weight,
                    self.policy.minimum_reference_weight,
                ),
                self.policy.reference_position_weight,
            )
        requested = _finite(position_weight, field_name="position_weight")
        if not 0.0 < requested <= 1.0:
            raise ValueError("position_weight must be above 0.0 and at most 1.0")
        if requested > candidate.maximum_position_weight + 1e-12:
            raise ValueError(
                "position_weight cannot exceed candidate.maximum_position_weight"
            )
        return requested

    @staticmethod
    def horizon_return(annual_return: float, *, horizon_days: int) -> float:
        """Convert an annual capital alternative into the candidate horizon."""

        years = horizon_days / 365.25
        if annual_return <= -1.0:
            return -1.0
        return exp(log1p(annual_return) * years) - 1.0

    _horizon_return = horizon_return

    @staticmethod
    def _annualized_scenarios(
        candidate: CandidateDecisionRecord,
        *,
        returns: tuple[float, ...],
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
        probabilities: tuple[float, ...],
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
        probabilities: tuple[float, ...],
        *,
        returns: tuple[float, ...],
    ) -> tuple[float, ...]:
        """Shift probability from the strongest outcomes to the worst outcome."""

        if len(probabilities) != len(returns) or not probabilities:
            raise ValueError("stress inputs must be non-empty and aligned")
        stressed = list(probabilities)
        worst_index = min(range(len(returns)), key=returns.__getitem__)
        remaining = self.policy.bear_probability_shift
        donor_indices = sorted(
            (index for index in range(len(returns)) if index != worst_index),
            key=lambda index: returns[index],
            reverse=True,
        )
        for index in donor_indices:
            if remaining <= 0.0:
                break
            reduction = min(stressed[index], remaining)
            stressed[index] -= reduction
            stressed[worst_index] += reduction
            remaining -= reduction
        return tuple(stressed)


__all__ = [
    "RobustCandidateAssessment",
    "RobustCandidateAssessor",
    "RobustDecisionPolicy",
]
