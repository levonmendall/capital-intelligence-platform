"""Dependency-aware, scenario-specific specialist reconciliation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from math import exp, log1p

from cio.committee import IndependentSpecialistPacket, SpecialistAnalysis
from cio.models import (
    CandidateDecisionRecord,
    EvidenceDependency,
    PayoffDistributionPoint,
    ReturnReconciliation,
    ScenarioAdjustment,
    SpecialistPosition,
    SpecialistReturnAdjustment,
    SpecialistRole,
)


@dataclass(frozen=True, slots=True)
class SpecialistReconciliationPolicy:
    """Conservative rules for incorporating independent specialist evidence."""

    version: str = "specialist-return-reconciliation.v4"
    specialist_adjustment_share: float = 0.35
    forecast_adjustment_share: float = 0.20
    maximum_total_adjustment: float = 0.15
    minimum_overlap_discount: float = 0.25
    maximum_role_adjustment: float = 0.06
    maximum_forecast_role_adjustment: float = 0.04
    maximum_probability_delta: float = 0.20

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
            "maximum_probability_delta",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be numeric")
            normalized = float(value)
            if not 0.0 <= normalized <= 1.0:
                raise ValueError(f"{field_name} must be between 0.0 and 1.0")
            object.__setattr__(self, field_name, normalized)


class SpecialistReturnReconciler:
    """Produce one coherent post-specialist outcome distribution.

    Specialists may either provide a parallel aggregate return impact or explicit
    per-scenario return/probability/path changes.  Scenario evidence is never
    flattened into an equal shift across bull, base, and bear outcomes.
    """

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
        dependency_map = self._dependency_map(candidate, analyses)
        origin_sets = {
            item.role: self._expanded_origins(item, dependency_map)
            for item in analyses
        }
        baseline_origins = self._expanded_candidate_origins(candidate, dependency_map)
        origin_frequency: dict[str, int] = {}
        for origins in origin_sets.values():
            for origin in origins:
                origin_frequency[origin] = origin_frequency.get(origin, 0) + 1

        labels = tuple(item.label for item in candidate.scenario_distribution)
        baseline_probabilities = {
            item.label: item.probability for item in candidate.scenario_distribution
        }
        provisional: list[
            tuple[
                SpecialistAnalysis,
                tuple[str, ...],
                float,
                float,
                tuple[ScenarioAdjustment, ...],
            ]
        ] = []
        for analysis in analyses:
            origins = origin_sets[analysis.role]
            specialist_independence = (
                sum(1.0 / origin_frequency[item] for item in origins) / len(origins)
                if origins
                else self.policy.minimum_overlap_discount
            )
            baseline_overlap = (
                len(set(origins).intersection(baseline_origins)) / len(origins)
                if origins
                else 1.0
            )
            baseline_novelty = 1.0 - baseline_overlap * (
                1.0 - self.policy.minimum_overlap_discount
            )
            overlap_discount = max(
                self.policy.minimum_overlap_discount,
                specialist_independence * baseline_novelty,
            )
            share = (
                self.policy.forecast_adjustment_share
                if analysis.role is SpecialistRole.CROSS_ASSET_FORECAST
                else self.policy.specialist_adjustment_share
            )
            role_cap = (
                self.policy.maximum_forecast_role_adjustment
                if analysis.role is SpecialistRole.CROSS_ASSET_FORECAST
                else self.policy.maximum_role_adjustment
            )
            factor = analysis.confidence * share * overlap_discount

            if analysis.scenario_adjustments:
                unknown = sorted(
                    {item.label for item in analysis.scenario_adjustments} - set(labels)
                )
                if unknown:
                    raise ValueError(
                        f"specialist scenario adjustments reference unknown labels: {unknown}"
                    )
                scaled = tuple(
                    ScenarioAdjustment(
                        label=item.label,
                        return_delta=item.return_delta * factor,
                        probability_delta=max(
                            -self.policy.maximum_probability_delta,
                            min(
                                self.policy.maximum_probability_delta,
                                item.probability_delta * factor,
                            ),
                        ),
                        path_drawdown_delta=item.path_drawdown_delta * factor,
                    )
                    for item in analysis.scenario_adjustments
                )
                applied = self._expected_scenario_impact(
                    scaled,
                    baseline_probabilities=baseline_probabilities,
                )
                if abs(applied) > role_cap and abs(applied) > 1e-12:
                    role_scale = role_cap / abs(applied)
                    scaled = self._scale_scenarios(scaled, role_scale)
                    applied *= role_scale
            else:
                applied = analysis.expected_return_impact * factor
                applied = max(-role_cap, min(role_cap, applied))
                scaled = ()
            provisional.append(
                (analysis, origins, overlap_discount, applied, scaled)
            )

        total_expected_adjustment = sum(item[3] for item in provisional)
        total_scale = 1.0
        if (
            abs(total_expected_adjustment) > self.policy.maximum_total_adjustment
            and abs(total_expected_adjustment) > 1e-12
        ):
            total_scale = (
                self.policy.maximum_total_adjustment
                / abs(total_expected_adjustment)
            )

        adjustments: list[SpecialistReturnAdjustment] = []
        parallel_adjustment = 0.0
        scenario_return_delta = {label: 0.0 for label in labels}
        scenario_probability_delta = {label: 0.0 for label in labels}
        scenario_path_drawdown = {label: 0.0 for label in labels}
        for analysis, origins, overlap_discount, applied, scenarios in provisional:
            final_scenarios = self._scale_scenarios(scenarios, total_scale)
            final_applied = applied * total_scale
            if final_scenarios:
                for item in final_scenarios:
                    scenario_return_delta[item.label] += item.return_delta
                    scenario_probability_delta[item.label] += item.probability_delta
                    scenario_path_drawdown[item.label] += item.path_drawdown_delta
            else:
                parallel_adjustment += final_applied
            adjustments.append(
                SpecialistReturnAdjustment(
                    role=analysis.role,
                    raw_impact=analysis.expected_return_impact,
                    confidence=analysis.confidence,
                    overlap_discount=overlap_discount,
                    applied_impact=final_applied,
                    evidence_origin_identifiers=(
                        origins
                        or (f"role:{analysis.role.value}:no-declared-origin",)
                    ),
                    scenario_adjustments=final_scenarios,
                )
            )

        raw_probabilities = {
            point.label: max(
                0.0,
                point.probability + scenario_probability_delta[point.label],
            )
            for point in candidate.scenario_distribution
        }
        probability_total = sum(raw_probabilities.values())
        if probability_total <= 0.0:
            raise ValueError("specialist probability adjustments removed all probability")
        probability_normalization = abs(probability_total - 1.0) > 0.000001
        probabilities = {
            label: value / probability_total
            for label, value in raw_probabilities.items()
        }

        bounds_correction = False
        outcomes: list[PayoffDistributionPoint] = []
        path_drawdowns: list[tuple[str, float]] = []
        for point in candidate.scenario_distribution:
            adjusted_return = (
                point.total_return
                + parallel_adjustment
                + scenario_return_delta[point.label]
            )
            if adjusted_return < -1.0:
                adjusted_return = -1.0
                bounds_correction = True
            outcomes.append(
                PayoffDistributionPoint(
                    label=point.label,
                    total_return=adjusted_return,
                    probability=probabilities[point.label],
                )
            )
            drawdown = max(-1.0, min(0.0, scenario_path_drawdown[point.label]))
            if drawdown < 0.0:
                path_drawdowns.append((point.label, drawdown))

        outcome_tuple = tuple(outcomes)
        implementation_cost = candidate.implementation_cost_return
        expected_return = sum(
            item.total_return * item.probability for item in outcome_tuple
        ) - implementation_cost
        expected_downside = (
            min(item.total_return for item in outcome_tuple) - implementation_cost
        )
        horizon_alternative = self._horizon_return(
            alternative,
            horizon_days=candidate.decision_horizon_days,
        )
        success_probability = max(
            0.0,
            min(
                1.0,
                sum(
                    item.probability
                    for item in outcome_tuple
                    if item.total_return - implementation_cost > horizon_alternative
                ),
            ),
        )
        evidence_origins = {
            *baseline_origins,
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
            adjustments=tuple(adjustments),
            bounds_correction_applied=bounds_correction,
            probability_normalization_applied=probability_normalization,
            path_drawdown_by_scenario=tuple(path_drawdowns),
        )

    @staticmethod
    def _scale_scenarios(
        scenarios: tuple[ScenarioAdjustment, ...],
        factor: float,
    ) -> tuple[ScenarioAdjustment, ...]:
        return tuple(
            ScenarioAdjustment(
                label=item.label,
                return_delta=item.return_delta * factor,
                probability_delta=item.probability_delta * factor,
                path_drawdown_delta=item.path_drawdown_delta * factor,
            )
            for item in scenarios
        )

    @staticmethod
    def _expected_scenario_impact(
        scenarios: tuple[ScenarioAdjustment, ...],
        *,
        baseline_probabilities: dict[str, float],
    ) -> float:
        return sum(
            baseline_probabilities[item.label] * item.return_delta
            for item in scenarios
        )

    @classmethod
    def _dependency_map(
        cls,
        candidate: CandidateDecisionRecord,
        analyses: tuple[SpecialistAnalysis, ...],
    ) -> dict[str, tuple[str, ...]]:
        values: list[EvidenceDependency] = list(candidate.evidence_dependencies)
        for analysis in analyses:
            values.extend(analysis.evidence_dependencies)
        mapping: dict[str, tuple[str, ...]] = {}
        for item in values:
            current = mapping.get(item.identifier, ())
            mapping[item.identifier] = tuple(
                dict.fromkeys((*current, *item.parent_identifiers))
            )
        return mapping

    @classmethod
    def _closure(
        cls,
        identifier: str,
        dependency_map: dict[str, tuple[str, ...]],
    ) -> frozenset[str]:
        pending = [cls._normalize_origin(identifier)]
        seen: set[str] = set()
        while pending:
            item = pending.pop()
            if item in seen:
                continue
            seen.add(item)
            pending.extend(dependency_map.get(item, ()))
        return frozenset(seen)

    @classmethod
    def _expanded_origins(
        cls,
        analysis: SpecialistAnalysis,
        dependency_map: dict[str, tuple[str, ...]],
    ) -> tuple[str, ...]:
        origins = cls._origins(analysis)
        expanded = {
            ancestor
            for origin in origins
            for ancestor in cls._closure(origin, dependency_map)
        }
        return tuple(sorted(expanded))

    @classmethod
    def _expanded_candidate_origins(
        cls,
        candidate: CandidateDecisionRecord,
        dependency_map: dict[str, tuple[str, ...]],
    ) -> frozenset[str]:
        origins = cls._candidate_origins(candidate)
        return frozenset(
            ancestor
            for origin in origins
            for ancestor in cls._closure(origin, dependency_map)
        )

    @classmethod
    def _origins(cls, analysis: SpecialistAnalysis) -> tuple[str, ...]:
        declared = analysis.evidence_origin_identifiers
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
