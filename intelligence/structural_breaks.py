"""Multidimensional structural-break and out-of-distribution detection.

The detector separates data-provider degradation from market novelty and returns
reversible advisory controls. It never automatically forces cash, liquidates a
position, changes policy, or authorizes capital.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any


class NoveltyDimension(str, Enum):
    MACRO_DISTRIBUTION = "macro_distribution"
    CORRELATION = "correlation_breakdown"
    POLICY_COMBINATION = "unprecedented_policy_combination"
    VOLATILITY_LIQUIDITY = "abnormal_volatility_and_liquidity"
    VALUATION = "extreme_valuation_regime"
    PROVIDER_DISAGREEMENT = "provider_disagreement"
    MODEL_DISAGREEMENT = "model_disagreement"
    FORECAST_RESIDUAL = "forecast_residual_change"
    CALIBRATION = "deteriorating_calibration"
    ANALOG_FAILURE = "historical_analog_failure"
    TRAINING_RANGE = "outside_training_range"


class StructuralBreakState(str, Enum):
    NORMAL = "normal"
    PROVIDER_DEGRADATION = "provider_degradation"
    POSSIBLE_BREAK = "possible_structural_break"
    CONFIRMED_BREAK = "confirmed_structural_break"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, slots=True)
class NoveltyObservation:
    dimension: NoveltyDimension
    standardized_distance: float
    reliability: float
    independent_source_count: int
    provider_health: float
    evidence_identifiers: tuple[str, ...]
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, NoveltyDimension):
            raise TypeError("dimension must be NoveltyDimension")
        if (
            not isfinite(float(self.standardized_distance))
            or self.standardized_distance < 0.0
        ):
            raise ValueError(
                "standardized_distance must be finite and non-negative"
            )
        for name in ("reliability", "provider_health"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between zero and one")
        if (
            isinstance(self.independent_source_count, bool)
            or self.independent_source_count < 0
        ):
            raise ValueError("independent_source_count must be non-negative")
        if not self.evidence_identifiers:
            raise ValueError("novelty observations require evidence identifiers")
        if not self.detail.strip():
            raise ValueError("detail is required")


@dataclass(frozen=True, slots=True)
class StructuralBreakControls:
    confidence_ceiling: float | None
    scenario_range_multiplier: float
    tail_risk_weight_multiplier: float
    staged_position_ceiling_multiplier: float
    review_interval_multiplier: float
    request_additional_research: bool
    block_historical_extrapolation: bool
    force_cash: bool = False
    force_liquidation: bool = False


@dataclass(frozen=True, slots=True)
class StructuralBreakAssessment:
    identifier: str
    as_of: datetime
    state: StructuralBreakState
    market_novelty_score: float
    model_uncertainty_score: float
    provider_risk_score: float
    active_dimensions: tuple[NoveltyDimension, ...]
    evidence_identifiers: tuple[str, ...]
    controls: StructuralBreakControls
    rationale: tuple[str, ...]
    schema_version: str = "structural-break-assessment.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "state": self.state.value,
            "market_novelty_score": self.market_novelty_score,
            "model_uncertainty_score": self.model_uncertainty_score,
            "provider_risk_score": self.provider_risk_score,
            "active_dimensions": [item.value for item in self.active_dimensions],
            "evidence_identifiers": list(self.evidence_identifiers),
            "controls": {
                "confidence_ceiling": self.controls.confidence_ceiling,
                "scenario_range_multiplier": self.controls.scenario_range_multiplier,
                "tail_risk_weight_multiplier": self.controls.tail_risk_weight_multiplier,
                "staged_position_ceiling_multiplier": self.controls.staged_position_ceiling_multiplier,
                "review_interval_multiplier": self.controls.review_interval_multiplier,
                "request_additional_research": self.controls.request_additional_research,
                "block_historical_extrapolation": self.controls.block_historical_extrapolation,
                "force_cash": self.controls.force_cash,
                "force_liquidation": self.controls.force_liquidation,
            },
            "rationale": list(self.rationale),
            "advisory_only": True,
        }


class StructuralBreakDetector:
    version = "structural-break-detector.v1"

    def assess(
        self,
        observations: tuple[NoveltyObservation, ...],
        *,
        identifier: str,
        as_of: datetime,
    ) -> StructuralBreakAssessment:
        if not identifier.strip():
            raise ValueError("identifier is required")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if not observations:
            controls = StructuralBreakControls(
                None, 1.0, 1.0, 1.0, 1.0, True, True
            )
            return StructuralBreakAssessment(
                identifier,
                as_of,
                StructuralBreakState.INSUFFICIENT_EVIDENCE,
                0.0,
                1.0,
                0.0,
                (),
                (),
                controls,
                (
                    "No novelty observations were supplied; historical extrapolation is unsupported.",
                ),
            )
        provider_observations = tuple(
            item
            for item in observations
            if item.dimension is NoveltyDimension.PROVIDER_DISAGREEMENT
        )
        market_observations = tuple(
            item
            for item in observations
            if item.dimension is not NoveltyDimension.PROVIDER_DISAGREEMENT
        )
        provider_risk = (
            max(
                (1.0 - item.provider_health) * item.reliability
                for item in provider_observations
            )
            if provider_observations
            else max(1.0 - item.provider_health for item in observations)
        )
        active = tuple(
            item
            for item in market_observations
            if item.standardized_distance >= 2.5
            and item.reliability >= 0.6
            and item.independent_source_count >= 2
            and item.provider_health >= 0.6
        )
        weighted_novelty = sum(
            min(1.0, item.standardized_distance / 5.0) * item.reliability
            for item in active
        ) / max(1, len(active))
        model_dimensions = {
            NoveltyDimension.MODEL_DISAGREEMENT,
            NoveltyDimension.FORECAST_RESIDUAL,
            NoveltyDimension.CALIBRATION,
            NoveltyDimension.ANALOG_FAILURE,
            NoveltyDimension.TRAINING_RANGE,
        }
        model_items = tuple(
            item for item in active if item.dimension in model_dimensions
        )
        model_uncertainty = sum(
            min(1.0, item.standardized_distance / 5.0) * item.reliability
            for item in model_items
        ) / max(1, len(model_items))

        if provider_risk >= 0.5 and not active:
            state = StructuralBreakState.PROVIDER_DEGRADATION
        elif len(active) >= 3 and weighted_novelty >= 0.55:
            state = StructuralBreakState.CONFIRMED_BREAK
        elif len(active) >= 2:
            state = StructuralBreakState.POSSIBLE_BREAK
        else:
            state = StructuralBreakState.NORMAL

        if state is StructuralBreakState.CONFIRMED_BREAK:
            controls = StructuralBreakControls(
                0.60, 1.75, 1.50, 0.50, 0.50, True, True
            )
        elif state is StructuralBreakState.POSSIBLE_BREAK:
            controls = StructuralBreakControls(
                0.75, 1.35, 1.25, 0.75, 0.75, True, True
            )
        elif state is StructuralBreakState.PROVIDER_DEGRADATION:
            controls = StructuralBreakControls(
                None, 1.0, 1.0, 1.0, 0.75, True, True
            )
        else:
            controls = StructuralBreakControls(
                None, 1.0, 1.0, 1.0, 1.0, False, False
            )
        rationale = tuple(item.detail for item in active) or (
            "No multidimensional, independently supported market break was established.",
        )
        evidence = tuple(
            dict.fromkeys(
                evidence_identifier
                for item in observations
                for evidence_identifier in item.evidence_identifiers
            )
        )
        return StructuralBreakAssessment(
            identifier=identifier,
            as_of=as_of,
            state=state,
            market_novelty_score=round(weighted_novelty, 8),
            model_uncertainty_score=round(model_uncertainty, 8),
            provider_risk_score=round(provider_risk, 8),
            active_dimensions=tuple(item.dimension for item in active),
            evidence_identifiers=evidence,
            controls=controls,
            rationale=rationale,
        )


__all__ = [
    "NoveltyDimension",
    "NoveltyObservation",
    "StructuralBreakAssessment",
    "StructuralBreakControls",
    "StructuralBreakDetector",
    "StructuralBreakState",
]
