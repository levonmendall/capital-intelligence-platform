# Adaptive robust growth ensemble for progressive compounding allocations.
#
# The ensemble converts the existing independent specialist packet into a bounded
# growth stage and position multiplier. It cannot create a candidate, bypass an
# evidence veto, authorize execution, or override portfolio construction.

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import exp, log
from statistics import pstdev
from typing import Iterable

from cio.committee import IndependentSpecialistPacket
from cio.models import CandidateDecisionRecord, SpecialistPosition, SpecialistRole
from cio.policy_matrix import DecisionPolicyProfile
from cio.robustness import RobustCandidateAssessment


class GrowthStage(str, Enum):
    OBSERVE = "observe"
    EXPLORE = "explore"
    VALIDATE = "validate"
    QUALIFIED = "qualified"
    ESTABLISHED = "established"
    STRATEGIC = "strategic"


@dataclass(frozen=True, slots=True)
class GrowthEnsemblePolicy:
    version: str = "adaptive-robust-growth-ensemble.v1"
    minimum_engine_coverage: float = 0.50
    exploration_floor: float = 0.0025
    validation_floor: float = 0.0075
    qualified_floor: float = 0.015
    established_floor: float = 0.03
    maximum_exploration_weight: float = 0.01
    maximum_validation_weight: float = 0.015
    maximum_qualified_weight: float = 0.03
    maximum_established_company_weight: float = 0.05
    maximum_historical_calibration: float = 1.10

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        for name in (
            "minimum_engine_coverage",
            "exploration_floor",
            "validation_floor",
            "qualified_floor",
            "established_floor",
            "maximum_exploration_weight",
            "maximum_validation_weight",
            "maximum_qualified_weight",
            "maximum_established_company_weight",
            "maximum_historical_calibration",
        ):
            if float(getattr(self, name)) < 0.0:
                raise ValueError(f"{name} cannot be negative")
        if self.maximum_historical_calibration < 1.0:
            raise ValueError("maximum_historical_calibration cannot be below 1.0")


@dataclass(frozen=True, slots=True)
class GrowthEnsembleAssessment:
    candidate_identifier: str
    policy_version: str
    stage: GrowthStage
    engine_coverage: float
    supportive_engine_ratio: float
    weighted_alignment: float
    confidence: float
    dispersion: float
    target_multiplier: float
    minimum_target_weight: float
    maximum_target_weight: float
    positive_engines: tuple[str, ...]
    negative_engines: tuple[str, ...]
    explanation: str


