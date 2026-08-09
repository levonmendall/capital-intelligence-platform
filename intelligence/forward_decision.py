"""Canonical Forward Decision Intelligence v2 advisory context.

This module standardizes forward-looking evidence that should be challenged by the
existing six-specialist committee before any CIO decision.  It never authorizes
capital, changes a CIO threshold, or turns an unavailable information domain into
synthetic evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from math import isfinite
from typing import Any, Mapping

from cio.committee import SpecialistAnalysis
from cio.models import CandidateAssetClass, SpecialistRole


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} cannot be empty")
    return value


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _number(value: object, *, field_name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    value = float(value)
    if not isfinite(value) or not low <= value <= high:
        raise ValueError(f"{field_name} must be finite and between {low} and {high}")
    return round(value, 8)


def _texts(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


class ForwardDecisionDimension(str, Enum):
    REGIME = "regime"
    FUNDAMENTALS = "fundamental_trajectory"
    EXPECTATIONS = "expectations_gap"
    CATALYSTS = "catalysts_events"
    EARNINGS = "earnings_events"
    DERIVATIVES = "derivatives_options"
    POSITIONING = "flows_positioning"
    CROSS_ASSET = "cross_asset_confirmation"
    MICROSTRUCTURE = "market_microstructure"
    REFLEXIVITY = "reflexivity_forced_flows"
    STRUCTURAL = "structural_transmission"
    CORPORATE_ACTIONS = "corporate_actions"
    ALTERNATIVE_DATA = "real_world_leading_indicators"
    PATH_RISK = "path_time_risk"
    PORTFOLIO_CONTEXT = "portfolio_opportunity_cost"
    CALIBRATION = "forecast_calibration"


class EvidenceAvailability(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class DecisionTimingPosture(str, Enum):
    ACT_NOW = "act_now"
    WAIT_FOR_EVENT = "wait_for_event"
    REASSESS = "reassess"
    NO_TIMING_EDGE = "no_timing_edge"


@dataclass(frozen=True, slots=True)
class ForwardDimensionAssessment:
    dimension: ForwardDecisionDimension
    availability: EvidenceAvailability
    summary: str
    confidence: float
    evidence: tuple[str, ...] = ()
    contradictory_evidence: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    change_conditions: tuple[str, ...] = ()
    evidence_identifiers: tuple[str, ...] = ()
    market_expectation: str | None = None
    internal_expectation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, ForwardDecisionDimension):
            raise TypeError("dimension must be ForwardDecisionDimension")
        if not isinstance(self.availability, EvidenceAvailability):
            raise TypeError("availability must be EvidenceAvailability")
        object.__setattr__(self, "summary", _text(self.summary, field_name="summary"))
        object.__setattr__(
            self,
            "confidence",
            _number(self.confidence, field_name="confidence", low=0.0, high=1.0),
        )
        for name in (
            "evidence",
            "contradictory_evidence",
            "assumptions",
            "risks",
            "change_conditions",
            "evidence_identifiers",
        ):
            object.__setattr__(self, name, _texts(getattr(self, name), field_name=name))
        for name in ("market_expectation", "internal_expectation"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _text(value, field_name=name))
        if self.availability in {EvidenceAvailability.AVAILABLE, EvidenceAvailability.PARTIAL} and not self.evidence_identifiers:
            raise ValueError("available/partial forward dimensions require governed evidence identifiers")
        if self.availability in {EvidenceAvailability.UNAVAILABLE, EvidenceAvailability.NOT_APPLICABLE}:
            if self.evidence_identifiers:
                raise ValueError("unavailable/not-applicable dimensions cannot claim evidence identifiers")
            if self.confidence != 0.0:
                raise ValueError("unavailable/not-applicable dimensions must have zero confidence")

    @property
    def is_usable(self) -> bool:
        return self.availability in {EvidenceAvailability.AVAILABLE, EvidenceAvailability.PARTIAL}

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "availability": self.availability.value,
            "summary": self.summary,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "contradictory_evidence": list(self.contradictory_evidence),
            "assumptions": list(self.assumptions),
            "risks": list(self.risks),
            "change_conditions": list(self.change_conditions),
            "evidence_identifiers": list(self.evidence_identifiers),
            "market_expectation": self.market_expectation,
            "internal_expectation": self.internal_expectation,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ForwardDimensionAssessment":
        return cls(
            dimension=ForwardDecisionDimension(str(payload["dimension"])),
            availability=EvidenceAvailability(str(payload["availability"])),
            summary=str(payload["summary"]),
            confidence=float(payload["confidence"]),
            evidence=tuple(str(item) for item in payload.get("evidence", ())),
            contradictory_evidence=tuple(str(item) for item in payload.get("contradictory_evidence", ())),
            assumptions=tuple(str(item) for item in payload.get("assumptions", ())),
            risks=tuple(str(item) for item in payload.get("risks", ())),
            change_conditions=tuple(str(item) for item in payload.get("change_conditions", ())),
            evidence_identifiers=tuple(str(item) for item in payload.get("evidence_identifiers", ())),
            market_expectation=payload.get("market_expectation"),
            internal_expectation=payload.get("internal_expectation"),
        )


@dataclass(frozen=True, slots=True)
class EventScenario:
    label: str
    probability: float
    return_impact: float
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _text(self.label, field_name="label"))
        object.__setattr__(self, "probability", _number(self.probability, field_name="probability", low=0.0, high=1.0))
        object.__setattr__(self, "return_impact", _number(self.return_impact, field_name="return_impact", low=-1.0, high=1.0))
        object.__setattr__(self, "rationale", _text(self.rationale, field_name="rationale"))

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "probability": self.probability, "return_impact": self.return_impact, "rationale": self.rationale}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EventScenario":
        return cls(label=str(payload["label"]), probability=float(payload["probability"]), return_impact=float(payload["return_impact"]), rationale=str(payload["rationale"]))


@dataclass(frozen=True, slots=True)
class CatalystEvent:
    identifier: str
    event_type: str
    scheduled_at: datetime
    expected_outcome: str
    market_expectation: str
    scenarios: tuple[EventScenario, ...]
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("identifier", "event_type", "expected_outcome", "market_expectation"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        _aware(self.scheduled_at, field_name="scheduled_at")
        if not isinstance(self.scenarios, tuple) or not self.scenarios or not all(isinstance(item, EventScenario) for item in self.scenarios):
            raise TypeError("scenarios must contain EventScenario values")
        total = sum(item.probability for item in self.scenarios)
        if abs(total - 1.0) > 1e-6:
            raise ValueError("event scenario probabilities must sum to one")
        object.__setattr__(self, "evidence_identifiers", _texts(self.evidence_identifiers, field_name="evidence_identifiers"))
        if not self.evidence_identifiers:
            raise ValueError("catalyst events require governed evidence identifiers")

    @property
    def expected_return_impact(self) -> float:
        return round(sum(item.probability * item.return_impact for item in self.scenarios), 8)

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "event_type": self.event_type,
            "scheduled_at": self.scheduled_at.isoformat(),
            "expected_outcome": self.expected_outcome,
            "market_expectation": self.market_expectation,
            "scenarios": [item.to_dict() for item in self.scenarios],
            "evidence_identifiers": list(self.evidence_identifiers),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CatalystEvent":
        return cls(
            identifier=str(payload["identifier"]),
            event_type=str(payload["event_type"]),
            scheduled_at=datetime.fromisoformat(str(payload["scheduled_at"])),
            expected_outcome=str(payload["expected_outcome"]),
            market_expectation=str(payload["market_expectation"]),
            scenarios=tuple(EventScenario.from_dict(item) for item in payload["scenarios"]),
            evidence_identifiers=tuple(str(item) for item in payload["evidence_identifiers"]),
        )


@dataclass(frozen=True, slots=True)
class ReturnDistribution:
    horizon_days: int
    expected_return: float
    geometric_expected_return: float
    probability_positive: float
    probability_beat_cash: float
    probability_beat_best_alternative: float
    expected_max_drawdown: float
    tail_loss: float
    percentiles: tuple[tuple[int, float], ...]
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.horizon_days, bool) or not isinstance(self.horizon_days, int) or self.horizon_days <= 0:
            raise ValueError("horizon_days must be a positive integer")
        for name in ("expected_return", "geometric_expected_return"):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name, low=-1.0, high=10.0))
        for name in ("probability_positive", "probability_beat_cash", "probability_beat_best_alternative"):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name, low=0.0, high=1.0))
        for name in ("expected_max_drawdown", "tail_loss"):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name, low=-1.0, high=0.0))
        if not isinstance(self.percentiles, tuple) or not self.percentiles:
            raise ValueError("percentiles cannot be empty")
        normalized: list[tuple[int, float]] = []
        for percentile, value in self.percentiles:
            if isinstance(percentile, bool) or not isinstance(percentile, int) or not 0 <= percentile <= 100:
                raise ValueError("percentile keys must be integers from 0 to 100")
            normalized.append((percentile, _number(value, field_name="percentile return", low=-1.0, high=10.0)))
        if tuple(percentile for percentile, _ in normalized) != tuple(sorted(percentile for percentile, _ in normalized)):
            raise ValueError("percentiles must be sorted")
        object.__setattr__(self, "percentiles", tuple(normalized))
        object.__setattr__(self, "evidence_identifiers", _texts(self.evidence_identifiers, field_name="evidence_identifiers"))
        if not self.evidence_identifiers:
            raise ValueError("return distribution requires evidence identifiers")

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon_days": self.horizon_days,
            "expected_return": self.expected_return,
            "geometric_expected_return": self.geometric_expected_return,
            "probability_positive": self.probability_positive,
            "probability_beat_cash": self.probability_beat_cash,
            "probability_beat_best_alternative": self.probability_beat_best_alternative,
            "expected_max_drawdown": self.expected_max_drawdown,
            "tail_loss": self.tail_loss,
            "percentiles": [[key, value] for key, value in self.percentiles],
            "evidence_identifiers": list(self.evidence_identifiers),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReturnDistribution":
        return cls(
            horizon_days=int(payload["horizon_days"]),
            expected_return=float(payload["expected_return"]),
            geometric_expected_return=float(payload["geometric_expected_return"]),
            probability_positive=float(payload["probability_positive"]),
            probability_beat_cash=float(payload["probability_beat_cash"]),
            probability_beat_best_alternative=float(payload["probability_beat_best_alternative"]),
            expected_max_drawdown=float(payload["expected_max_drawdown"]),
            tail_loss=float(payload["tail_loss"]),
            percentiles=tuple((int(item[0]), float(item[1])) for item in payload["percentiles"]),
            evidence_identifiers=tuple(str(item) for item in payload["evidence_identifiers"]),
        )


@dataclass(frozen=True, slots=True)
class DecisionTiming:
    posture: DecisionTimingPosture
    rationale: str
    next_reassessment_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.posture, DecisionTimingPosture):
            raise TypeError("posture must be DecisionTimingPosture")
        object.__setattr__(self, "rationale", _text(self.rationale, field_name="rationale"))
        if self.next_reassessment_at is not None:
            _aware(self.next_reassessment_at, field_name="next_reassessment_at")

    def to_dict(self) -> dict[str, Any]:
        return {"posture": self.posture.value, "rationale": self.rationale, "next_reassessment_at": None if self.next_reassessment_at is None else self.next_reassessment_at.isoformat()}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DecisionTiming":
        raw = payload.get("next_reassessment_at")
        return cls(posture=DecisionTimingPosture(str(payload["posture"])), rationale=str(payload["rationale"]), next_reassessment_at=None if raw is None else datetime.fromisoformat(str(raw)))


@dataclass(frozen=True, slots=True)
class ThesisMonitor:
    thesis: str
    must_remain_true: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    monitor_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "thesis", _text(self.thesis, field_name="thesis"))
        for name in ("must_remain_true", "invalidation_conditions", "monitor_evidence"):
            object.__setattr__(self, name, _texts(getattr(self, name), field_name=name))
        if not self.invalidation_conditions:
            raise ValueError("thesis monitor requires at least one invalidation condition")

    def to_dict(self) -> dict[str, Any]:
        return {"thesis": self.thesis, "must_remain_true": list(self.must_remain_true), "invalidation_conditions": list(self.invalidation_conditions), "monitor_evidence": list(self.monitor_evidence)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ThesisMonitor":
        return cls(thesis=str(payload["thesis"]), must_remain_true=tuple(str(item) for item in payload.get("must_remain_true", ())), invalidation_conditions=tuple(str(item) for item in payload.get("invalidation_conditions", ())), monitor_evidence=tuple(str(item) for item in payload.get("monitor_evidence", ())))


# Asset-class applicability prevents irrelevant evidence requirements while retaining
# a common packet.  Domains not listed are explicitly not applicable, never silently
# treated as missing.
_BASE = {
    ForwardDecisionDimension.REGIME,
    ForwardDecisionDimension.EXPECTATIONS,
    ForwardDecisionDimension.CATALYSTS,
    ForwardDecisionDimension.DERIVATIVES,
    ForwardDecisionDimension.POSITIONING,
    ForwardDecisionDimension.CROSS_ASSET,
    ForwardDecisionDimension.MICROSTRUCTURE,
    ForwardDecisionDimension.REFLEXIVITY,
    ForwardDecisionDimension.STRUCTURAL,
    ForwardDecisionDimension.PATH_RISK,
    ForwardDecisionDimension.PORTFOLIO_CONTEXT,
    ForwardDecisionDimension.CALIBRATION,
}
_ASSET_APPLICABILITY: dict[CandidateAssetClass, frozenset[ForwardDecisionDimension]] = {
    CandidateAssetClass.US_EQUITY: frozenset(_BASE | {ForwardDecisionDimension.FUNDAMENTALS, ForwardDecisionDimension.EARNINGS, ForwardDecisionDimension.CORPORATE_ACTIONS, ForwardDecisionDimension.ALTERNATIVE_DATA}),
    CandidateAssetClass.INTERNATIONAL_EQUITY: frozenset(_BASE | {ForwardDecisionDimension.FUNDAMENTALS, ForwardDecisionDimension.EARNINGS, ForwardDecisionDimension.CORPORATE_ACTIONS, ForwardDecisionDimension.ALTERNATIVE_DATA}),
    CandidateAssetClass.US_ETF: frozenset(_BASE | {ForwardDecisionDimension.FUNDAMENTALS}),
    CandidateAssetClass.FIXED_INCOME: frozenset(_BASE | {ForwardDecisionDimension.FUNDAMENTALS, ForwardDecisionDimension.CORPORATE_ACTIONS}),
    CandidateAssetClass.COMMODITY: frozenset(_BASE | {ForwardDecisionDimension.ALTERNATIVE_DATA}),
    CandidateAssetClass.FX: frozenset(_BASE),
    CandidateAssetClass.CRYPTO: frozenset(_BASE | {ForwardDecisionDimension.ALTERNATIVE_DATA}),
    CandidateAssetClass.REAL_ESTATE: frozenset(_BASE | {ForwardDecisionDimension.FUNDAMENTALS, ForwardDecisionDimension.ALTERNATIVE_DATA}),
    CandidateAssetClass.FUTURE: frozenset(_BASE | {ForwardDecisionDimension.ALTERNATIVE_DATA}),
    CandidateAssetClass.OPTION: frozenset(_BASE),
    CandidateAssetClass.VOLATILITY: frozenset(_BASE),
    CandidateAssetClass.ALTERNATIVE: frozenset(_BASE | {ForwardDecisionDimension.ALTERNATIVE_DATA}),
    CandidateAssetClass.CASH_EQUIVALENT: frozenset({ForwardDecisionDimension.REGIME, ForwardDecisionDimension.EXPECTATIONS, ForwardDecisionDimension.CROSS_ASSET, ForwardDecisionDimension.PATH_RISK, ForwardDecisionDimension.PORTFOLIO_CONTEXT, ForwardDecisionDimension.CALIBRATION}),
    CandidateAssetClass.OTHER: frozenset(_BASE),
}


def applicable_dimensions(asset_class: CandidateAssetClass) -> frozenset[ForwardDecisionDimension]:
    if not isinstance(asset_class, CandidateAssetClass):
        raise TypeError("asset_class must be CandidateAssetClass")
    return _ASSET_APPLICABILITY[asset_class]


_ROLE_DIMENSIONS: dict[SpecialistRole, frozenset[ForwardDecisionDimension]] = {
    SpecialistRole.MACRO_ECONOMIC: frozenset({ForwardDecisionDimension.REGIME, ForwardDecisionDimension.EXPECTATIONS, ForwardDecisionDimension.CATALYSTS, ForwardDecisionDimension.CROSS_ASSET, ForwardDecisionDimension.STRUCTURAL}),
    SpecialistRole.MARKET: frozenset({ForwardDecisionDimension.EXPECTATIONS, ForwardDecisionDimension.CATALYSTS, ForwardDecisionDimension.DERIVATIVES, ForwardDecisionDimension.POSITIONING, ForwardDecisionDimension.CROSS_ASSET, ForwardDecisionDimension.MICROSTRUCTURE, ForwardDecisionDimension.REFLEXIVITY}),
    SpecialistRole.CROSS_ASSET_FORECAST: frozenset(ForwardDecisionDimension),
    SpecialistRole.FUNDAMENTAL_VALUATION: frozenset({ForwardDecisionDimension.FUNDAMENTALS, ForwardDecisionDimension.EXPECTATIONS, ForwardDecisionDimension.CATALYSTS, ForwardDecisionDimension.EARNINGS, ForwardDecisionDimension.STRUCTURAL, ForwardDecisionDimension.CORPORATE_ACTIONS, ForwardDecisionDimension.ALTERNATIVE_DATA}),
    SpecialistRole.PORTFOLIO_RISK: frozenset({ForwardDecisionDimension.CATALYSTS, ForwardDecisionDimension.DERIVATIVES, ForwardDecisionDimension.POSITIONING, ForwardDecisionDimension.MICROSTRUCTURE, ForwardDecisionDimension.REFLEXIVITY, ForwardDecisionDimension.PATH_RISK, ForwardDecisionDimension.PORTFOLIO_CONTEXT}),
    SpecialistRole.EVIDENCE_GOVERNANCE: frozenset(ForwardDecisionDimension),
}


@dataclass(frozen=True, slots=True)
class ForwardDecisionContext:
    identifier: str
    candidate_identifier: str
    as_of: datetime
    asset_class: CandidateAssetClass
    dimensions: tuple[ForwardDimensionAssessment, ...]
    catalysts: tuple[CatalystEvent, ...] = ()
    return_distribution: ReturnDistribution | None = None
    timing: DecisionTiming | None = None
    thesis_monitor: ThesisMonitor | None = None
    event_cluster_window_hours: int = 72
    schema_version: str = "forward-decision-intelligence.v2"
    advisory_only: bool = True

    def __post_init__(self) -> None:
        for name in ("identifier", "candidate_identifier", "schema_version"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        if self.advisory_only is not True:
            raise ValueError("forward decision intelligence must remain advisory_only")
        if not isinstance(self.dimensions, tuple) or not all(isinstance(item, ForwardDimensionAssessment) for item in self.dimensions):
            raise TypeError("dimensions must contain ForwardDimensionAssessment values")
        ids = tuple(item.dimension for item in self.dimensions)
        if len(ids) != len(set(ids)):
            raise ValueError("forward decision dimensions must be unique")
        expected = applicable_dimensions(self.asset_class)
        represented = set(ids)
        if represented != set(ForwardDecisionDimension):
            missing = sorted(item.value for item in set(ForwardDecisionDimension) - represented)
            extra = sorted(item.value for item in represented - set(ForwardDecisionDimension))
            raise ValueError(f"forward decision context must classify every dimension: missing={missing} extra={extra}")
        for item in self.dimensions:
            should_apply = item.dimension in expected
            if not should_apply and item.availability is not EvidenceAvailability.NOT_APPLICABLE:
                raise ValueError(f"{item.dimension.value} must be not_applicable for {self.asset_class.value}")
            if should_apply and item.availability is EvidenceAvailability.NOT_APPLICABLE:
                raise ValueError(f"{item.dimension.value} is applicable to {self.asset_class.value}")
        if not isinstance(self.catalysts, tuple) or not all(isinstance(item, CatalystEvent) for item in self.catalysts):
            raise TypeError("catalysts must contain CatalystEvent values")
        catalyst_ids = tuple(item.identifier for item in self.catalysts)
        if len(catalyst_ids) != len(set(catalyst_ids)):
            raise ValueError("catalyst identifiers must be unique")
        if any(item.scheduled_at < self.as_of for item in self.catalysts):
            raise ValueError("forward catalysts cannot be scheduled before context as_of")
        if self.return_distribution is not None and not isinstance(self.return_distribution, ReturnDistribution):
            raise TypeError("return_distribution must be ReturnDistribution or None")
        if self.timing is not None:
            if not isinstance(self.timing, DecisionTiming):
                raise TypeError("timing must be DecisionTiming or None")
            if self.timing.next_reassessment_at is not None and self.timing.next_reassessment_at < self.as_of:
                raise ValueError("next reassessment cannot precede context as_of")
        if self.thesis_monitor is not None and not isinstance(self.thesis_monitor, ThesisMonitor):
            raise TypeError("thesis_monitor must be ThesisMonitor or None")
        if isinstance(self.event_cluster_window_hours, bool) or not isinstance(self.event_cluster_window_hours, int) or self.event_cluster_window_hours <= 0:
            raise ValueError("event_cluster_window_hours must be a positive integer")

    @property
    def evidence_identifiers(self) -> tuple[str, ...]:
        values = [identifier for item in self.dimensions for identifier in item.evidence_identifiers]
        values.extend(identifier for event in self.catalysts for identifier in event.evidence_identifiers)
        if self.return_distribution is not None:
            values.extend(self.return_distribution.evidence_identifiers)
        return tuple(dict.fromkeys(values))

    @property
    def missing_applicable_dimensions(self) -> tuple[ForwardDecisionDimension, ...]:
        return tuple(item.dimension for item in self.dimensions if item.availability is EvidenceAvailability.UNAVAILABLE)

    @property
    def evidence_completeness(self) -> float:
        applicable = [item for item in self.dimensions if item.availability is not EvidenceAvailability.NOT_APPLICABLE]
        if not applicable:
            return 1.0
        score = sum(1.0 if item.availability is EvidenceAvailability.AVAILABLE else 0.5 if item.availability is EvidenceAvailability.PARTIAL else 0.0 for item in applicable)
        return round(score / len(applicable), 8)

    @property
    def event_clusters(self) -> tuple[tuple[str, ...], ...]:
        if len(self.catalysts) < 2:
            return ()
        ordered = sorted(self.catalysts, key=lambda item: item.scheduled_at)
        window = timedelta(hours=self.event_cluster_window_hours)
        clusters: list[tuple[str, ...]] = []
        current = [ordered[0]]
        for event in ordered[1:]:
            if event.scheduled_at - current[-1].scheduled_at <= window:
                current.append(event)
            else:
                if len(current) > 1:
                    clusters.append(tuple(item.identifier for item in current))
                current = [event]
        if len(current) > 1:
            clusters.append(tuple(item.identifier for item in current))
        return tuple(clusters)

    def enrich_analysis(self, analysis: SpecialistAnalysis) -> SpecialistAnalysis:
        relevant = _ROLE_DIMENSIONS[analysis.role]
        usable = tuple(item for item in self.dimensions if item.dimension in relevant and item.is_usable)
        missing = tuple(item for item in self.dimensions if item.dimension in relevant and item.availability is EvidenceAvailability.UNAVAILABLE)
        additions: list[str] = []
        if usable:
            additions.append("Forward Decision Intelligence v2 considered " + ", ".join(item.dimension.value for item in usable) + ".")
        if self.event_clusters and analysis.role in {SpecialistRole.MARKET, SpecialistRole.CROSS_ASSET_FORECAST, SpecialistRole.PORTFOLIO_RISK}:
            additions.append(f" Event-cluster risk: {len(self.event_clusters)} overlapping catalyst cluster(s).")
        if self.return_distribution is not None and analysis.role in {SpecialistRole.CROSS_ASSET_FORECAST, SpecialistRole.PORTFOLIO_RISK}:
            additions.append(f" Distribution evidence: {self.return_distribution.probability_beat_cash:.0%} probability of beating cash and {self.return_distribution.expected_max_drawdown:.1%} expected maximum drawdown.")
        if self.timing is not None and analysis.role in {SpecialistRole.MARKET, SpecialistRole.CROSS_ASSET_FORECAST, SpecialistRole.PORTFOLIO_RISK}:
            additions.append(f" Timing posture is {self.timing.posture.value}; this is advisory and cannot authorize a trade.")
        limitations = list(analysis.limitations)
        if missing:
            limitations.append("Forward evidence unavailable for applicable dimensions: " + ", ".join(item.dimension.value for item in missing))
        limitations.append("Forward Decision Intelligence v2 is advisory evidence only; it cannot authorize capital or weaken CIO/construction thresholds")
        return replace(
            analysis,
            conclusion=analysis.conclusion + (" " + "".join(additions) if additions else ""),
            supporting_evidence=tuple(dict.fromkeys(analysis.supporting_evidence + tuple(value for item in usable for value in item.evidence))),
            contradictory_evidence=tuple(dict.fromkeys(analysis.contradictory_evidence + tuple(value for item in usable for value in item.contradictory_evidence))),
            critical_assumptions=tuple(dict.fromkeys(analysis.critical_assumptions + tuple(value for item in usable for value in item.assumptions))),
            risks=tuple(dict.fromkeys(analysis.risks + tuple(value for item in usable for value in item.risks) + tuple("Upcoming catalyst: " + event.event_type for event in self.catalysts if event.scheduled_at >= self.as_of))),
            change_conditions=tuple(dict.fromkeys(analysis.change_conditions + tuple(value for item in usable for value in item.change_conditions) + (() if self.thesis_monitor is None else self.thesis_monitor.invalidation_conditions))),
            limitations=tuple(dict.fromkeys(limitations)),
            evidence_origin_identifiers=tuple(dict.fromkeys(analysis.evidence_origin_identifiers + tuple(value for item in usable for value in item.evidence_identifiers) + tuple(value for event in self.catalysts for value in event.evidence_identifiers) + (() if self.return_distribution is None else self.return_distribution.evidence_identifiers))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "candidate_identifier": self.candidate_identifier,
            "as_of": self.as_of.isoformat(),
            "asset_class": self.asset_class.value,
            "dimensions": [item.to_dict() for item in self.dimensions],
            "catalysts": [item.to_dict() for item in self.catalysts],
            "return_distribution": None if self.return_distribution is None else self.return_distribution.to_dict(),
            "timing": None if self.timing is None else self.timing.to_dict(),
            "thesis_monitor": None if self.thesis_monitor is None else self.thesis_monitor.to_dict(),
            "event_cluster_window_hours": self.event_cluster_window_hours,
            "schema_version": self.schema_version,
            "advisory_only": self.advisory_only,
            "evidence_completeness": self.evidence_completeness,
            "missing_applicable_dimensions": [item.value for item in self.missing_applicable_dimensions],
            "event_clusters": [list(item) for item in self.event_clusters],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ForwardDecisionContext":
        distribution = payload.get("return_distribution")
        timing = payload.get("timing")
        monitor = payload.get("thesis_monitor")
        return cls(
            identifier=str(payload["identifier"]),
            candidate_identifier=str(payload["candidate_identifier"]),
            as_of=datetime.fromisoformat(str(payload["as_of"])),
            asset_class=CandidateAssetClass(str(payload["asset_class"])),
            dimensions=tuple(ForwardDimensionAssessment.from_dict(item) for item in payload["dimensions"]),
            catalysts=tuple(CatalystEvent.from_dict(item) for item in payload.get("catalysts", ())),
            return_distribution=None if distribution is None else ReturnDistribution.from_dict(distribution),
            timing=None if timing is None else DecisionTiming.from_dict(timing),
            thesis_monitor=None if monitor is None else ThesisMonitor.from_dict(monitor),
            event_cluster_window_hours=int(payload.get("event_cluster_window_hours", 72)),
            schema_version=str(payload.get("schema_version", "forward-decision-intelligence.v2")),
            advisory_only=bool(payload.get("advisory_only", True)),
        )


def build_forward_decision_context(
    *,
    identifier: str,
    candidate_identifier: str,
    as_of: datetime,
    asset_class: CandidateAssetClass,
    assessments: tuple[ForwardDimensionAssessment, ...] = (),
    catalysts: tuple[CatalystEvent, ...] = (),
    return_distribution: ReturnDistribution | None = None,
    timing: DecisionTiming | None = None,
    thesis_monitor: ThesisMonitor | None = None,
) -> ForwardDecisionContext:
    """Build a complete packet while truthfully classifying absent evidence.

    Callers provide only domains for which governed evidence exists.  Every omitted
    applicable domain is marked unavailable; irrelevant domains are not_applicable.
    This is intentionally fail-closed and does not synthesize missing provider data.
    """

    if not isinstance(assessments, tuple):
        raise TypeError("assessments must be a tuple")
    supplied = {item.dimension: item for item in assessments}
    if len(supplied) != len(assessments):
        raise ValueError("assessments cannot contain duplicate dimensions")
    applicable = applicable_dimensions(asset_class)
    complete: list[ForwardDimensionAssessment] = []
    for dimension in ForwardDecisionDimension:
        if dimension in supplied:
            complete.append(supplied[dimension])
        elif dimension in applicable:
            complete.append(
                ForwardDimensionAssessment(
                    dimension=dimension,
                    availability=EvidenceAvailability.UNAVAILABLE,
                    summary=f"No governed {dimension.value} evidence was available at the knowledge cutoff",
                    confidence=0.0,
                )
            )
        else:
            complete.append(
                ForwardDimensionAssessment(
                    dimension=dimension,
                    availability=EvidenceAvailability.NOT_APPLICABLE,
                    summary=f"{dimension.value} is not required for {asset_class.value}",
                    confidence=0.0,
                )
            )
    return ForwardDecisionContext(
        identifier=identifier,
        candidate_identifier=candidate_identifier,
        as_of=as_of,
        asset_class=asset_class,
        dimensions=tuple(complete),
        catalysts=catalysts,
        return_distribution=return_distribution,
        timing=timing,
        thesis_monitor=thesis_monitor,
    )


__all__ = [
    "CatalystEvent",
    "DecisionTiming",
    "DecisionTimingPosture",
    "EvidenceAvailability",
    "EventScenario",
    "ForwardDecisionContext",
    "ForwardDecisionDimension",
    "ForwardDimensionAssessment",
    "ReturnDistribution",
    "ThesisMonitor",
    "applicable_dimensions",
    "build_forward_decision_context",
]
