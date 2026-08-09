"""Governed forward-intelligence engines for the existing six-specialist process.

The engines in this module do not discover trades, authorize capital, or replace a
specialist.  They translate point-in-time business, trend, structural-theme,
monetary-policy, and currency evidence into candidate-specific signals that the
existing committee may independently challenge and the CIO may reject.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any, Iterable, Mapping

from cio.committee import SpecialistAnalysis
from cio.models import (
    ScenarioAdjustment,
    SpecialistPosition,
    SpecialistRole,
)
from intelligence.forward_decision import ForwardDecisionContext


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _number(
    value: object,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    if maximum is not None and normalized > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}")
    return round(normalized, 8)


def _ratio(value: object, *, field_name: str) -> float:
    return _number(value, field_name=field_name, minimum=0.0, maximum=1.0)


def _bounded(value: object, *, field_name: str) -> float:
    return _number(value, field_name=field_name, minimum=-1.0, maximum=1.0)


def _texts(
    value: object,
    *,
    field_name: str,
    minimum: int = 0,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} must contain at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _clamp(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, float(value))), 8)


def _position(impact: float, *, threshold: float = 0.01) -> SpecialistPosition:
    if impact > threshold:
        return SpecialistPosition.SUPPORTIVE
    if impact < -threshold:
        return SpecialistPosition.OPPOSED
    return SpecialistPosition.NEUTRAL


class ThemeStage(str, Enum):
    EMERGING = "emerging"
    ACCELERATING = "accelerating"
    BROADENING = "broadening"
    SUPPLY_CONSTRAINED = "supply_constrained"
    CAPACITY_EXPANDING = "capacity_expanding"
    CROWDED = "crowded"
    OVERSUPPLIED = "oversupplied"
    DECELERATING = "decelerating"
    NORMALIZING = "normalizing"


class TrendStage(str, Enum):
    EARLY = "early"
    CONFIRMED = "confirmed"
    BROADENING = "broadening"
    MATURE = "mature"
    CROWDED = "crowded"
    REVERSING = "reversing"
    DETERIORATING = "deteriorating"


class PolicyRegime(str, Enum):
    ACCELERATING_QE = "accelerating_qe"
    DECELERATING_QE = "decelerating_qe"
    STABLE_BALANCE_SHEET = "stable_balance_sheet"
    EARLY_QT = "early_qt"
    ACCELERATING_QT = "accelerating_qt"
    RATE_HIKING = "rate_hiking"
    RESTRICTIVE_HOLD = "restrictive_hold"
    RATE_CUTTING = "rate_cutting"
    EMERGENCY_EASING = "emergency_easing"
    POLICY_CONFLICT = "policy_conflict"


class PolicyMotive(str, Enum):
    STABLE_DISINFLATION = "stable_disinflation"
    GROWTH_SUPPORT = "growth_support"
    FINANCIAL_CRISIS = "financial_crisis"
    INFLATION_CONTROL = "inflation_control"
    NORMALIZATION = "normalization"
    CURRENCY_DEFENSE = "currency_defense"
    FISCAL_STRESS = "fiscal_stress"
    UNCERTAIN = "uncertain"


class CurrencyRegime(str, Enum):
    STRONG_DOLLAR = "strong_dollar"
    WEAK_DOLLAR = "weak_dollar"
    DOLLAR_FUNDING_STRESS = "dollar_funding_stress"
    HIGH_FX_VOLATILITY = "high_fx_volatility"
    BALANCED = "balanced"


@dataclass(frozen=True, slots=True)
class ForwardSignal:
    """One governed candidate-specific inference supplied to selected roles."""

    identifier: str
    as_of: datetime
    name: str
    channels: tuple[str, ...]
    expected_return_impact: float
    confidence: float
    evidence: tuple[str, ...]
    contradictory_evidence: tuple[str, ...]
    assumptions: tuple[str, ...]
    risks: tuple[str, ...]
    change_conditions: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("identifier", "name"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.as_of, field_name="as_of")
        allowed = {"macro", "market", "forecast", "fundamental"}
        channels = tuple(
            _text(item, field_name="channels").lower() for item in self.channels
        )
        if not channels or not set(channels).issubset(allowed):
            raise ValueError("channels must use governed specialist channel names")
        object.__setattr__(self, "channels", tuple(dict.fromkeys(channels)))
        object.__setattr__(
            self,
            "expected_return_impact",
            _bounded(self.expected_return_impact, field_name="expected_return_impact"),
        )
        object.__setattr__(
            self,
            "confidence",
            _ratio(self.confidence, field_name="confidence"),
        )
        for field_name, minimum in (
            ("evidence", 1),
            ("contradictory_evidence", 0),
            ("assumptions", 1),
            ("risks", 1),
            ("change_conditions", 1),
            ("evidence_identifiers", 1),
        ):
            object.__setattr__(
                self,
                field_name,
                _texts(getattr(self, field_name), field_name=field_name, minimum=minimum),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "name": self.name,
            "channels": list(self.channels),
            "expected_return_impact": self.expected_return_impact,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "contradictory_evidence": list(self.contradictory_evidence),
            "assumptions": list(self.assumptions),
            "risks": list(self.risks),
            "change_conditions": list(self.change_conditions),
            "evidence_identifiers": list(self.evidence_identifiers),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ForwardSignal":
        return cls(
            identifier=str(payload["identifier"]),
            as_of=datetime.fromisoformat(str(payload["as_of"])),
            name=str(payload["name"]),
            channels=tuple(str(item) for item in payload["channels"]),
            expected_return_impact=float(payload["expected_return_impact"]),
            confidence=float(payload["confidence"]),
            evidence=tuple(str(item) for item in payload["evidence"]),
            contradictory_evidence=tuple(
                str(item) for item in payload.get("contradictory_evidence", ())
            ),
            assumptions=tuple(str(item) for item in payload["assumptions"]),
            risks=tuple(str(item) for item in payload["risks"]),
            change_conditions=tuple(
                str(item) for item in payload["change_conditions"]
            ),
            evidence_identifiers=tuple(
                str(item) for item in payload["evidence_identifiers"]
            ),
        )


@dataclass(frozen=True, slots=True)
class ForwardScenario:
    label: str
    return_delta: float
    probability_delta: float
    path_drawdown_delta: float
    rationale: str
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _text(self.label, field_name="label"))
        object.__setattr__(
            self,
            "return_delta",
            _number(self.return_delta, field_name="return_delta", minimum=-1.0, maximum=1.0),
        )
        object.__setattr__(
            self,
            "probability_delta",
            _number(
                self.probability_delta,
                field_name="probability_delta",
                minimum=-1.0,
                maximum=1.0,
            ),
        )
        drawdown = _number(
            self.path_drawdown_delta,
            field_name="path_drawdown_delta",
            minimum=-1.0,
            maximum=0.0,
        )
        object.__setattr__(self, "path_drawdown_delta", drawdown)
        object.__setattr__(
            self,
            "rationale",
            _text(self.rationale, field_name="rationale"),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(
                self.evidence_identifiers,
                field_name="evidence_identifiers",
                minimum=1,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "return_delta": self.return_delta,
            "probability_delta": self.probability_delta,
            "path_drawdown_delta": self.path_drawdown_delta,
            "rationale": self.rationale,
            "evidence_identifiers": list(self.evidence_identifiers),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ForwardScenario":
        return cls(
            label=str(payload["label"]),
            return_delta=float(payload["return_delta"]),
            probability_delta=float(payload["probability_delta"]),
            path_drawdown_delta=float(payload["path_drawdown_delta"]),
            rationale=str(payload["rationale"]),
            evidence_identifiers=tuple(
                str(item) for item in payload["evidence_identifiers"]
            ),
        )


@dataclass(frozen=True, slots=True)
class ForwardIntelligenceBundle:
    """Point-in-time forward evidence that enriches, but never replaces, specialists."""

    identifier: str
    candidate_identifier: str
    as_of: datetime
    signals: tuple[ForwardSignal, ...]
    scenarios: tuple[ForwardScenario, ...]
    diagnostics: tuple[str, ...]
    model_versions: tuple[str, ...]
    theme_stage: ThemeStage | None = None
    trend_stage: TrendStage | None = None
    policy_regime: PolicyRegime | None = None
    currency_regime: CurrencyRegime | None = None
    decision_context: ForwardDecisionContext | None = None
    schema_version: str = "forward-intelligence.v2"

    def __post_init__(self) -> None:
        for field_name in ("identifier", "candidate_identifier", "schema_version"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.signals, tuple) or not all(
            isinstance(item, ForwardSignal) for item in self.signals
        ):
            raise TypeError("signals must contain ForwardSignal values")
        if not isinstance(self.scenarios, tuple) or not all(
            isinstance(item, ForwardScenario) for item in self.scenarios
        ):
            raise TypeError("scenarios must contain ForwardScenario values")
        if any(item.as_of != self.as_of for item in self.signals):
            raise ValueError("all forward signals must share bundle as_of")
        identifiers = tuple(item.identifier for item in self.signals)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("forward signal identifiers must be unique")
        object.__setattr__(
            self,
            "diagnostics",
            _texts(self.diagnostics, field_name="diagnostics"),
        )
        object.__setattr__(
            self,
            "model_versions",
            _texts(self.model_versions, field_name="model_versions", minimum=1),
        )
        for field_name, enum_type in (
            ("theme_stage", ThemeStage),
            ("trend_stage", TrendStage),
            ("policy_regime", PolicyRegime),
            ("currency_regime", CurrencyRegime),
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, enum_type):
                raise TypeError(f"{field_name} must be {enum_type.__name__} or None")
        if self.decision_context is not None:
            if not isinstance(self.decision_context, ForwardDecisionContext):
                raise TypeError("decision_context must be ForwardDecisionContext or None")
            if self.decision_context.candidate_identifier != self.candidate_identifier:
                raise ValueError("decision context does not match candidate")
            if self.decision_context.as_of != self.as_of:
                raise ValueError("decision context must share bundle as_of")

    @property
    def evidence_identifiers(self) -> tuple[str, ...]:
        context_identifiers = (
            () if self.decision_context is None else self.decision_context.evidence_identifiers
        )
        return tuple(
            dict.fromkeys(
                tuple(
                    identifier
                    for item in self.signals
                    for identifier in item.evidence_identifiers
                )
                + context_identifiers
            )
        )

    def signals_for(self, channel: str) -> tuple[ForwardSignal, ...]:
        normalized = _text(channel, field_name="channel").lower()
        return tuple(item for item in self.signals if normalized in item.channels)

    def _scenario_adjustments(self) -> tuple[ScenarioAdjustment, ...]:
        grouped: dict[str, list[ForwardScenario]] = {}
        for item in self.scenarios:
            grouped.setdefault(item.label, []).append(item)
        return tuple(
            ScenarioAdjustment(
                label=label,
                return_delta=_clamp(
                    sum(item.return_delta for item in values), -0.25, 0.25
                ),
                probability_delta=_clamp(
                    sum(item.probability_delta for item in values), -0.20, 0.20
                ),
                path_drawdown_delta=_clamp(
                    sum(item.path_drawdown_delta for item in values), -0.25, 0.0
                ),
            )
            for label, values in sorted(grouped.items())
        )

    def enrich_analysis(self, analysis: SpecialistAnalysis) -> SpecialistAnalysis:
        if self.decision_context is not None:
            analysis = self.decision_context.enrich_analysis(analysis)
        channel = {
            SpecialistRole.MACRO_ECONOMIC: "macro",
            SpecialistRole.MARKET: "market",
            SpecialistRole.CROSS_ASSET_FORECAST: "forecast",
            SpecialistRole.FUNDAMENTAL_VALUATION: "fundamental",
        }.get(analysis.role)
        if channel is None:
            return analysis
        signals = self.signals_for(channel)
        scenario_adjustments = (
            self._scenario_adjustments()
            if analysis.role is SpecialistRole.CROSS_ASSET_FORECAST
            else ()
        )
        if not signals and not scenario_adjustments:
            return analysis
        signal_impact = _clamp(
            sum(item.expected_return_impact for item in signals), -0.25, 0.25
        )
        combined_impact = _clamp(
            analysis.expected_return_impact + signal_impact,
            -1.0,
            1.0,
        )
        active_confidence = tuple(item.confidence for item in signals)
        confidence = (
            analysis.confidence
            if not active_confidence
            else min(
                max(analysis.confidence, sum(active_confidence) / len(active_confidence)),
                min(active_confidence),
            )
            if analysis.position is not SpecialistPosition.ABSTAIN
            else min(active_confidence)
        )
        position = analysis.position
        if position is SpecialistPosition.ABSTAIN and (
            abs(signal_impact) >= 0.01 or scenario_adjustments
        ):
            position = _position(signal_impact)
        elif position is not SpecialistPosition.ABSTAIN:
            position = _position(combined_impact)
        existing_adjustments = {item.label: item for item in analysis.scenario_adjustments}
        for item in scenario_adjustments:
            previous = existing_adjustments.get(item.label)
            if previous is None:
                existing_adjustments[item.label] = item
            else:
                existing_adjustments[item.label] = ScenarioAdjustment(
                    label=item.label,
                    return_delta=_clamp(
                        previous.return_delta + item.return_delta, -0.25, 0.25
                    ),
                    probability_delta=_clamp(
                        previous.probability_delta + item.probability_delta,
                        -0.20,
                        0.20,
                    ),
                    path_drawdown_delta=_clamp(
                        previous.path_drawdown_delta + item.path_drawdown_delta,
                        -0.25,
                        0.0,
                    ),
                )
        return replace(
            analysis,
            position=position,
            conclusion=(
                analysis.conclusion
                + " Forward intelligence adds "
                + ", ".join(item.name for item in signals)
                + f" with a combined {signal_impact:+.2%} candidate effect."
                if signals
                else analysis.conclusion
                + " Governed forward scenarios add candidate-specific transmission evidence."
            ),
            expected_return_impact=combined_impact,
            confidence=confidence,
            supporting_evidence=tuple(
                dict.fromkeys(
                    analysis.supporting_evidence
                    + tuple(value for item in signals for value in item.evidence)
                    + self.diagnostics
                )
            ),
            contradictory_evidence=tuple(
                dict.fromkeys(
                    analysis.contradictory_evidence
                    + tuple(
                        value
                        for item in signals
                        for value in item.contradictory_evidence
                    )
                )
            ),
            critical_assumptions=tuple(
                dict.fromkeys(
                    analysis.critical_assumptions
                    + tuple(value for item in signals for value in item.assumptions)
                )
            ),
            risks=tuple(
                dict.fromkeys(
                    analysis.risks
                    + tuple(value for item in signals for value in item.risks)
                )
            ),
            change_conditions=tuple(
                dict.fromkeys(
                    analysis.change_conditions
                    + tuple(
                        value for item in signals for value in item.change_conditions
                    )
                )
            ),
            limitations=tuple(
                dict.fromkeys(
                    analysis.limitations
                    + (
                        "Forward causal relationships remain probabilistic and must be revalidated as evidence changes",
                    )
                )
            ),
            evidence_origin_identifiers=tuple(
                dict.fromkeys(
                    analysis.evidence_origin_identifiers
                    + tuple(
                        value
                        for item in signals
                        for value in item.evidence_identifiers
                    )
                    + tuple(
                        value
                        for item in self.scenarios
                        for value in item.evidence_identifiers
                    )
                )
            ),
            scenario_adjustments=tuple(existing_adjustments.values()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "candidate_identifier": self.candidate_identifier,
            "as_of": self.as_of.isoformat(),
            "signals": [item.to_dict() for item in self.signals],
            "scenarios": [item.to_dict() for item in self.scenarios],
            "diagnostics": list(self.diagnostics),
            "model_versions": list(self.model_versions),
            "theme_stage": None if self.theme_stage is None else self.theme_stage.value,
            "trend_stage": None if self.trend_stage is None else self.trend_stage.value,
            "policy_regime": (
                None if self.policy_regime is None else self.policy_regime.value
            ),
            "currency_regime": (
                None if self.currency_regime is None else self.currency_regime.value
            ),
            "decision_context": (
                None if self.decision_context is None else self.decision_context.to_dict()
            ),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ForwardIntelligenceBundle":
        return cls(
            identifier=str(payload["identifier"]),
            candidate_identifier=str(payload["candidate_identifier"]),
            as_of=datetime.fromisoformat(str(payload["as_of"])),
            signals=tuple(ForwardSignal.from_dict(item) for item in payload["signals"]),
            scenarios=tuple(
                ForwardScenario.from_dict(item) for item in payload.get("scenarios", ())
            ),
            diagnostics=tuple(str(item) for item in payload.get("diagnostics", ())),
            model_versions=tuple(str(item) for item in payload["model_versions"]),
            theme_stage=(
                None
                if payload.get("theme_stage") is None
                else ThemeStage(str(payload["theme_stage"]))
            ),
            trend_stage=(
                None
                if payload.get("trend_stage") is None
                else TrendStage(str(payload["trend_stage"]))
            ),
            policy_regime=(
                None
                if payload.get("policy_regime") is None
                else PolicyRegime(str(payload["policy_regime"]))
            ),
            currency_regime=(
                None
                if payload.get("currency_regime") is None
                else CurrencyRegime(str(payload["currency_regime"]))
            ),
            decision_context=(
                None
                if payload.get("decision_context") is None
                else ForwardDecisionContext.from_dict(dict(payload["decision_context"]))
            ),
            schema_version=str(payload.get("schema_version", "forward-intelligence.v1")),
        )


@dataclass(frozen=True, slots=True)
class StrategicBusinessObservation:
    identifier: str
    as_of: datetime
    revenue_exposure: float
    demand_growth: float
    pricing_power: float
    capacity_adequacy: float
    incremental_margin: float
    market_share_trend: float
    capital_allocation_quality: float
    customer_concentration: float
    supplier_concentration: float
    valuation_priced_in: float
    evidence: tuple[str, ...]
    risks: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        _aware(self.as_of, field_name="as_of")
        for field_name in (
            "revenue_exposure",
            "customer_concentration",
            "supplier_concentration",
            "valuation_priced_in",
        ):
            object.__setattr__(self, field_name, _ratio(getattr(self, field_name), field_name=field_name))
        for field_name in (
            "demand_growth",
            "pricing_power",
            "capacity_adequacy",
            "incremental_margin",
            "market_share_trend",
            "capital_allocation_quality",
        ):
            object.__setattr__(self, field_name, _bounded(getattr(self, field_name), field_name=field_name))
        for field_name, minimum in (
            ("evidence", 1),
            ("risks", 1),
            ("evidence_identifiers", 1),
        ):
            object.__setattr__(self, field_name, _texts(getattr(self, field_name), field_name=field_name, minimum=minimum))


class StrategicBusinessEngine:
    version = "strategic-business-transmission.v1"

    def analyze(self, observation: StrategicBusinessObservation) -> ForwardSignal:
        positive = (
            0.22 * observation.demand_growth
            + 0.18 * observation.pricing_power
            + 0.16 * observation.incremental_margin
            + 0.14 * observation.market_share_trend
            + 0.12 * observation.capital_allocation_quality
            + 0.10 * observation.capacity_adequacy
        ) * observation.revenue_exposure
        concentration_penalty = 0.12 * max(
            observation.customer_concentration,
            observation.supplier_concentration,
        )
        priced_penalty = max(0.0, positive) * 0.75 * observation.valuation_priced_in
        impact = _clamp(positive - concentration_penalty - priced_penalty, -0.20, 0.20)
        confidence = _clamp(
            0.45
            + 0.30 * observation.revenue_exposure
            + 0.15 * (1.0 - max(observation.customer_concentration, observation.supplier_concentration))
            + 0.10 * (1.0 - observation.valuation_priced_in),
            0.0,
            1.0,
        )
        return ForwardSignal(
            identifier=f"signal:business:{observation.identifier}",
            as_of=observation.as_of,
            name="strategic business economics",
            channels=("fundamental",),
            expected_return_impact=impact,
            confidence=confidence,
            evidence=observation.evidence,
            contradictory_evidence=(
                f"Customer concentration={observation.customer_concentration:.0%}",
                f"Supplier concentration={observation.supplier_concentration:.0%}",
                f"Estimated benefit already priced={observation.valuation_priced_in:.0%}",
            ),
            assumptions=(
                "Segment demand translates into reported revenue and incremental earnings",
                "The company retains sufficient capacity and competitive position to serve demand",
            ),
            risks=observation.risks,
            change_conditions=(
                "Reassess after material changes in orders, backlog, capacity, pricing, market share, margins, customer concentration, or valuation",
            ),
            evidence_identifiers=observation.evidence_identifiers,
        )


@dataclass(frozen=True, slots=True)
class MarketTrendObservation:
    identifier: str
    as_of: datetime
    absolute_trend: float
    relative_trend: float
    breadth: float
    earnings_revision_breadth: float
    volume_confirmation: float
    leadership_concentration: float
    crowding: float
    valuation_expansion_share: float
    reversal_signal: float
    evidence: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        _aware(self.as_of, field_name="as_of")
        for field_name in (
            "absolute_trend",
            "relative_trend",
            "breadth",
            "earnings_revision_breadth",
            "volume_confirmation",
        ):
            object.__setattr__(self, field_name, _bounded(getattr(self, field_name), field_name=field_name))
        for field_name in (
            "leadership_concentration",
            "crowding",
            "valuation_expansion_share",
            "reversal_signal",
        ):
            object.__setattr__(self, field_name, _ratio(getattr(self, field_name), field_name=field_name))
        object.__setattr__(self, "evidence", _texts(self.evidence, field_name="evidence", minimum=1))
        object.__setattr__(self, "evidence_identifiers", _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1))


@dataclass(frozen=True, slots=True)
class TrendAssessment:
    stage: TrendStage
    signal: ForwardSignal


class MarketTrendEngine:
    version = "market-cycle-trend.v1"

    def analyze(self, observation: MarketTrendObservation) -> TrendAssessment:
        core = (
            0.24 * observation.absolute_trend
            + 0.20 * observation.relative_trend
            + 0.20 * observation.breadth
            + 0.20 * observation.earnings_revision_breadth
            + 0.16 * observation.volume_confirmation
        )
        fragility = (
            0.35 * observation.leadership_concentration
            + 0.30 * observation.crowding
            + 0.20 * observation.valuation_expansion_share
            + 0.45 * observation.reversal_signal
        )
        impact = _clamp(0.12 * core - 0.10 * fragility, -0.15, 0.15)
        if observation.reversal_signal >= 0.65:
            stage = TrendStage.REVERSING
        elif core < -0.20:
            stage = TrendStage.DETERIORATING
        elif observation.crowding >= 0.75 or observation.leadership_concentration >= 0.80:
            stage = TrendStage.CROWDED
        elif core >= 0.60 and observation.breadth >= 0.45:
            stage = TrendStage.BROADENING
        elif core >= 0.40:
            stage = TrendStage.CONFIRMED
        elif core >= 0.10:
            stage = TrendStage.EARLY
        else:
            stage = TrendStage.MATURE
        signal = ForwardSignal(
            identifier=f"signal:trend:{observation.identifier}",
            as_of=observation.as_of,
            name=f"{stage.value.replace('_', ' ')} market trend",
            channels=("market",),
            expected_return_impact=impact,
            confidence=_clamp(0.50 + 0.30 * abs(core) + 0.20 * observation.volume_confirmation, 0.0, 1.0),
            evidence=observation.evidence,
            contradictory_evidence=(
                f"Leadership concentration={observation.leadership_concentration:.0%}",
                f"Crowding={observation.crowding:.0%}",
                f"Valuation-led appreciation={observation.valuation_expansion_share:.0%}",
            ),
            assumptions=(
                "Price trend, breadth, volume, and earnings revisions remain representative through implementation",
            ),
            risks=(
                "A narrow or valuation-led rally can reverse before reported fundamentals change",
                "Crowding can amplify drawdowns and execution costs",
            ),
            change_conditions=(
                "Reclassify after material changes in relative strength, breadth, revisions, volume, leadership concentration, crowding, or reversal evidence",
            ),
            evidence_identifiers=observation.evidence_identifiers,
        )
        return TrendAssessment(stage=stage, signal=signal)


@dataclass(frozen=True, slots=True)
class ThemeNodeObservation:
    name: str
    demand_growth: float
    capacity_growth: float
    utilization: float
    lead_time_pressure: float
    pricing_power: float
    supplier_concentration: float
    substitution_risk: float
    beneficiary_symbols: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, field_name="name"))
        for field_name in ("demand_growth", "capacity_growth", "lead_time_pressure", "pricing_power"):
            object.__setattr__(self, field_name, _bounded(getattr(self, field_name), field_name=field_name))
        for field_name in ("utilization", "supplier_concentration", "substitution_risk"):
            object.__setattr__(self, field_name, _ratio(getattr(self, field_name), field_name=field_name))
        object.__setattr__(self, "beneficiary_symbols", _texts(self.beneficiary_symbols, field_name="beneficiary_symbols"))
        object.__setattr__(self, "evidence_identifiers", _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1))

    @property
    def bottleneck_score(self) -> float:
        scarcity = self.demand_growth - self.capacity_growth
        score = (
            0.30 * scarcity
            + 0.20 * self.utilization
            + 0.15 * self.lead_time_pressure
            + 0.15 * self.pricing_power
            + 0.12 * self.supplier_concentration
            - 0.18 * self.substitution_risk
        )
        return _clamp(score, -1.0, 1.0)


@dataclass(frozen=True, slots=True)
class ThemeLink:
    source: str
    target: str
    transmission_strength: float
    lag_days: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _text(self.source, field_name="source"))
        object.__setattr__(self, "target", _text(self.target, field_name="target"))
        object.__setattr__(self, "transmission_strength", _ratio(self.transmission_strength, field_name="transmission_strength"))
        if isinstance(self.lag_days, bool) or not isinstance(self.lag_days, int):
            raise TypeError("lag_days must be an integer")
        if self.lag_days < 0:
            raise ValueError("lag_days cannot be negative")
        if self.source == self.target:
            raise ValueError("theme link cannot reference the same node")


@dataclass(frozen=True, slots=True)
class StructuralThemeObservation:
    identifier: str
    name: str
    as_of: datetime
    demand_origin: str
    candidate_node: str
    nodes: tuple[ThemeNodeObservation, ...]
    links: tuple[ThemeLink, ...]
    theme_demand_growth: float
    market_pricing_score: float
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("identifier", "name", "demand_origin", "candidate_node"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name=field_name))
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.nodes, tuple) or not all(isinstance(item, ThemeNodeObservation) for item in self.nodes):
            raise TypeError("nodes must contain ThemeNodeObservation values")
        if not isinstance(self.links, tuple) or not all(isinstance(item, ThemeLink) for item in self.links):
            raise TypeError("links must contain ThemeLink values")
        names = tuple(item.name for item in self.nodes)
        if len(names) != len(set(names)):
            raise ValueError("theme node names must be unique")
        if self.demand_origin not in names or self.candidate_node not in names:
            raise ValueError("demand origin and candidate node must exist in nodes")
        if any(item.source not in names or item.target not in names for item in self.links):
            raise ValueError("theme links must reference declared nodes")
        object.__setattr__(self, "theme_demand_growth", _bounded(self.theme_demand_growth, field_name="theme_demand_growth"))
        object.__setattr__(self, "market_pricing_score", _ratio(self.market_pricing_score, field_name="market_pricing_score"))
        object.__setattr__(self, "evidence", _texts(self.evidence, field_name="evidence", minimum=1))


@dataclass(frozen=True, slots=True)
class ThemeAssessment:
    stage: ThemeStage
    bottlenecks: tuple[tuple[str, float], ...]
    next_beneficiaries: tuple[str, ...]
    signal: ForwardSignal
    scenarios: tuple[ForwardScenario, ...]


class StructuralThemeEngine:
    version = "structural-theme-transmission.v1"

    @staticmethod
    def _reachable_strength(observation: StructuralThemeObservation) -> dict[str, float]:
        scores = {observation.demand_origin: 1.0}
        for _ in range(len(observation.nodes)):
            changed = False
            for link in observation.links:
                source = scores.get(link.source)
                if source is None:
                    continue
                candidate = source * link.transmission_strength * (1.0 / (1.0 + link.lag_days / 365.0))
                if candidate > scores.get(link.target, 0.0):
                    scores[link.target] = candidate
                    changed = True
            if not changed:
                break
        return scores

    def analyze(self, observation: StructuralThemeObservation) -> ThemeAssessment:
        by_name = {item.name: item for item in observation.nodes}
        transmission = self._reachable_strength(observation)
        bottlenecks = tuple(
            sorted(
                ((item.name, item.bottleneck_score) for item in observation.nodes),
                key=lambda item: (-item[1], item[0]),
            )
        )
        candidate = by_name[observation.candidate_node]
        candidate_strength = transmission.get(candidate.name, 0.0)
        raw = candidate.bottleneck_score * candidate_strength * max(0.0, observation.theme_demand_growth)
        impact = _clamp(raw * (1.0 - 0.75 * observation.market_pricing_score), -0.20, 0.20)
        top_score = bottlenecks[0][1] if bottlenecks else 0.0
        if observation.market_pricing_score >= 0.80:
            stage = ThemeStage.CROWDED
        elif top_score >= 0.55:
            stage = ThemeStage.SUPPLY_CONSTRAINED
        elif observation.theme_demand_growth >= 0.50:
            stage = ThemeStage.ACCELERATING
        elif observation.theme_demand_growth >= 0.20:
            stage = ThemeStage.BROADENING
        elif observation.theme_demand_growth < -0.20:
            stage = ThemeStage.DECELERATING
        elif candidate.capacity_growth > candidate.demand_growth:
            stage = ThemeStage.CAPACITY_EXPANDING
        elif candidate.capacity_growth > 0.40 and candidate.bottleneck_score < 0.0:
            stage = ThemeStage.OVERSUPPLIED
        else:
            stage = ThemeStage.EMERGING
        beneficiaries = tuple(
            dict.fromkeys(
                symbol
                for node_name, score in bottlenecks
                if score > 0.20
                for symbol in by_name[node_name].beneficiary_symbols
            )
        )
        evidence_ids = tuple(
            dict.fromkeys(
                identifier
                for item in observation.nodes
                for identifier in item.evidence_identifiers
            )
        )
        signal = ForwardSignal(
            identifier=f"signal:theme:{observation.identifier}:{candidate.name}",
            as_of=observation.as_of,
            name=f"{observation.name} demand transmission",
            channels=("forecast", "fundamental"),
            expected_return_impact=impact,
            confidence=_clamp(0.40 + 0.35 * candidate_strength + 0.25 * abs(candidate.bottleneck_score), 0.0, 1.0),
            evidence=(
                *observation.evidence,
                f"Candidate node={candidate.name}",
                f"Transmission strength={candidate_strength:.2f}",
                f"Bottleneck score={candidate.bottleneck_score:+.2f}",
                f"Theme stage={stage.value}",
            ),
            contradictory_evidence=(
                f"Capacity growth={candidate.capacity_growth:+.2f}",
                f"Substitution risk={candidate.substitution_risk:.0%}",
                f"Estimated theme benefit already priced={observation.market_pricing_score:.0%}",
            ),
            assumptions=(
                "Demand propagates through the disclosed value-chain links within their stated lags",
                "The candidate can convert the identified bottleneck into revenue and earnings",
            ),
            risks=(
                "Capacity additions, substitution, weaker end demand, or customer redesign can break the transmission chain",
                "A correct theme can still be a poor investment when expectations are already priced",
            ),
            change_conditions=(
                "Reassess after material changes in demand, orders, utilization, capacity, lead times, pricing, substitution, or valuation",
            ),
            evidence_identifiers=evidence_ids,
        )
        scenarios = (
            ForwardScenario(
                label="bull",
                return_delta=_clamp(max(0.0, impact) * 1.25, 0.0, 0.25),
                probability_delta=_clamp(0.08 * max(0.0, candidate.bottleneck_score), 0.0, 0.10),
                path_drawdown_delta=0.0,
                rationale="Demand persists and the candidate remains the constrained beneficiary.",
                evidence_identifiers=evidence_ids,
            ),
            ForwardScenario(
                label="base",
                return_delta=impact,
                probability_delta=0.0,
                path_drawdown_delta=_clamp(-0.03 * observation.market_pricing_score, -0.10, 0.0),
                rationale="Demand transmission continues with partial capacity response and partial pricing realization.",
                evidence_identifiers=evidence_ids,
            ),
            ForwardScenario(
                label="bear",
                return_delta=_clamp(-0.12 * (candidate.substitution_risk + max(0.0, candidate.capacity_growth)), -0.25, 0.0),
                probability_delta=_clamp(0.06 * observation.market_pricing_score, 0.0, 0.10),
                path_drawdown_delta=_clamp(-0.10 - 0.10 * observation.market_pricing_score, -0.25, 0.0),
                rationale="Capacity catches up, substitution emerges, or end demand weakens before earnings materialize.",
                evidence_identifiers=evidence_ids,
            ),
        )
        return ThemeAssessment(
            stage=stage,
            bottlenecks=bottlenecks,
            next_beneficiaries=beneficiaries,
            signal=signal,
            scenarios=scenarios,
        )


@dataclass(frozen=True, slots=True)
class MonetaryPolicyObservation:
    identifier: str
    as_of: datetime
    regime: PolicyRegime
    motive: PolicyMotive
    inflation_trend: float
    growth_trend: float
    financial_stress: float
    liquidity_impulse: float
    real_yield_change: float
    credit_spread_change: float
    market_pricing_score: float
    evidence: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.regime, PolicyRegime):
            raise TypeError("regime must be PolicyRegime")
        if not isinstance(self.motive, PolicyMotive):
            raise TypeError("motive must be PolicyMotive")
        for field_name in ("inflation_trend", "growth_trend", "liquidity_impulse", "real_yield_change", "credit_spread_change"):
            object.__setattr__(self, field_name, _bounded(getattr(self, field_name), field_name=field_name))
        for field_name in ("financial_stress", "market_pricing_score"):
            object.__setattr__(self, field_name, _ratio(getattr(self, field_name), field_name=field_name))
        object.__setattr__(self, "evidence", _texts(self.evidence, field_name="evidence", minimum=1))
        object.__setattr__(self, "evidence_identifiers", _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1))


@dataclass(frozen=True, slots=True)
class AssetPolicySensitivity:
    liquidity: float
    duration: float
    credit: float
    inflation: float
    growth: float

    def __post_init__(self) -> None:
        for field_name in ("liquidity", "duration", "credit", "inflation", "growth"):
            object.__setattr__(self, field_name, _bounded(getattr(self, field_name), field_name=field_name))


@dataclass(frozen=True, slots=True)
class MonetaryAssessment:
    regime: PolicyRegime
    signal: ForwardSignal
    scenarios: tuple[ForwardScenario, ...]


class MonetaryPolicyTransmissionEngine:
    version = "monetary-policy-transmission.v1"

    _POLICY_IMPULSE = {
        PolicyRegime.ACCELERATING_QE: 1.0,
        PolicyRegime.DECELERATING_QE: 0.45,
        PolicyRegime.STABLE_BALANCE_SHEET: 0.0,
        PolicyRegime.EARLY_QT: -0.35,
        PolicyRegime.ACCELERATING_QT: -0.85,
        PolicyRegime.RATE_HIKING: -0.65,
        PolicyRegime.RESTRICTIVE_HOLD: -0.20,
        PolicyRegime.RATE_CUTTING: 0.55,
        PolicyRegime.EMERGENCY_EASING: 0.70,
        PolicyRegime.POLICY_CONFLICT: 0.0,
    }

    def analyze(
        self,
        observation: MonetaryPolicyObservation,
        sensitivity: AssetPolicySensitivity,
    ) -> MonetaryAssessment:
        policy = self._POLICY_IMPULSE[observation.regime]
        transmission = (
            0.20 * sensitivity.liquidity * (0.55 * policy + 0.45 * observation.liquidity_impulse)
            + 0.20 * sensitivity.duration * (-observation.real_yield_change)
            + 0.18 * sensitivity.credit * (-observation.credit_spread_change)
            + 0.16 * sensitivity.inflation * observation.inflation_trend
            + 0.16 * sensitivity.growth * observation.growth_trend
        )
        crisis_penalty = 0.0
        if observation.motive is PolicyMotive.FINANCIAL_CRISIS:
            crisis_penalty = observation.financial_stress * (
                0.15 * max(0.0, sensitivity.growth)
                + 0.15 * max(0.0, sensitivity.credit)
            )
            transmission += 0.10 * observation.financial_stress * max(0.0, sensitivity.duration)
        inflation_conflict = max(0.0, observation.inflation_trend) * max(
            0.0, sensitivity.duration
        ) * 0.12
        raw = transmission - crisis_penalty - inflation_conflict
        impact = _clamp(raw * (1.0 - 0.75 * observation.market_pricing_score), -0.20, 0.20)
        signal = ForwardSignal(
            identifier=f"signal:monetary:{observation.identifier}",
            as_of=observation.as_of,
            name=f"{observation.regime.value.replace('_', ' ')} policy transmission",
            channels=("macro", "forecast"),
            expected_return_impact=impact,
            confidence=_clamp(
                0.45
                + 0.25 * abs(observation.liquidity_impulse)
                + 0.15 * abs(observation.real_yield_change)
                + 0.15 * abs(observation.credit_spread_change),
                0.0,
                1.0,
            ),
            evidence=(
                *observation.evidence,
                f"Policy motive={observation.motive.value}",
                f"Liquidity impulse={observation.liquidity_impulse:+.2f}",
                f"Real-yield change={observation.real_yield_change:+.2f}",
                f"Credit-spread change={observation.credit_spread_change:+.2f}",
            ),
            contradictory_evidence=(
                f"Financial stress={observation.financial_stress:.0%}",
                f"Inflation trend={observation.inflation_trend:+.2f}",
                f"Policy outcome already priced={observation.market_pricing_score:.0%}",
            ),
            assumptions=(
                "Policy implementation, not announcement alone, reaches liquidity, real-yield, currency, credit, valuation, and earnings channels",
                "Candidate sensitivities remain stable over the decision horizon",
            ),
            risks=(
                "Emergency easing may initially accompany recession, widening spreads, and falling earnings rather than broad risk-on behavior",
                "Inflation, term premium, fiscal supply, or currency stress can offset easier policy",
            ),
            change_conditions=(
                "Reassess when balance-sheet operations, inflation, growth, stress, real yields, credit spreads, or market-implied policy expectations change",
            ),
            evidence_identifiers=observation.evidence_identifiers,
        )
        scenarios = (
            ForwardScenario(
                label="bull",
                return_delta=_clamp(max(0.0, impact) + 0.05 * max(0.0, sensitivity.liquidity), 0.0, 0.25),
                probability_delta=_clamp(0.05 * max(0.0, observation.growth_trend - observation.financial_stress), 0.0, 0.08),
                path_drawdown_delta=0.0,
                rationale="Disinflationary easing transmits through lower real yields, stable credit, and improving breadth.",
                evidence_identifiers=observation.evidence_identifiers,
            ),
            ForwardScenario(
                label="base",
                return_delta=impact,
                probability_delta=0.0,
                path_drawdown_delta=_clamp(-0.04 * observation.financial_stress, -0.10, 0.0),
                rationale="Policy transmits partially and is partly reflected in market pricing.",
                evidence_identifiers=observation.evidence_identifiers,
            ),
            ForwardScenario(
                label="bear",
                return_delta=_clamp(-0.15 * max(observation.financial_stress, max(0.0, observation.inflation_trend)), -0.25, 0.0),
                probability_delta=_clamp(0.06 * max(observation.financial_stress, max(0.0, observation.inflation_trend)), 0.0, 0.10),
                path_drawdown_delta=_clamp(-0.08 - 0.12 * observation.financial_stress, -0.25, 0.0),
                rationale="Easing responds to crisis or inflation reaccelerates, weakening earnings or lifting term premia despite policy support.",
                evidence_identifiers=observation.evidence_identifiers,
            ),
        )
        return MonetaryAssessment(regime=observation.regime, signal=signal, scenarios=scenarios)


@dataclass(frozen=True, slots=True)
class CurrencyObservation:
    identifier: str
    as_of: datetime
    base_currency: str
    reporting_currency: str
    dollar_strength: float
    real_yield_differential: float
    dollar_funding_stress: float
    fx_volatility: float
    commodity_dollar_beta: float
    market_pricing_score: float
    evidence: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        _aware(self.as_of, field_name="as_of")
        for field_name in ("base_currency", "reporting_currency"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name=field_name).upper())
        for field_name in ("dollar_strength", "real_yield_differential", "commodity_dollar_beta"):
            object.__setattr__(self, field_name, _bounded(getattr(self, field_name), field_name=field_name))
        for field_name in ("dollar_funding_stress", "fx_volatility", "market_pricing_score"):
            object.__setattr__(self, field_name, _ratio(getattr(self, field_name), field_name=field_name))
        object.__setattr__(self, "evidence", _texts(self.evidence, field_name="evidence", minimum=1))
        object.__setattr__(self, "evidence_identifiers", _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1))


@dataclass(frozen=True, slots=True)
class CurrencyExposure:
    unhedged_foreign_asset_share: float
    foreign_revenue_share: float
    usd_revenue_share: float
    local_cost_share: float
    usd_debt_share: float
    commodity_input_share: float
    commodity_revenue_share: float
    emerging_market_funding_sensitivity: float
    hedge_ratio: float

    def __post_init__(self) -> None:
        for field_name in (
            "unhedged_foreign_asset_share",
            "foreign_revenue_share",
            "usd_revenue_share",
            "local_cost_share",
            "usd_debt_share",
            "commodity_input_share",
            "commodity_revenue_share",
            "emerging_market_funding_sensitivity",
            "hedge_ratio",
        ):
            object.__setattr__(self, field_name, _ratio(getattr(self, field_name), field_name=field_name))


@dataclass(frozen=True, slots=True)
class CurrencyAssessment:
    regime: CurrencyRegime
    signal: ForwardSignal
    scenarios: tuple[ForwardScenario, ...]
    components: tuple[tuple[str, float], ...]


class CurrencyTransmissionEngine:
    version = "currency-market-transmission.v1"

    def analyze(
        self,
        observation: CurrencyObservation,
        exposure: CurrencyExposure,
    ) -> CurrencyAssessment:
        usd = observation.dollar_strength
        unhedged = 1.0 - exposure.hedge_ratio
        translation = -0.10 * usd * exposure.unhedged_foreign_asset_share * unhedged
        multinational_translation = -0.06 * usd * exposure.foreign_revenue_share * unhedged
        exporter_margin = (
            0.08 * usd * exposure.usd_revenue_share * exposure.local_cost_share
            if observation.base_currency != "USD"
            else 0.0
        )
        funding = -0.12 * (
            observation.dollar_funding_stress + max(0.0, usd)
        ) * (
            0.60 * exposure.usd_debt_share
            + 0.40 * exposure.emerging_market_funding_sensitivity
        )
        commodities = 0.08 * observation.commodity_dollar_beta * usd * (
            exposure.commodity_revenue_share - exposure.commodity_input_share
        )
        carry = 0.04 * observation.real_yield_differential
        volatility_cost = -0.05 * observation.fx_volatility * unhedged * (
            exposure.unhedged_foreign_asset_share + exposure.foreign_revenue_share
        )
        components = (
            ("translation", translation),
            ("multinational_translation", multinational_translation),
            ("exporter_margin", exporter_margin),
            ("dollar_funding", funding),
            ("commodity_invoicing", commodities),
            ("real_yield_carry", carry),
            ("fx_volatility", volatility_cost),
        )
        raw = sum(value for _, value in components)
        impact = _clamp(raw * (1.0 - 0.70 * observation.market_pricing_score), -0.20, 0.20)
        if observation.dollar_funding_stress >= 0.65:
            regime = CurrencyRegime.DOLLAR_FUNDING_STRESS
        elif observation.fx_volatility >= 0.70:
            regime = CurrencyRegime.HIGH_FX_VOLATILITY
        elif usd >= 0.25:
            regime = CurrencyRegime.STRONG_DOLLAR
        elif usd <= -0.25:
            regime = CurrencyRegime.WEAK_DOLLAR
        else:
            regime = CurrencyRegime.BALANCED
        signal = ForwardSignal(
            identifier=f"signal:currency:{observation.identifier}",
            as_of=observation.as_of,
            name=f"{regime.value.replace('_', ' ')} transmission",
            channels=("macro", "forecast", "fundamental"),
            expected_return_impact=impact,
            confidence=_clamp(
                0.45
                + 0.20 * abs(usd)
                + 0.20 * observation.dollar_funding_stress
                + 0.15 * observation.fx_volatility,
                0.0,
                1.0,
            ),
            evidence=(
                *observation.evidence,
                *(f"{name} effect={value:+.2%}" for name, value in components),
                f"Hedge ratio={exposure.hedge_ratio:.0%}",
            ),
            contradictory_evidence=(
                f"Currency effect already priced={observation.market_pricing_score:.0%}",
                "Dollar strength can benefit non-U.S. exporters with U.S.-dollar revenue and local-currency costs even while it pressures unhedged foreign assets and dollar borrowers",
            ),
            assumptions=(
                "Reported currency exposures, hedge ratios, debt currency, revenue currency, and cost currency remain representative",
                "Dollar, carry, funding, commodity-invoicing, and translation channels remain active over the decision horizon",
            ),
            risks=(
                "Currency effects can reverse when policy differentials, intervention, funding conditions, or hedges change",
                "A broad dollar move has different effects across exporters, importers, commodities, emerging markets, and multinational earnings",
            ),
            change_conditions=(
                "Reassess after material changes in dollar trend, real-yield differentials, funding stress, FX volatility, hedges, debt currency, revenue currency, cost currency, or commodity exposure",
            ),
            evidence_identifiers=observation.evidence_identifiers,
        )
        adverse = max(observation.dollar_funding_stress, observation.fx_volatility)
        scenarios = (
            ForwardScenario(
                label="bull",
                return_delta=_clamp(max(0.0, impact) + 0.04 * max(0.0, exporter_margin), 0.0, 0.20),
                probability_delta=_clamp(0.04 * max(0.0, -usd), 0.0, 0.06),
                path_drawdown_delta=0.0,
                rationale="Currency translation, carry, exporter margins, or easier dollar funding reinforce the candidate thesis.",
                evidence_identifiers=observation.evidence_identifiers,
            ),
            ForwardScenario(
                label="base",
                return_delta=impact,
                probability_delta=0.0,
                path_drawdown_delta=_clamp(-0.03 * observation.fx_volatility, -0.08, 0.0),
                rationale="Currency effects remain close to the point-in-time exposure and hedge assumptions.",
                evidence_identifiers=observation.evidence_identifiers,
            ),
            ForwardScenario(
                label="bear",
                return_delta=_clamp(min(0.0, impact) - 0.10 * adverse, -0.25, 0.0),
                probability_delta=_clamp(0.06 * adverse, 0.0, 0.10),
                path_drawdown_delta=_clamp(-0.08 - 0.12 * adverse, -0.25, 0.0),
                rationale="Dollar funding tightens, translation losses rise, commodity or emerging-market stress spreads, or hedges fail to offset exposure.",
                evidence_identifiers=observation.evidence_identifiers,
            ),
        )
        return CurrencyAssessment(
            regime=regime,
            signal=signal,
            scenarios=scenarios,
            components=tuple((name, round(value, 8)) for name, value in components),
        )


def build_forward_intelligence_bundle(
    *,
    identifier: str,
    candidate_identifier: str,
    as_of: datetime,
    business: ForwardSignal | None = None,
    trend: TrendAssessment | None = None,
    theme: ThemeAssessment | None = None,
    monetary: MonetaryAssessment | None = None,
    currency: CurrencyAssessment | None = None,
    decision_context: ForwardDecisionContext | None = None,
) -> ForwardIntelligenceBundle:
    signals = tuple(
        item
        for item in (
            business,
            None if trend is None else trend.signal,
            None if theme is None else theme.signal,
            None if monetary is None else monetary.signal,
            None if currency is None else currency.signal,
        )
        if item is not None
    )
    scenarios = tuple(
        item
        for assessment in (theme, monetary, currency)
        if assessment is not None
        for item in assessment.scenarios
    )
    diagnostics: list[str] = []
    if theme is not None:
        diagnostics.append(
            "Theme bottlenecks: "
            + ", ".join(f"{name}={score:+.2f}" for name, score in theme.bottlenecks[:3])
        )
        if theme.next_beneficiaries:
            diagnostics.append(
                "Potential next beneficiaries: " + ", ".join(theme.next_beneficiaries)
            )
    if currency is not None:
        diagnostics.append(
            "Currency transmission: "
            + ", ".join(f"{name}={value:+.2%}" for name, value in currency.components)
        )
    versions = tuple(
        dict.fromkeys(
            item
            for assessment, item in (
                (business, StrategicBusinessEngine.version),
                (trend, MarketTrendEngine.version),
                (theme, StructuralThemeEngine.version),
                (monetary, MonetaryPolicyTransmissionEngine.version),
                (currency, CurrencyTransmissionEngine.version),
            )
            if assessment is not None
        )
    )
    if decision_context is not None:
        versions = tuple(dict.fromkeys((*versions, decision_context.schema_version)))
    return ForwardIntelligenceBundle(
        identifier=identifier,
        candidate_identifier=candidate_identifier,
        as_of=as_of,
        signals=signals,
        scenarios=scenarios,
        diagnostics=tuple(diagnostics),
        model_versions=versions or ("forward-intelligence-empty.v1",),
        theme_stage=None if theme is None else theme.stage,
        trend_stage=None if trend is None else trend.stage,
        policy_regime=None if monetary is None else monetary.regime,
        currency_regime=None if currency is None else currency.regime,
        decision_context=decision_context,
    )


__all__ = [
    "AssetPolicySensitivity",
    "CurrencyAssessment",
    "CurrencyExposure",
    "CurrencyObservation",
    "CurrencyRegime",
    "CurrencyTransmissionEngine",
    "ForwardIntelligenceBundle",
    "ForwardScenario",
    "ForwardSignal",
    "MarketTrendEngine",
    "MarketTrendObservation",
    "MonetaryAssessment",
    "MonetaryPolicyObservation",
    "MonetaryPolicyTransmissionEngine",
    "PolicyMotive",
    "PolicyRegime",
    "StrategicBusinessEngine",
    "StrategicBusinessObservation",
    "StructuralThemeEngine",
    "StructuralThemeObservation",
    "ThemeAssessment",
    "ThemeLink",
    "ThemeNodeObservation",
    "ThemeStage",
    "TrendAssessment",
    "TrendStage",
    "build_forward_intelligence_bundle",
]