class AdaptiveRobustGrowthEnsemble:
    _RETURN_ROLES = (
        SpecialistRole.MACRO_ECONOMIC,
        SpecialistRole.MARKET,
        SpecialistRole.CROSS_ASSET_FORECAST,
        SpecialistRole.FUNDAMENTAL_VALUATION,
    )

    def __init__(self, policy: GrowthEnsemblePolicy | None = None) -> None:
        self.policy = policy or GrowthEnsemblePolicy()

    @staticmethod
    def _position_signal(position: SpecialistPosition) -> float:
        if position is SpecialistPosition.SUPPORTIVE:
            return 1.0
        if position is SpecialistPosition.OPPOSED:
            return -1.0
        return 0.0

    @staticmethod
    def _geometric_mean(values: Iterable[float]) -> float:
        cleaned = tuple(max(0.01, min(1.0, float(value))) for value in values)
        if not cleaned:
            return 0.0
        return exp(sum(log(value) for value in cleaned) / len(cleaned))

    def assess(
        self,
        candidate: CandidateDecisionRecord,
        specialists: IndependentSpecialistPacket,
        robustness: RobustCandidateAssessment,
        profile: DecisionPolicyProfile,
        *,
        analysis_lane: str = "acquisition",
    ) -> GrowthEnsembleAssessment:
        analyses = tuple(specialists.for_role(role) for role in self._RETURN_ROLES)
        active = tuple(
            item for item in analyses
            if item.position is not SpecialistPosition.ABSTAIN
        )
        coverage = len(active) / len(analyses)
        independence = specialists.evidence_independence
        role_weight_total = sum(
            independence.weight_for(item.role) for item in active
        )
        weight_total = sum(
            max(0.05, item.confidence) * independence.weight_for(item.role)
            for item in active
        )
        alignment = (
            0.0
            if weight_total <= 0.0
            else sum(
                self._position_signal(item.position)
                * max(0.05, item.confidence)
                * independence.weight_for(item.role)
                for item in active
            ) / weight_total
        )
        supportive = (
            0.0
            if role_weight_total <= 0.0
            else sum(
                independence.weight_for(item.role)
                for item in active
                if item.position is SpecialistPosition.SUPPORTIVE
            ) / role_weight_total
        )
        confidence = independence.independent_confidence
        dispersion = (
            0.0
            if len(active) < 2
            else pstdev(item.expected_return_impact for item in active)
        )
        positive = tuple(
            item.role.value for item in active
            if item.position is SpecialistPosition.SUPPORTIVE
        )
        negative = tuple(
            item.role.value for item in active
            if item.position is SpecialistPosition.OPPOSED
        )

        lane = str(analysis_lane).lower()
        current = candidate.current_portfolio_weight
        positive_edge = max(0.0, robustness.robust_edge)
        edge_reference = max(0.0025, profile.minimum_opportunity_edge)
        edge_strength = min(
            1.0, positive_edge / max(edge_reference * 2.0, 0.005)
        )
        reliability = min(1.0, robustness.evidence_reliability / 0.85)
        agreement = max(0.0, min(1.0, (alignment + 1.0) / 2.0))
        uncertainty = max(0.25, 1.0 - min(0.75, dispersion))
        raw_multiplier = (
            0.20 * reliability
            + 0.20 * agreement
            + 0.15 * supportive
            + 0.15 * confidence
            + 0.20 * edge_strength
            + 0.10 * independence.independence_ratio
        ) * uncertainty
        raw_multiplier = max(0.15, min(1.0, raw_multiplier))

        effective = independence.effective_role_count
        if current >= 0.03 and alignment >= 0.20 and effective >= 2.0:
            stage = GrowthStage.ESTABLISHED
        elif (
            lane == "participation"
            and coverage >= self.policy.minimum_engine_coverage
            and effective >= 3.0
        ):
            stage = GrowthStage.STRATEGIC
        elif (
            alignment >= 0.45
            and supportive >= 0.75
            and robustness.robust_edge > 0.0
            and effective >= 3.0
        ):
            stage = GrowthStage.QUALIFIED
        elif alignment >= 0.10 and supportive >= 0.50 and effective >= 2.0:
            stage = GrowthStage.VALIDATE
        elif (
            lane in {"exploration", "participation"}
            and alignment > -0.35
            and effective >= 1.0
        ):
            stage = GrowthStage.EXPLORE
        else:
            stage = GrowthStage.OBSERVE

        if stage is GrowthStage.OBSERVE:
            minimum, maximum = 0.0, 0.0
        elif stage is GrowthStage.EXPLORE:
            minimum = self.policy.exploration_floor
            maximum = min(
                profile.maximum_position_weight,
                self.policy.maximum_exploration_weight,
            )
        elif stage is GrowthStage.VALIDATE:
            minimum = self.policy.validation_floor
            maximum = min(
                profile.maximum_position_weight,
                self.policy.maximum_validation_weight,
            )
        elif stage is GrowthStage.QUALIFIED:
            minimum = self.policy.qualified_floor
            maximum = min(
                profile.maximum_position_weight,
                self.policy.maximum_qualified_weight,
            )
        elif stage is GrowthStage.ESTABLISHED:
            minimum = min(current, self.policy.established_floor)
            maximum = min(
                profile.maximum_position_weight,
                self.policy.maximum_established_company_weight,
            )
        else:
            minimum = min(0.01, profile.maximum_position_weight)
            maximum = profile.maximum_position_weight

        explanation = (
            f"{stage.value.title()} stage from {len(active)}/{len(analyses)} active "
            f"return engines and {independence.effective_role_count:.2f} effective independent engines; "
            f"supportive={supportive:.0%}, alignment={alignment:+.2f}, "
            f"confidence={confidence:.0%}, independence={independence.independence_ratio:.0%}, "
            f"robust edge={robustness.robust_edge:+.2%}. "
            "Uncertainty changes position size before it eliminates participation."
        )
        return GrowthEnsembleAssessment(
            candidate_identifier=candidate.identifier,
            policy_version=self.policy.version,
            stage=stage,
            engine_coverage=round(coverage, 8),
            supportive_engine_ratio=round(supportive, 8),
            weighted_alignment=round(alignment, 8),
            confidence=round(confidence, 8),
            dispersion=round(dispersion, 8),
            target_multiplier=round(raw_multiplier, 8),
            minimum_target_weight=round(minimum, 8),
            maximum_target_weight=round(maximum, 8),
            positive_engines=positive,
            negative_engines=negative,
            explanation=explanation,
        )


__all__ = [
    "AdaptiveRobustGrowthEnsemble",
    "GrowthEnsembleAssessment",
    "GrowthEnsemblePolicy",
    "GrowthStage",
]
