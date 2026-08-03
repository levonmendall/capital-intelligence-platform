"""Governed, general-purpose event-to-market transmission evidence.

The engine converts a quality-gated headline into one or more causal drivers,
combines their cross-asset implications, and tests those hypotheses against
point-in-time market observations. It covers the major recurring headline
families while routing novel material events to explicit causal review instead
of silently ignoring them.

The output is supporting evidence only. It cannot create candidates, mutate an
expected return, issue a CIO action, construct a portfolio, submit an order, or
enable real-money trading.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from data.decision_information import (
    CurrentEventPortfolioAnalyzer,
    DecisionInformationRecord,
    InformationQualityState,
    PortfolioInformationImpact,
)


def _text(value: object, *, field_name: str = "value") -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _ratio(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    number = float(value)
    if not isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field_name} must be finite and between zero and one")
    return round(number, 8)


def _bounded(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    number = float(value)
    if not isfinite(number) or not -1.0 <= number <= 1.0:
        raise ValueError(f"{field_name} must be finite and between -1 and one")
    return round(number, 8)


def _positive(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    number = float(value)
    if not isfinite(number) or number <= 0.0:
        raise ValueError(f"{field_name} must be finite and positive")
    return round(number, 8)


def _texts(value: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} must contain at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _record_text(record: DecisionInformationRecord) -> str:
    return " ".join(
        (
            record.topic,
            record.summary,
            *record.entities,
            *record.geographies,
            *record.sectors,
            *record.tags,
            *(channel.value for channel in record.impact_channels),
        )
    ).lower()


def _contains(text: str, phrases: Sequence[str]) -> bool:
    return any(phrase in text for phrase in phrases)


class EventMarketDomain(str, Enum):
    MACRO_GROWTH = "macro_growth"
    INFLATION = "inflation"
    LABOR = "labor"
    MONETARY_POLICY = "monetary_policy"
    FISCAL_POLICY = "fiscal_policy"
    GEOPOLITICS = "geopolitics"
    TRADE_SANCTIONS = "trade_sanctions"
    COMMODITY_SUPPLY = "commodity_supply"
    CORPORATE = "corporate"
    CREDIT_FINANCIAL_STABILITY = "credit_financial_stability"
    REGULATION_LEGAL = "regulation_legal"
    OPERATIONAL_CYBER = "operational_cyber"
    WEATHER_DISASTER = "weather_disaster"
    PUBLIC_HEALTH = "public_health"
    POLITICAL_ELECTION = "political_election"
    MARKET_LIQUIDITY = "market_liquidity"
    CURRENCY = "currency"
    TECHNOLOGY_INNOVATION = "technology_innovation"
    UNKNOWN = "unknown"


class EventMarketState(str, Enum):
    GEOPOLITICAL_ESCALATION = "geopolitical_escalation"
    GEOPOLITICAL_DEESCALATION = "geopolitical_deescalation"
    SUPPLY_TIGHTENING = "supply_tightening"
    SUPPLY_EASING = "supply_easing"
    DEMAND_STRENGTHENING = "demand_strengthening"
    DEMAND_WEAKENING = "demand_weakening"
    INFLATION_ACCELERATION = "inflation_acceleration"
    INFLATION_DECELERATION = "inflation_deceleration"
    LABOR_TIGHTENING = "labor_tightening"
    LABOR_WEAKENING = "labor_weakening"
    POLICY_TIGHTENING = "policy_tightening"
    POLICY_EASING = "policy_easing"
    FISCAL_EXPANSION = "fiscal_expansion"
    FISCAL_CONTRACTION = "fiscal_contraction"
    TRADE_RESTRICTION = "trade_restriction"
    TRADE_EASING = "trade_easing"
    CORPORATE_POSITIVE = "corporate_positive"
    CORPORATE_NEGATIVE = "corporate_negative"
    CREDIT_STRESS = "credit_stress"
    CREDIT_RELIEF = "credit_relief"
    REGULATORY_TIGHTENING = "regulatory_tightening"
    REGULATORY_RELIEF = "regulatory_relief"
    OPERATIONAL_DISRUPTION = "operational_disruption"
    OPERATIONAL_RESTORATION = "operational_restoration"
    DISASTER_ESCALATION = "disaster_escalation"
    DISASTER_RECOVERY = "disaster_recovery"
    HEALTH_ESCALATION = "health_escalation"
    HEALTH_IMPROVEMENT = "health_improvement"
    POLITICAL_UNCERTAINTY = "political_uncertainty"
    POLITICAL_RESOLUTION = "political_resolution"
    LIQUIDITY_STRESS = "liquidity_stress"
    LIQUIDITY_RELIEF = "liquidity_relief"
    CURRENCY_DEPRECIATION = "currency_depreciation"
    CURRENCY_APPRECIATION = "currency_appreciation"
    TECHNOLOGY_BREAKTHROUGH = "technology_breakthrough"
    UNRESOLVED_MAJOR_EVENT = "unresolved_major_event"
    UNKNOWN = "unknown"


class EventCoverageState(str, Enum):
    MAPPED = "mapped"
    PARTIAL = "partial"
    UNRESOLVED = "unresolved"


class TransmissionDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NEUTRAL = "neutral"

    @property
    def sign(self) -> float:
        return {
            TransmissionDirection.POSITIVE: 1.0,
            TransmissionDirection.NEGATIVE: -1.0,
            TransmissionDirection.MIXED: 0.0,
            TransmissionDirection.NEUTRAL: 0.0,
        }[self]


@dataclass(frozen=True, slots=True)
class MarketObservation:
    """One contemporaneous market move used only as confirmation evidence."""

    identifier: str
    exposure_identifier: str
    observed_at: datetime
    return_change: float
    evidence_identifiers: tuple[str, ...]
    source: str = "market"
    schema_version: str = "event-market-observation.v2"

    def __post_init__(self) -> None:
        for field_name in ("identifier", "exposure_identifier", "source", "schema_version"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "observed_at",
            _aware(self.observed_at, field_name="observed_at"),
        )
        object.__setattr__(
            self,
            "return_change",
            _bounded(self.return_change, field_name="return_change"),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1),
        )


@dataclass(frozen=True, slots=True)
class RuleTransmission:
    target_identifier: str
    direction: TransmissionDirection
    magnitude: float
    mechanism: str
    horizon: str

    def __post_init__(self) -> None:
        for field_name in ("target_identifier", "mechanism", "horizon"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.direction, TransmissionDirection):
            raise TypeError("direction must be TransmissionDirection")
        object.__setattr__(self, "magnitude", _ratio(self.magnitude, field_name="magnitude"))


@dataclass(frozen=True, slots=True)
class EventRule:
    identifier: str
    domain: EventMarketDomain
    state: EventMarketState
    phrases: tuple[str, ...]
    context_phrases: tuple[str, ...]
    excluded_phrases: tuple[str, ...]
    channels: tuple[str, ...]
    priority: float
    causal_chain: tuple[str, ...]
    transmissions: tuple[RuleTransmission, ...]
    alternatives: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        if not isinstance(self.domain, EventMarketDomain):
            raise TypeError("domain must be EventMarketDomain")
        if not isinstance(self.state, EventMarketState):
            raise TypeError("state must be EventMarketState")
        for field_name, minimum in (
            ("phrases", 1),
            ("context_phrases", 0),
            ("excluded_phrases", 0),
            ("channels", 0),
            ("causal_chain", 1),
            ("alternatives", 1),
        ):
            object.__setattr__(
                self,
                field_name,
                _texts(getattr(self, field_name), field_name=field_name, minimum=minimum),
            )
        object.__setattr__(self, "priority", _ratio(self.priority, field_name="priority"))
        if not isinstance(self.transmissions, tuple) or not all(
            isinstance(item, RuleTransmission) for item in self.transmissions
        ):
            raise TypeError("transmissions must contain RuleTransmission values")
        if not self.transmissions:
            raise ValueError("transmissions cannot be empty")

    def match_score(self, record: DecisionInformationRecord, text: str) -> float:
        if self.excluded_phrases and _contains(text, self.excluded_phrases):
            return 0.0
        phrase_hits = sum(1 for phrase in self.phrases if phrase in text)
        if phrase_hits == 0:
            return 0.0
        if self.context_phrases and not _contains(text, self.context_phrases):
            return 0.0
        record_channels = {channel.value for channel in record.impact_channels}
        channel_overlap = len(record_channels.intersection(self.channels))
        phrase_score = min(1.0, phrase_hits / max(1.0, min(3.0, len(self.phrases) / 3.0)))
        channel_score = min(1.0, channel_overlap / 2.0) if self.channels else 0.5
        return round(min(1.0, 0.55 * phrase_score + 0.25 * channel_score + 0.20 * self.priority), 8)


@dataclass(frozen=True, slots=True)
class EventDriver:
    rule_identifier: str
    domain: EventMarketDomain
    state: EventMarketState
    confidence: float
    causal_chain: tuple[str, ...]
    transmissions: tuple[RuleTransmission, ...]
    alternatives: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "rule_identifier",
            _text(self.rule_identifier, field_name="rule_identifier"),
        )
        if not isinstance(self.domain, EventMarketDomain):
            raise TypeError("domain must be EventMarketDomain")
        if not isinstance(self.state, EventMarketState):
            raise TypeError("state must be EventMarketState")
        object.__setattr__(self, "confidence", _ratio(self.confidence, field_name="confidence"))
        object.__setattr__(
            self,
            "causal_chain",
            _texts(self.causal_chain, field_name="causal_chain", minimum=1),
        )
        if not isinstance(self.transmissions, tuple) or not all(
            isinstance(item, RuleTransmission) for item in self.transmissions
        ):
            raise TypeError("transmissions must contain RuleTransmission values")
        object.__setattr__(
            self,
            "alternatives",
            _texts(self.alternatives, field_name="alternatives", minimum=1),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_identifier": self.rule_identifier,
            "domain": self.domain.value,
            "state": self.state.value,
            "confidence": self.confidence,
            "causal_chain": list(self.causal_chain),
            "transmissions": [
                {
                    "target_identifier": item.target_identifier,
                    "direction": item.direction.value,
                    "magnitude": item.magnitude,
                    "mechanism": item.mechanism,
                    "horizon": item.horizon,
                }
                for item in self.transmissions
            ],
            "alternatives": list(self.alternatives),
        }


@dataclass(frozen=True, slots=True)
class MarketTransmission:
    target_identifier: str
    direction: TransmissionDirection
    magnitude: float
    confidence: float
    mechanism: str
    horizon: str
    evidence_identifiers: tuple[str, ...]
    contributing_driver_identifiers: tuple[str, ...]
    schema_version: str = "event-market-transmission.v2"

    def __post_init__(self) -> None:
        for field_name in ("target_identifier", "mechanism", "horizon", "schema_version"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.direction, TransmissionDirection):
            raise TypeError("direction must be TransmissionDirection")
        object.__setattr__(self, "magnitude", _ratio(self.magnitude, field_name="magnitude"))
        object.__setattr__(self, "confidence", _ratio(self.confidence, field_name="confidence"))
        for field_name in ("evidence_identifiers", "contributing_driver_identifiers"):
            object.__setattr__(
                self,
                field_name,
                _texts(getattr(self, field_name), field_name=field_name, minimum=1),
            )

    @property
    def directional_score(self) -> float:
        return round(self.direction.sign * self.magnitude * self.confidence, 8)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_identifier": self.target_identifier,
            "direction": self.direction.value,
            "magnitude": self.magnitude,
            "confidence": self.confidence,
            "mechanism": self.mechanism,
            "horizon": self.horizon,
            "evidence_identifiers": list(self.evidence_identifiers),
            "contributing_driver_identifiers": list(self.contributing_driver_identifiers),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class EventMarketPolicy:
    version: str = "event-to-market.v2-general-headlines"
    minimum_record_evidence_strength: float = 0.20
    minimum_cluster_quality: float = 0.50
    minimum_market_confirmation: float = 0.20
    minimum_confirmation_coverage: float = 0.15
    minimum_assessment_confidence: float = 0.45
    minimum_rule_score: float = 0.40
    minimum_major_headline_materiality: float = 0.65
    minimum_observed_move: float = 0.001
    full_confirmation_move: float = 0.03
    mixed_direction_conflict_ratio: float = 0.30

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _text(self.version, field_name="version"))
        for field_name in (
            "minimum_record_evidence_strength",
            "minimum_cluster_quality",
            "minimum_market_confirmation",
            "minimum_confirmation_coverage",
            "minimum_assessment_confidence",
            "minimum_rule_score",
            "minimum_major_headline_materiality",
            "mixed_direction_conflict_ratio",
        ):
            object.__setattr__(
                self,
                field_name,
                _ratio(getattr(self, field_name), field_name=field_name),
            )
        for field_name in ("minimum_observed_move", "full_confirmation_move"):
            object.__setattr__(
                self,
                field_name,
                _positive(getattr(self, field_name), field_name=field_name),
            )
        if self.full_confirmation_move < self.minimum_observed_move:
            raise ValueError("full_confirmation_move cannot be below minimum_observed_move")


@dataclass(frozen=True, slots=True)
class EventMarketAssessment:
    identifier: str
    information_identifier: str
    event_cluster_identifier: str
    assessed_at: datetime
    state: EventMarketState
    domains: tuple[EventMarketDomain, ...]
    coverage_state: EventCoverageState
    drivers: tuple[EventDriver, ...]
    causal_chain: tuple[str, ...]
    transmissions: tuple[MarketTransmission, ...]
    market_confirmation: float
    confirmation_coverage: float
    confidence: float
    major_headline: bool
    requires_causal_review: bool
    contradictory_evidence: tuple[str, ...]
    alternative_explanations: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    affected_portfolio_instruments: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    eligible_for_cio_context: bool
    policy_version: str
    schema_version: str = "event-market-assessment.v2"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "information_identifier",
            "event_cluster_identifier",
            "policy_version",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(self, "assessed_at", _aware(self.assessed_at, field_name="assessed_at"))
        if not isinstance(self.state, EventMarketState):
            raise TypeError("state must be EventMarketState")
        if not isinstance(self.coverage_state, EventCoverageState):
            raise TypeError("coverage_state must be EventCoverageState")
        if not isinstance(self.domains, tuple) or not all(
            isinstance(item, EventMarketDomain) for item in self.domains
        ):
            raise TypeError("domains must contain EventMarketDomain values")
        if not self.domains:
            raise ValueError("domains cannot be empty")
        if len(self.domains) != len(set(self.domains)):
            raise ValueError("domains cannot contain duplicates")
        if not isinstance(self.drivers, tuple) or not all(
            isinstance(item, EventDriver) for item in self.drivers
        ):
            raise TypeError("drivers must contain EventDriver values")
        if not isinstance(self.transmissions, tuple) or not all(
            isinstance(item, MarketTransmission) for item in self.transmissions
        ):
            raise TypeError("transmissions must contain MarketTransmission values")
        if not self.transmissions:
            raise ValueError("transmissions cannot be empty")
        targets = tuple(item.target_identifier for item in self.transmissions)
        if len(targets) != len(set(targets)):
            raise ValueError("transmission targets must be unique")
        for field_name, minimum in (
            ("causal_chain", 1),
            ("contradictory_evidence", 0),
            ("alternative_explanations", 1),
            ("unresolved_questions", 0),
            ("affected_portfolio_instruments", 0),
            ("evidence_identifiers", 1),
        ):
            object.__setattr__(
                self,
                field_name,
                _texts(getattr(self, field_name), field_name=field_name, minimum=minimum),
            )
        for field_name in ("market_confirmation", "confirmation_coverage", "confidence"):
            object.__setattr__(
                self,
                field_name,
                _ratio(getattr(self, field_name), field_name=field_name),
            )
        for field_name in ("major_headline", "requires_causal_review", "eligible_for_cio_context"):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")

    def transmission(self, target_identifier: str) -> MarketTransmission | None:
        target = _text(target_identifier, field_name="target_identifier")
        return next((item for item in self.transmissions if item.target_identifier == target), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "information_identifier": self.information_identifier,
            "event_cluster_identifier": self.event_cluster_identifier,
            "assessed_at": self.assessed_at.isoformat(),
            "state": self.state.value,
            "domains": [item.value for item in self.domains],
            "coverage_state": self.coverage_state.value,
            "drivers": [item.to_dict() for item in self.drivers],
            "causal_chain": list(self.causal_chain),
            "transmissions": [item.to_dict() for item in self.transmissions],
            "market_confirmation": self.market_confirmation,
            "confirmation_coverage": self.confirmation_coverage,
            "confidence": self.confidence,
            "major_headline": self.major_headline,
            "requires_causal_review": self.requires_causal_review,
            "contradictory_evidence": list(self.contradictory_evidence),
            "alternative_explanations": list(self.alternative_explanations),
            "unresolved_questions": list(self.unresolved_questions),
            "affected_portfolio_instruments": list(self.affected_portfolio_instruments),
            "evidence_identifiers": list(self.evidence_identifiers),
            "eligible_for_cio_context": self.eligible_for_cio_context,
            "policy_version": self.policy_version,
            "schema_version": self.schema_version,
            "authorizes_candidate_creation": False,
            "authorizes_expected_return_change": False,
            "authorizes_portfolio_change": False,
            "real_money_authorized": False,
        }


@dataclass(frozen=True, slots=True)
class CandidateEventMarketEvidence:
    candidate_identifier: str
    event_market_assessment_identifier: str
    as_of: datetime
    directional_score: float
    transmissions: tuple[str, ...]
    domains: tuple[EventMarketDomain, ...]
    evidence_identifiers: tuple[str, ...]
    confidence: float
    eligible_for_specialist_context: bool
    schema_version: str = "candidate-event-market-evidence.v2"

    def __post_init__(self) -> None:
        for field_name in ("candidate_identifier", "event_market_assessment_identifier", "schema_version"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(self, "as_of", _aware(self.as_of, field_name="as_of"))
        object.__setattr__(
            self,
            "directional_score",
            _bounded(self.directional_score, field_name="directional_score"),
        )
        object.__setattr__(
            self,
            "transmissions",
            _texts(self.transmissions, field_name="transmissions", minimum=1),
        )
        if not isinstance(self.domains, tuple) or not all(
            isinstance(item, EventMarketDomain) for item in self.domains
        ):
            raise TypeError("domains must contain EventMarketDomain values")
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1),
        )
        object.__setattr__(self, "confidence", _ratio(self.confidence, field_name="confidence"))
        if not isinstance(self.eligible_for_specialist_context, bool):
            raise TypeError("eligible_for_specialist_context must be a bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_identifier": self.candidate_identifier,
            "event_market_assessment_identifier": self.event_market_assessment_identifier,
            "as_of": self.as_of.isoformat(),
            "directional_score": self.directional_score,
            "transmissions": list(self.transmissions),
            "domains": [item.value for item in self.domains],
            "evidence_identifiers": list(self.evidence_identifiers),
            "confidence": self.confidence,
            "eligible_for_specialist_context": self.eligible_for_specialist_context,
            "schema_version": self.schema_version,
            "authorizes_expected_return_change": False,
            "authorizes_portfolio_change": False,
            "real_money_authorized": False,
        }


@dataclass(frozen=True, slots=True)
class GovernedEventMarketResult:
    assessment: EventMarketAssessment
    portfolio_impact: PortfolioInformationImpact
    candidate_evidence: tuple[CandidateEventMarketEvidence, ...]
    requires_cio_review: bool
    schema_version: str = "governed-event-market-result.v2"

    def __post_init__(self) -> None:
        if not isinstance(self.assessment, EventMarketAssessment):
            raise TypeError("assessment must be EventMarketAssessment")
        if not isinstance(self.portfolio_impact, PortfolioInformationImpact):
            raise TypeError("portfolio_impact must be PortfolioInformationImpact")
        if not isinstance(self.candidate_evidence, tuple) or not all(
            isinstance(item, CandidateEventMarketEvidence) for item in self.candidate_evidence
        ):
            raise TypeError("candidate_evidence must contain CandidateEventMarketEvidence values")
        identifiers = tuple(item.candidate_identifier for item in self.candidate_evidence)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("candidate event-market evidence must be unique")
        if not isinstance(self.requires_cio_review, bool):
            raise TypeError("requires_cio_review must be a bool")
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, field_name="schema_version"),
        )



__all__ = [
    "CandidateEventMarketEvidence", "EventCoverageState", "EventDriver",
    "EventMarketAssessment", "EventMarketDomain", "EventMarketPolicy",
    "EventMarketState", "EventRule", "GovernedEventMarketResult",
    "MarketObservation", "MarketTransmission", "RuleTransmission",
    "TransmissionDirection", "_aware", "_record_text", "_text",
    "_texts", "_unique",
]
