"""Dependency-aware specialist reconciliation of candidate return distributions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from math import exp, log1p

from cio.committee import IndependentSpecialistPacket, SpecialistAnalysis
from cio.models import (
    CandidateDecisionRecord,
    PayoffDistributionPoint,
    ReturnReconciliation,
    SpecialistPosition,
    SpecialistReturnAdjustment,
    SpecialistRole,
)


@dataclass(frozen=True, slots=True)
class SpecialistReconciliationPolicy:
    """Conservative rules for incorporating independent specialist evidence."""

    version: str = "specialist-return-reconciliation.v3"
    specialist_adjustment_share: float = 0.35
    forecast_adjustment_share: float = 0.20
    maximum_total_adjustment: float = 0.15
    minimum_overlap_discount: float = 0.25
    maximum_role_adjustment: float = 0.06
    maximum_forecast_role_adjustment: float = 0.04

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version cannot be empty")
        for field_name in (
            "specialist_adjustment_share",
            "forecast_adjustment_share",
            "maximum_total_adjustment",
            "minimum_overlap_discount",
            "maximum_role_adjustment",
            "maximum_forecast_role_adjustment",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be numeric")
            normalized = float(value)
            if not 0.0 <= normalized <= 1.0:
                raise ValueError(f"{field_name} must be between 0.0 and 1.0")
            object.__setattr__(self, field_name, normalized)


class SpecialistReturnReconciler:
    """Produce one mathematically coherent post-specialist outcome distribution."""

    _RETURN_ROLES = frozenset(
        {
            SpecialistRole.MACRO_ECONOMIC,
            SpecialistRole.MARKET,
            SpecialistRole.CROSS_ASSET_FORECAST,
            SpecialistRole.FUNDAMENTAL_VALUATION,
        }
    )

    def __init__(
        self,
        policy: SpecialistReconciliationPolicy | None = None,
    ) -> None:
        self.policy = policy or SpecialistReconciliationPolicy()

    def reconcile(
        self,
        candidate: CandidateDecisionRecord,
        specialists: IndependentSpecialistPacket,
        *,
        alternative_return: float,
    ) -> ReturnReconciliation:
        if not isinstance(candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be a CandidateDecisionRecord")
        if not isinstance(specialists, IndependentSpecialistPacket):
            raise TypeError("specialists must be an IndependentSpecialistPacket")
        specialists.validate_against(candidate)
        if isinstance(alternative_return, bool) or not isinstance(
            alternative_return, (int, float)
        ):
            raise TypeError("alternative_return must be numeric")
        alternative = float(alternative_return)

        analyses = tuple(
            item
            for item in specialists.analyses
            if item.role in self._RETURN_ROLES
            and item.position is not SpecialistPosition.ABSTAIN
        )
        origin_sets = {
            item.role: self._origins(item)
            for item in analyses
        }
        baseline_origins = self._candidate_origins(candidate)
        origin_frequency: dict[str, int] = {}
        for origins in origin_sets.values():
            for origin in origins:
                origin_frequency[origin] = origin_frequency.get(origin, 0) + 1

        provisional: list[tuple[SpecialistAnalysis, tuple[str, ...], float, float]] = []
        for analysis in analyses:
            origins = origin_sets[analysis.role]
            specialist_independence = (
                sum(1.0 / origin_frequency[item] for item in origins) / len(origins)
            )
            baseline_overlap = (
                len(set(origins).intersection(baseline_origins)) / len(origins)
            )
            baseline_novelty = 1.0 - baseline_overlap * (
                1.0 - self.policy.minimum_overlap_discount
            )
            overlap_discount = max(
                self.policy.minimum_overlap_discount,
                specialist_independence * baseline_novelty,
            )
            adjustment_share = (
                self.policy.forecast_adjustment_share
                if analysis.role is SpecialistRole.CROSS_ASSET_FORECAST
                else self.policy.specialist_adjustment_share
            )
            role_cap = (
                self.policy.maximum_forecast_role_adjustment
                if analysis.role is SpecialistRole.CROSS_ASSET_FORECAST
                else self.policy.maximum_role_adjustment
            )
            applied = (
                analysis.expected_return_impact
                * analysis.confidence
                * adjustment_share
                * overlap_discount
            )
            applied = max(-role_cap, min(role_cap, applied))
            provisional.append((analysis, origins, overlap_discount, applied))

        total = sum(item[3] for item in provisional)
        scale = 1.0
        if abs(total) > self.policy.maximum_total_adjustment and abs(total) > 1e-12:
            scale = self.policy.maximum_total_adjustment / abs(total)

        adjustments = tuple(
            SpecialistReturnAdjustment(
                role=analysis.role,
                raw_impact=analysis.expected_return_impact,
                confidence=analysis.confidence,
                overlap_discount=overlap_discount,
                applied_impact=applied * scale,
                evidence_origin_identifiers=origins,
            )
            for analysis, origins, overlap_discount, applied in provisional
        )
        total_adjustment = sum(item.applied_impact for item in adjustments)

        bounds_correction = False
        outcomes: list[PayoffDistributionPoint] = []
        for point in candidate.scenario_distribution:
            adjusted = point.total_return + total_adjustment
            if adjusted < -1.0:
                adjusted = -1.0
                bounds_correction = True
            outcomes.append(
                PayoffDistributionPoint(
                    label=point.label,
                    total_return=adjusted,
                    probability=point.probability,
                )
            )
        outcome_tuple = tuple(outcomes)
        implementation_cost = candidate.implementation_cost_return
        expected_return = sum(
            item.total_return * item.probability for item in outcome_tuple
        ) - implementation_cost
        expected_downside = min(item.total_return for item in outcome_tuple) - implementation_cost
        horizon_alternative = self._horizon_return(
            alternative,
            horizon_days=candidate.decision_horizon_days,
        )
        success_probability = sum(
            item.probability
            for item in outcome_tuple
            if item.total_return - implementation_cost > horizon_alternative
        )
        evidence_origins = {
            *(self._normalize_origin(item) for item in candidate.evidence_identifiers),
            *(origin for origins in origin_sets.values() for origin in origins),
        }
        return ReturnReconciliation(
            policy_version=self.policy.version,
            original_expected_return=candidate.net_expected_return,
            original_probability_of_success=candidate.probability_of_success,
            alternative_return=alternative,
            horizon_alternative_return=horizon_alternative,
            implementation_cost_return=implementation_cost,
            outcomes=outcome_tuple,
            expected_return=expected_return,
            expected_downside=expected_downside,
            probability_of_success=success_probability,
            evidence_origin_count=max(1, len(evidence_origins)),
            adjustments=adjustments,
            bounds_correction_applied=bounds_correction,
        )

    @classmethod
    def _origins(cls, analysis: SpecialistAnalysis) -> tuple[str, ...]:
        declared = getattr(analysis, "evidence_origin_identifiers", ())
        if declared:
            return tuple(
                dict.fromkeys(cls._normalize_origin(item) for item in declared)
            )
        return tuple(
            dict.fromkeys(
                cls._text_origin(item) for item in analysis.supporting_evidence
            )
        )

    @classmethod
    def _candidate_origins(
        cls,
        candidate: CandidateDecisionRecord,
    ) -> frozenset[str]:
        origins = {
            cls._normalize_origin(item) for item in candidate.evidence_identifiers
        }
        for item in (
            *candidate.supporting_evidence,
            *candidate.contradictory_evidence,
        ):
            origins.add(cls._normalize_origin(item))
            origins.add(cls._text_origin(item))
        return frozenset(origins)

    @staticmethod
    def _normalize_origin(value: str) -> str:
        return value.strip().lower()

    @staticmethod
    def _text_origin(value: str) -> str:
        return (
            "evidence-text:"
            + hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()
        )

    @staticmethod
    def _horizon_return(annual_return: float, *, horizon_days: int) -> float:
        if annual_return <= -1.0:
            return -1.0
        return exp(log1p(annual_return) * (horizon_days / 365.25)) - 1.0


__all__ = [
    "SpecialistReconciliationPolicy",
    "SpecialistReturnReconciler",
]
