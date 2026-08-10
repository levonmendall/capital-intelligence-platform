"""Hierarchical global/regional macro evidence model.

This is an evidence-translation engine for the existing Macro and Forecast specialists.
It intentionally separates macro-state measurement from portfolio authority and can
run in shadow mode until each observation family has certified point-in-time history.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from cio.models import CandidateAssetClass
from intelligence.forward import ForwardSignal


class MacroDimension(str, Enum):
    GROWTH = "growth"
    INFLATION = "inflation"
    LABOR = "labor"
    POLICY = "policy"
    RATES = "rates"
    CREDIT = "credit"
    LIQUIDITY = "liquidity"
    FISCAL = "fiscal"
    FX = "fx"
    COMMODITY = "commodity"


@dataclass(frozen=True, slots=True)
class MacroObservation:
    identifier: str
    as_of: datetime
    geography: str
    dimension: MacroDimension
    direction: float
    confidence: float
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.geography.strip():
            raise ValueError("macro observation identity/geography cannot be empty")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("macro observation as_of must be timezone-aware")
        if not isinstance(self.dimension, MacroDimension):
            raise TypeError("dimension must be MacroDimension")
        for name, low, high in (("direction", -1.0, 1.0), ("confidence", 0.0, 1.0)):
            value = float(getattr(self, name))
            if not isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}")
        if not self.evidence_identifiers:
            raise ValueError("macro observation requires evidence identifiers")


@dataclass(frozen=True, slots=True)
class GlobalMacroState:
    as_of: datetime
    geography: str
    dimension_scores: tuple[tuple[MacroDimension, float], ...]
    confidence: float
    evidence_identifiers: tuple[str, ...]
    schema_version: str = "global-macro-state.v1"

    def score(self, dimension: MacroDimension) -> float:
        return dict(self.dimension_scores).get(dimension, 0.0)


_SENSITIVITY: dict[CandidateAssetClass, dict[MacroDimension, float]] = {
    CandidateAssetClass.US_EQUITY: {
        MacroDimension.GROWTH: 0.30,
        MacroDimension.CREDIT: 0.20,
        MacroDimension.LIQUIDITY: 0.20,
        MacroDimension.RATES: -0.15,
        MacroDimension.INFLATION: -0.15,
    },
    CandidateAssetClass.INTERNATIONAL_EQUITY: {
        MacroDimension.GROWTH: 0.28,
        MacroDimension.CREDIT: 0.18,
        MacroDimension.LIQUIDITY: 0.18,
        MacroDimension.FX: 0.18,
        MacroDimension.RATES: -0.10,
        MacroDimension.INFLATION: -0.08,
    },
    CandidateAssetClass.FIXED_INCOME: {
        MacroDimension.RATES: -0.35,
        MacroDimension.INFLATION: -0.25,
        MacroDimension.CREDIT: 0.20,
        MacroDimension.LIQUIDITY: 0.20,
    },
    CandidateAssetClass.COMMODITY: {
        MacroDimension.COMMODITY: 0.35,
        MacroDimension.INFLATION: 0.20,
        MacroDimension.GROWTH: 0.20,
        MacroDimension.FX: -0.15,
        MacroDimension.LIQUIDITY: 0.10,
    },
    CandidateAssetClass.FX: {
        MacroDimension.FX: 0.40,
        MacroDimension.POLICY: 0.25,
        MacroDimension.RATES: 0.20,
        MacroDimension.GROWTH: 0.15,
    },
    CandidateAssetClass.CRYPTO: {
        MacroDimension.LIQUIDITY: 0.35,
        MacroDimension.RATES: -0.25,
        MacroDimension.FX: -0.15,
        MacroDimension.GROWTH: 0.15,
        MacroDimension.CREDIT: 0.10,
    },
    CandidateAssetClass.REAL_ESTATE: {
        MacroDimension.RATES: -0.35,
        MacroDimension.CREDIT: 0.25,
        MacroDimension.GROWTH: 0.20,
        MacroDimension.INFLATION: 0.10,
        MacroDimension.LIQUIDITY: 0.10,
    },
}


class GlobalMacroStateEngine:
    version = "global-macro-state.v1"

    def aggregate(
        self,
        observations: tuple[MacroObservation, ...],
        *,
        as_of: datetime,
        geography: str = "GLOBAL",
    ) -> GlobalMacroState:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        selected = tuple(
            item
            for item in observations
            if item.as_of <= as_of
            and (
                geography.upper() == "GLOBAL"
                or item.geography.upper() in {"GLOBAL", geography.upper()}
            )
        )
        grouped: dict[MacroDimension, list[MacroObservation]] = {}
        for item in selected:
            grouped.setdefault(item.dimension, []).append(item)
        scores: list[tuple[MacroDimension, float]] = []
        for dimension in MacroDimension:
            values = grouped.get(dimension, [])
            if not values:
                continue
            total = sum(max(0.05, item.confidence) for item in values)
            score = sum(
                item.direction * max(0.05, item.confidence) for item in values
            ) / total
            scores.append((dimension, round(max(-1.0, min(1.0, score)), 8)))
        confidence = (
            0.0
            if not selected
            else round(
                min(1.0, sum(item.confidence for item in selected) / len(selected)),
                8,
            )
        )
        evidence = tuple(
            dict.fromkeys(
                identifier
                for item in selected
                for identifier in item.evidence_identifiers
            )
        )
        return GlobalMacroState(
            as_of=as_of,
            geography=geography,
            dimension_scores=tuple(scores),
            confidence=confidence,
            evidence_identifiers=evidence,
        )

    def candidate_signal(
        self,
        *,
        candidate_identifier: str,
        asset_class: CandidateAssetClass,
        state: GlobalMacroState,
        shadow: bool = True,
    ) -> ForwardSignal | None:
        if not state.evidence_identifiers:
            return None
        sensitivity = _SENSITIVITY.get(asset_class, {})
        raw = sum(
            state.score(dimension) * weight
            for dimension, weight in sensitivity.items()
        )
        impact = 0.0 if shadow else max(-0.05, min(0.05, raw * 0.05))
        evidence = tuple(
            f"{dimension.value}={score:+.2f}"
            for dimension, score in state.dimension_scores
        ) or ("No material macro dimension score was available",)
        return ForwardSignal(
            identifier=f"signal:global-macro:{candidate_identifier}:{state.as_of.isoformat()}",
            as_of=state.as_of,
            name="hierarchical global macro state",
            channels=("macro", "forecast"),
            expected_return_impact=impact,
            confidence=state.confidence,
            evidence=evidence,
            contradictory_evidence=(
                "Shadow mode prevents macro overlay from changing expected return"
                if shadow
                else "Macro transmission can change across regimes",
            ),
            assumptions=(
                "Regional observations remain representative through the decision horizon",
            ),
            risks=(
                "Macro relationships can reverse after policy, growth, inflation, or liquidity shocks",
            ),
            change_conditions=(
                "Refresh after a material change in growth, inflation, policy, rates, credit, liquidity, fiscal, FX, or commodity conditions",
            ),
            evidence_identifiers=state.evidence_identifiers,
        )


__all__ = [
    "GlobalMacroState",
    "GlobalMacroStateEngine",
    "MacroDimension",
    "MacroObservation",
]
