"""Candidate, thesis, liquidity, and joint-portfolio risk intelligence.

These diagnostics enrich the existing Portfolio & Risk specialist. They do not
create a seventh specialist, authorize a trade, or replace the robust assessor and
portfolio-construction survival controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite, sqrt
from typing import Iterable

from cio import CandidateDecisionRecord, PayoffDistributionPoint


def _finite(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


def _clamp(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, float(value))), 8)


def _distribution(candidate: CandidateDecisionRecord) -> tuple[PayoffDistributionPoint, ...]:
    if candidate.payoff_distribution:
        return candidate.payoff_distribution
    return (
        PayoffDistributionPoint(
            "bear",
            candidate.bear_case_return,
            candidate.bear_case_probability,
        ),
        PayoffDistributionPoint(
            "base",
            candidate.base_case_return,
            candidate.base_case_probability,
        ),
        PayoffDistributionPoint(
            "bull",
            candidate.bull_case_return,
            candidate.bull_case_probability,
        ),
    )


def _weighted_tail_mean(
    points: tuple[PayoffDistributionPoint, ...],
    *,
    tail_probability: float,
) -> float:
    remaining = tail_probability
    total = 0.0
    used = 0.0
    for point in sorted(points, key=lambda item: item.total_return):
        if remaining <= 0.0:
            break
        take = min(remaining, point.probability)
        total += point.total_return * take
        used += take
        remaining -= take
    if used <= 0.0:
        return 0.0
    return round(total / used, 8)


def _factor_similarity(
    first: tuple[tuple[str, float], ...],
    second: tuple[tuple[str, float], ...],
) -> float:
    left = dict(first)
    right = dict(second)
    names = set(left).union(right)
    if not names:
        return 0.0
    dot = sum(left.get(name, 0.0) * right.get(name, 0.0) for name in names)
    norm_left = sqrt(sum(left.get(name, 0.0) ** 2 for name in names))
    norm_right = sqrt(sum(right.get(name, 0.0) ** 2 for name in names))
    if norm_left <= 0.0 or norm_right <= 0.0:
        return 0.0
    return _clamp(dot / (norm_left * norm_right), -1.0, 1.0)


@dataclass(frozen=True, slots=True)
class CandidateRiskPolicy:
    version: str = "candidate-risk-intelligence.v1"
    expected_shortfall_tail_probability: float = 0.10
    maximum_daily_volume_participation: float = 0.10
    stressed_volume_fraction: float = 0.35
    stressed_cost_multiplier: float = 4.0
    maximum_stressed_days_to_exit: float = 10.0
    severe_conditional_loss: float = -0.35
    severe_expected_shortfall: float = -0.25

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        for field_name in (
            "expected_shortfall_tail_probability",
            "maximum_daily_volume_participation",
            "stressed_volume_fraction",
        ):
            value = _finite(getattr(self, field_name), field_name=field_name)
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{field_name} must be in (0, 1]")
        if self.stressed_cost_multiplier < 1.0:
            raise ValueError("stressed_cost_multiplier must be at least 1")
        if self.maximum_stressed_days_to_exit <= 0.0:
            raise ValueError("maximum_stressed_days_to_exit must be positive")
        if self.severe_conditional_loss >= 0.0 or self.severe_expected_shortfall >= 0.0:
            raise ValueError("severe loss thresholds must be negative")


@dataclass(frozen=True, slots=True)
class CandidateRiskAssessment:
    candidate_identifier: str
    symbol: str
    policy_version: str
    proposed_weight: float
    probability_of_loss: float
    conditional_loss_given_failure: float
    expected_shortfall: float
    upside_to_conditional_downside: float
    probability_below_alternative: float
    expected_time_underwater_days: float
    expected_recovery_days: float
    normal_days_to_exit: float
    stressed_days_to_exit: float
    stressed_execution_cost_return: float
    assumption_concentration: float
    invalidation_clarity: float
    edge_half_life_days: float
    fragility_score: float
    hard_blocks: tuple[str, ...]
    diagnostics: tuple[str, ...]

    @property
    def liquid_under_stress(self) -> bool:
        return not any("liquidity" in item.lower() for item in self.hard_blocks)

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_identifier": self.candidate_identifier,
            "symbol": self.symbol,
            "policy_version": self.policy_version,
            "proposed_weight": self.proposed_weight,
            "probability_of_loss": self.probability_of_loss,
            "conditional_loss_given_failure": self.conditional_loss_given_failure,
            "expected_shortfall": self.expected_shortfall,
            "upside_to_conditional_downside": self.upside_to_conditional_downside,
            "probability_below_alternative": self.probability_below_alternative,
            "expected_time_underwater_days": self.expected_time_underwater_days,
            "expected_recovery_days": self.expected_recovery_days,
            "normal_days_to_exit": self.normal_days_to_exit,
            "stressed_days_to_exit": self.stressed_days_to_exit,
            "stressed_execution_cost_return": self.stressed_execution_cost_return,
            "assumption_concentration": self.assumption_concentration,
            "invalidation_clarity": self.invalidation_clarity,
            "edge_half_life_days": self.edge_half_life_days,
            "fragility_score": self.fragility_score,
            "hard_blocks": list(self.hard_blocks),
            "diagnostics": list(self.diagnostics),
        }


class CandidateRiskIntelligenceEngine:
    """Derive decision-useful risk metrics without duplicating economic gates."""

    def __init__(self, policy: CandidateRiskPolicy | None = None) -> None:
        self.policy = policy or CandidateRiskPolicy()

    def assess(
        self,
        candidate: CandidateDecisionRecord,
        *,
        portfolio_value: float,
        proposed_weight: float,
        alternative_return: float,
        invalidation_clarity: float = 0.50,
    ) -> CandidateRiskAssessment:
        portfolio_value = _finite(portfolio_value, field_name="portfolio_value")
        proposed_weight = _finite(proposed_weight, field_name="proposed_weight")
        alternative_return = _finite(
            alternative_return,
            field_name="alternative_return",
        )
        if portfolio_value <= 0.0:
            raise ValueError("portfolio_value must be positive")
        if not 0.0 <= proposed_weight <= 1.0:
            raise ValueError("proposed_weight must be between 0 and 1")
        if not 0.0 <= invalidation_clarity <= 1.0:
            raise ValueError("invalidation_clarity must be between 0 and 1")

        points = _distribution(candidate)
        loss_points = tuple(item for item in points if item.total_return < 0.0)
        probability_of_loss = sum(item.probability for item in loss_points)
        conditional_loss = (
            0.0
            if probability_of_loss <= 0.0
            else sum(item.total_return * item.probability for item in loss_points)
            / probability_of_loss
        )
        expected_shortfall = _weighted_tail_mean(
            points,
            tail_probability=self.policy.expected_shortfall_tail_probability,
        )
        positive = sum(
            max(0.0, item.total_return) * item.probability for item in points
        )
        downside = abs(
            sum(min(0.0, item.total_return) * item.probability for item in points)
        )
        upside_ratio = positive / max(downside, 0.000001)
        horizon_alternative = (1.0 + alternative_return) ** (
            candidate.decision_horizon_days / 365.0
        ) - 1.0
        probability_below_alternative = sum(
            item.probability
            for item in points
            if item.total_return - candidate.implementation_cost_return
            <= horizon_alternative
        )
        underwater_days = candidate.decision_horizon_days * min(
            1.0,
            probability_of_loss + 0.50 * probability_below_alternative,
        )
        annual_recovery_rate = max(
            0.01,
            candidate.net_expected_return,
            alternative_return,
        )
        recovery_days = min(
            3650.0,
            abs(min(0.0, conditional_loss)) / annual_recovery_rate * 365.0,
        )

        position_dollars = portfolio_value * proposed_weight
        adv = candidate.instrument.average_daily_dollar_volume
        normal_capacity = adv * self.policy.maximum_daily_volume_participation
        stressed_capacity = normal_capacity * self.policy.stressed_volume_fraction
        normal_days = (
            float("inf") if normal_capacity <= 0.0 else position_dollars / normal_capacity
        )
        stressed_days = (
            float("inf")
            if stressed_capacity <= 0.0
            else position_dollars / stressed_capacity
        )
        base_cost = candidate.implementation_cost_return
        stressed_cost = base_cost * self.policy.stressed_cost_multiplier * max(
            1.0,
            min(stressed_days, self.policy.maximum_stressed_days_to_exit * 2.0),
        )

        assumption_count = max(1, len(candidate.critical_assumptions))
        assumption_concentration = 1.0 / assumption_count
        evidence_durability = (
            0.45 * candidate.evidence_quality.freshness
            + 0.35 * candidate.evidence_quality.completeness
            + 0.20 * candidate.evidence_quality.independence
        )
        edge_half_life = candidate.decision_horizon_days * max(
            0.10,
            evidence_durability,
        )
        fragility = _clamp(
            0.25 * assumption_concentration
            + 0.20 * (1.0 - invalidation_clarity)
            + 0.20 * probability_below_alternative
            + 0.20 * min(1.0, recovery_days / max(1.0, candidate.decision_horizon_days * 2.0))
            + 0.15 * (1.0 - evidence_durability),
            0.0,
            1.0,
        )

        blocks: list[str] = []
        if stressed_days > self.policy.maximum_stressed_days_to_exit:
            blocks.append(
                "Stress liquidity cannot exit the proposed position within "
                f"{self.policy.maximum_stressed_days_to_exit:.0f} days"
            )
        if conditional_loss <= self.policy.severe_conditional_loss and (
            expected_shortfall <= self.policy.severe_expected_shortfall
        ):
            blocks.append(
                "Candidate conditional loss and expected shortfall jointly exceed "
                "the severe tail-loss review threshold"
            )
        diagnostics = (
            f"Probability of loss={probability_of_loss:.1%}",
            f"Conditional loss given failure={conditional_loss:.1%}",
            f"Candidate expected shortfall={expected_shortfall:.1%}",
            f"Probability below best alternative={probability_below_alternative:.1%}",
            f"Expected time underwater={underwater_days:.0f} days",
            f"Expected recovery proxy={recovery_days:.0f} days",
            f"Stress exit horizon={stressed_days:.2f} days",
            f"Stressed execution cost={stressed_cost:.2%}",
            f"Thesis fragility={fragility:.0%}",
            f"Estimated edge half-life={edge_half_life:.0f} days",
        )
        return CandidateRiskAssessment(
            candidate_identifier=candidate.identifier,
            symbol=candidate.instrument.symbol,
            policy_version=self.policy.version,
            proposed_weight=round(proposed_weight, 8),
            probability_of_loss=round(probability_of_loss, 8),
            conditional_loss_given_failure=round(conditional_loss, 8),
            expected_shortfall=round(expected_shortfall, 8),
            upside_to_conditional_downside=round(upside_ratio, 8),
            probability_below_alternative=round(probability_below_alternative, 8),
            expected_time_underwater_days=round(underwater_days, 8),
            expected_recovery_days=round(recovery_days, 8),
            normal_days_to_exit=round(normal_days, 8),
            stressed_days_to_exit=round(stressed_days, 8),
            stressed_execution_cost_return=round(stressed_cost, 8),
            assumption_concentration=round(assumption_concentration, 8),
            invalidation_clarity=round(invalidation_clarity, 8),
            edge_half_life_days=round(edge_half_life, 8),
            fragility_score=fragility,
            hard_blocks=tuple(blocks),
            diagnostics=diagnostics,
        )


class JointCandidateRelation(str, Enum):
    COMPLEMENTARY = "complementary"
    MUTUALLY_EXCLUSIVE = "mutually_exclusive"
    DOMINATED = "dominated"
    BASKET_CANDIDATE = "basket_candidate"
    INDEPENDENT = "independent"


@dataclass(frozen=True, slots=True)
class JointCandidateAssessment:
    first_candidate_identifier: str
    second_candidate_identifier: str
    relation: JointCandidateRelation
    factor_similarity: float
    same_correlation_bucket: bool
    tail_dependence: float
    preferred_candidate_identifier: str | None
    explanation: str

    def to_dict(self) -> dict[str, object]:
        return {
            "first_candidate_identifier": self.first_candidate_identifier,
            "second_candidate_identifier": self.second_candidate_identifier,
            "relation": self.relation.value,
            "factor_similarity": self.factor_similarity,
            "same_correlation_bucket": self.same_correlation_bucket,
            "tail_dependence": self.tail_dependence,
            "preferred_candidate_identifier": self.preferred_candidate_identifier,
            "explanation": self.explanation,
        }


class JointCandidateIntelligenceEngine:
    """Classify candidate pairs before final construction resolves competition."""

    def assess(
        self,
        candidates: tuple[CandidateDecisionRecord, ...],
        risk_assessments: tuple[CandidateRiskAssessment, ...],
        exposure_profiles: Iterable[object],
    ) -> tuple[JointCandidateAssessment, ...]:
        risk_by_id = {item.candidate_identifier: item for item in risk_assessments}
        profile_by_id = {
            getattr(item, "candidate_identifier"): item for item in exposure_profiles
        }
        values: list[JointCandidateAssessment] = []
        for index, first in enumerate(candidates):
            for second in candidates[index + 1 :]:
                first_profile = profile_by_id[first.identifier]
                second_profile = profile_by_id[second.identifier]
                similarity = _factor_similarity(
                    getattr(first_profile, "factor_loadings"),
                    getattr(second_profile, "factor_loadings"),
                )
                same_bucket = (
                    getattr(first_profile, "correlation_bucket")
                    == getattr(second_profile, "correlation_bucket")
                )
                tail_dependence = _clamp(
                    0.55 * max(0.0, similarity)
                    + 0.35 * float(same_bucket)
                    + 0.10
                    * min(
                        risk_by_id[first.identifier].probability_of_loss,
                        risk_by_id[second.identifier].probability_of_loss,
                    ),
                    0.0,
                    1.0,
                )
                first_quality = (
                    first.net_expected_return
                    - abs(risk_by_id[first.identifier].expected_shortfall)
                    - risk_by_id[first.identifier].stressed_execution_cost_return
                )
                second_quality = (
                    second.net_expected_return
                    - abs(risk_by_id[second.identifier].expected_shortfall)
                    - risk_by_id[second.identifier].stressed_execution_cost_return
                )
                preferred = (
                    first.identifier if first_quality >= second_quality else second.identifier
                )
                quality_gap = abs(first_quality - second_quality)
                if similarity < -0.20 and tail_dependence < 0.35:
                    relation = JointCandidateRelation.COMPLEMENTARY
                    explanation = (
                        "Opposing factor behavior and low tail dependence may improve the "
                        "portfolio when the candidates are evaluated together."
                    )
                    preferred = None
                elif same_bucket and similarity > 0.75 and quality_gap >= 0.02:
                    relation = JointCandidateRelation.MUTUALLY_EXCLUSIVE
                    explanation = (
                        "The candidates consume substantially the same correlation and "
                        "factor capacity; the stronger risk-adjusted candidate dominates."
                    )
                elif quality_gap >= 0.05 and tail_dependence >= 0.45:
                    relation = JointCandidateRelation.DOMINATED
                    explanation = (
                        "One candidate has materially weaker return after tail loss and "
                        "stress execution cost without adding enough diversification."
                    )
                elif same_bucket and 0.30 <= similarity <= 0.75 and quality_gap < 0.02:
                    relation = JointCandidateRelation.BASKET_CANDIDATE
                    explanation = (
                        "The candidates express related return drivers with comparable "
                        "risk-adjusted economics and may warrant bounded basket analysis."
                    )
                    preferred = None
                else:
                    relation = JointCandidateRelation.INDEPENDENT
                    explanation = (
                        "The pair does not show a strong complementary, competing, or "
                        "dominance relationship at the current evidence boundary."
                    )
                    preferred = None
                values.append(
                    JointCandidateAssessment(
                        first_candidate_identifier=first.identifier,
                        second_candidate_identifier=second.identifier,
                        relation=relation,
                        factor_similarity=similarity,
                        same_correlation_bucket=same_bucket,
                        tail_dependence=tail_dependence,
                        preferred_candidate_identifier=preferred,
                        explanation=explanation,
                    )
                )
        return tuple(values)


__all__ = [
    "CandidateRiskAssessment",
    "CandidateRiskIntelligenceEngine",
    "CandidateRiskPolicy",
    "JointCandidateAssessment",
    "JointCandidateIntelligenceEngine",
    "JointCandidateRelation",
]
