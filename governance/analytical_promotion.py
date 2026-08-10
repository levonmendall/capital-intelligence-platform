"""Controlled promotion of validated shadow analytics into canonical evidence.

Promotion is deliberately one-way conservative: a certified calibration artifact may
cap confidence, a certified macro overlay may add adverse evidence or reduce expected
return, and a certified risk overlay may tighten construction risk. No promoted
artifact may raise expected return, confidence, position size, turnover, or execution
authority.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from math import isfinite

from committee.specialists import (
    CrossAssetForecastSpecialistContext,
    MacroSpecialistContext,
)
from portfolio.construction_api import PortfolioConstructionPolicy


@dataclass(frozen=True, slots=True)
class AnalyticalPromotionCertification:
    identifier: str
    artifact_identifier: str
    certified_at: datetime
    valid_until: datetime
    knowledge_cutoff: datetime
    historical_replay_passed: bool
    point_in_time_passed: bool
    calibration_passed: bool
    decision_certified: bool
    evidence_identifiers: tuple[str, ...]
    schema_version: str = "analytical-promotion-certification.v1"

    def __post_init__(self) -> None:
        for name in ("identifier", "artifact_identifier", "schema_version"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} cannot be empty")
        for name in ("certified_at", "valid_until", "knowledge_cutoff"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.valid_until < self.certified_at:
            raise ValueError("promotion certification cannot expire before certification")
        if self.knowledge_cutoff > self.certified_at:
            raise ValueError("promotion certification cannot use future knowledge")
        for name in (
            "historical_replay_passed",
            "point_in_time_passed",
            "calibration_passed",
            "decision_certified",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be bool")
        if not self.evidence_identifiers:
            raise ValueError("promotion certification requires evidence lineage")

    def require_usable(self, *, as_of: datetime, artifact_identifier: str) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if artifact_identifier != self.artifact_identifier:
            raise ValueError("promotion certification belongs to another artifact")
        if not self.decision_certified:
            raise ValueError("shadow artifact is not decision-certified")
        if not (
            self.historical_replay_passed
            and self.point_in_time_passed
            and self.calibration_passed
        ):
            raise ValueError("promotion prerequisites are incomplete")
        if self.certified_at > as_of:
            raise ValueError("promotion certification is future-known")
        if self.valid_until < as_of:
            raise ValueError("promotion certification is expired")
        if self.knowledge_cutoff > as_of:
            raise ValueError("promotion knowledge cutoff is future-known")


@dataclass(frozen=True, slots=True)
class ForecastConfidenceCeiling:
    identifier: str
    as_of: datetime
    confidence_ceiling: float
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("forecast ceiling identifier cannot be empty")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("forecast ceiling as_of must be timezone-aware")
        if not isfinite(float(self.confidence_ceiling)) or not 0.0 <= float(
            self.confidence_ceiling
        ) <= 1.0:
            raise ValueError("confidence_ceiling must be between zero and one")
        if not self.evidence_identifiers:
            raise ValueError("forecast ceiling requires evidence lineage")


@dataclass(frozen=True, slots=True)
class ConservativeMacroOverlay:
    identifier: str
    as_of: datetime
    regime_label: str
    expected_return_impact: float
    confidence_ceiling: float
    headwinds: tuple[str, ...]
    systemic_risks: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.regime_label.strip():
            raise ValueError("macro overlay identity cannot be empty")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("macro overlay as_of must be timezone-aware")
        if not isfinite(float(self.expected_return_impact)) or not -1.0 <= float(
            self.expected_return_impact
        ) <= 1.0:
            raise ValueError("expected_return_impact must be between -1 and one")
        if not isfinite(float(self.confidence_ceiling)) or not 0.0 <= float(
            self.confidence_ceiling
        ) <= 1.0:
            raise ValueError("confidence_ceiling must be between zero and one")
        if not self.evidence_identifiers:
            raise ValueError("macro overlay requires evidence lineage")


@dataclass(frozen=True, slots=True)
class ConservativeRiskOverlay:
    """Decision-certified risk limits derived from validated dynamic/stress analytics."""

    identifier: str
    as_of: datetime
    maximum_expected_shortfall: float
    maximum_stressed_drawdown: float
    maximum_liquidity_adjusted_loss: float
    maximum_position_weight_ceiling: float
    maximum_turnover_ceiling: float
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("risk overlay identifier cannot be empty")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("risk overlay as_of must be timezone-aware")
        for name in (
            "maximum_expected_shortfall",
            "maximum_stressed_drawdown",
            "maximum_liquidity_adjusted_loss",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not isfinite(float(value)) or not -1.0 <= float(value) < 0.0:
                raise ValueError(f"{name} must be negative and at least -1")
        for name in ("maximum_position_weight_ceiling", "maximum_turnover_ceiling"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not isfinite(float(value)) or not 0.0 < float(value) <= 1.0:
                raise ValueError(f"{name} must be between zero and one")
        if not self.evidence_identifiers:
            raise ValueError("risk overlay requires evidence lineage")


class ConservativeAnalyticalPromotion:
    version = "conservative-analytical-promotion.v1"

    @staticmethod
    def apply_forecast_confidence_ceiling(
        context: CrossAssetForecastSpecialistContext,
        ceiling: ForecastConfidenceCeiling,
        certification: AnalyticalPromotionCertification,
    ) -> CrossAssetForecastSpecialistContext:
        certification.require_usable(
            as_of=context.as_of,
            artifact_identifier=ceiling.identifier,
        )
        if ceiling.as_of > context.as_of:
            raise ValueError("forecast ceiling is future-known")
        resolved = min(context.aggregate_confidence, float(ceiling.confidence_ceiling))
        return replace(
            context,
            aggregate_confidence=resolved,
            limitations=tuple(
                dict.fromkeys(
                    (
                        *context.limitations,
                        f"Decision-certified calibration caps confidence at {resolved:.0%}.",
                    )
                )
            ),
            evidence_identifiers=tuple(
                dict.fromkeys(
                    (
                        *context.evidence_identifiers,
                        *ceiling.evidence_identifiers,
                        *certification.evidence_identifiers,
                    )
                )
            ),
            model_versions=tuple(
                dict.fromkeys((*context.model_versions, ConservativeAnalyticalPromotion.version))
            ),
        )

    @staticmethod
    def apply_macro_overlay(
        context: MacroSpecialistContext,
        overlay: ConservativeMacroOverlay,
        certification: AnalyticalPromotionCertification,
    ) -> MacroSpecialistContext:
        certification.require_usable(
            as_of=context.as_of,
            artifact_identifier=overlay.identifier,
        )
        if overlay.as_of > context.as_of:
            raise ValueError("macro overlay is future-known")
        # Conservative phase: promoted macro evidence can only make the live view
        # less optimistic, never create incremental alpha.
        impact = min(context.expected_return_impact, float(overlay.expected_return_impact))
        confidence = min(context.confidence, float(overlay.confidence_ceiling))
        return replace(
            context,
            regime=f"{context.regime}|certified:{overlay.regime_label}",
            expected_return_impact=impact,
            confidence=confidence,
            headwinds=tuple(dict.fromkeys((*context.headwinds, *overlay.headwinds))),
            systemic_risks=tuple(
                dict.fromkeys((*context.systemic_risks, *overlay.systemic_risks))
            ),
            evidence_identifiers=tuple(
                dict.fromkeys(
                    (
                        *context.evidence_identifiers,
                        *overlay.evidence_identifiers,
                        *certification.evidence_identifiers,
                    )
                )
            ),
        )

    @staticmethod
    def apply_construction_risk_overlay(
        policy: PortfolioConstructionPolicy,
        overlay: ConservativeRiskOverlay,
        certification: AnalyticalPromotionCertification,
    ) -> PortfolioConstructionPolicy:
        """Tighten canonical construction policy; never relax an existing limit."""
        if not isinstance(policy, PortfolioConstructionPolicy):
            raise TypeError("policy must be PortfolioConstructionPolicy")
        certification.require_usable(
            as_of=overlay.as_of,
            artifact_identifier=overlay.identifier,
        )
        return replace(
            policy,
            version=f"{policy.version}|{ConservativeAnalyticalPromotion.version}",
            maximum_expected_shortfall=max(
                policy.maximum_expected_shortfall,
                float(overlay.maximum_expected_shortfall),
            ),
            maximum_stressed_drawdown=max(
                policy.maximum_stressed_drawdown,
                float(overlay.maximum_stressed_drawdown),
            ),
            maximum_liquidity_adjusted_loss=max(
                policy.maximum_liquidity_adjusted_loss,
                float(overlay.maximum_liquidity_adjusted_loss),
            ),
            maximum_position_weight=min(
                policy.maximum_position_weight,
                float(overlay.maximum_position_weight_ceiling),
            ),
            maximum_turnover=min(
                policy.maximum_turnover,
                float(overlay.maximum_turnover_ceiling),
            ),
        )


__all__ = [
    "AnalyticalPromotionCertification",
    "ConservativeAnalyticalPromotion",
    "ConservativeMacroOverlay",
    "ConservativeRiskOverlay",
    "ForecastConfidenceCeiling",
]
