"""Canonical point-in-time contracts for news, events, and alternative information.

A headline is not investment evidence by itself. Records preserve event time,
publication time, availability time, corrections, source identity, licensing,
entity and geography mappings, corroboration, and portfolio-impact lineage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any, Mapping, Protocol


class DecisionInformationError(RuntimeError):
    """Raised when decision information is invalid or unavailable."""


class InformationQualityState(str, Enum):
    LIVE = "live"
    CACHED = "cached"
    STALE = "stale"
    CORRECTED = "corrected"
    DISPUTED = "disputed"
    UNVERIFIED = "unverified"
    FIXTURE = "fixture"
    MISSING = "missing"


class InformationSourceType(str, Enum):
    OFFICIAL = "official"
    REGULATORY = "regulatory"
    ISSUER = "issuer"
    NEWSWIRE = "newswire"
    JOURNALISM = "journalism"
    RESEARCH = "research"
    MARKET = "market"
    ALTERNATIVE = "alternative"
    SOCIAL = "social"
    VALIDATION = "validation"


class PortfolioImpactChannel(str, Enum):
    GROWTH = "growth"
    INFLATION = "inflation"
    POLICY = "policy"
    LIQUIDITY = "liquidity"
    DISCOUNT_RATE = "discount_rate"
    EARNINGS = "earnings"
    CREDIT = "credit"
    SUPPLY = "supply"
    DEMAND = "demand"
    COMMODITY = "commodity"
    CURRENCY = "currency"
    VOLATILITY = "volatility"
    REGULATION = "regulation"
    GEOPOLITICAL = "geopolitical"
    OPERATIONAL = "operational"
    CYBER = "cyber"
    CLIMATE_WEATHER = "climate_weather"
    POSITIONING = "positioning"
    SENTIMENT = "sentiment"
    COUNTERPARTY = "counterparty"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _optional_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name=field_name)


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _texts(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _ratio(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{field_name} must be finite and between zero and one")
    return round(normalized, 8)


@dataclass(frozen=True, slots=True)
class InformationProvenance:
    provider: str
    source_identifier: str
    source_type: InformationSourceType
    retrieved_at: datetime
    license_identifier: str
    usage_rights_identifier: str
    raw_content_hash: str
    quality_state: InformationQualityState
    correction_of_identifier: str | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "provider",
            "source_identifier",
            "license_identifier",
            "usage_rights_identifier",
            "raw_content_hash",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name=field_name))
        if not isinstance(self.source_type, InformationSourceType):
            raise TypeError("source_type must be InformationSourceType")
        if not isinstance(self.quality_state, InformationQualityState):
            raise TypeError("quality_state must be InformationQualityState")
        _aware(self.retrieved_at, field_name="retrieved_at")
        object.__setattr__(
            self,
            "correction_of_identifier",
            _optional_text(self.correction_of_identifier, field_name="correction_of_identifier"),
        )
        object.__setattr__(self, "limitations", _texts(self.limitations, field_name="limitations"))


@dataclass(frozen=True, slots=True)
class DecisionInformationRecord:
    """One immutable fact, event, statement, estimate, or observed signal."""

    identifier: str
    topic: str
    summary: str
    event_at: datetime
    published_at: datetime
    available_at: datetime
    knowledge_cutoff: datetime
    provenance: InformationProvenance
    canonical_event_identifier: str
    entities: tuple[str, ...]
    instruments: tuple[str, ...]
    geographies: tuple[str, ...]
    sectors: tuple[str, ...]
    tags: tuple[str, ...]
    impact_channels: tuple[PortfolioImpactChannel, ...]
    reliability: float
    relevance: float
    materiality: float
    independence: float
    corroborating_source_identifiers: tuple[str, ...] = ()
    supersedes_identifiers: tuple[str, ...] = ()
    schema_version: str = "decision-information-record.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "topic",
            "summary",
            "canonical_event_identifier",
            "schema_version",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name=field_name))
        for field_name in ("event_at", "published_at", "available_at", "knowledge_cutoff"):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.published_at < self.event_at:
            raise ValueError("published_at cannot predate event_at")
        if self.available_at < self.published_at:
            raise ValueError("available_at cannot predate published_at")
        if self.knowledge_cutoff < self.available_at:
            raise ValueError("knowledge_cutoff cannot predate available_at")
        if not isinstance(self.provenance, InformationProvenance):
            raise TypeError("provenance must be InformationProvenance")
        for field_name in (
            "entities",
            "instruments",
            "geographies",
            "sectors",
            "tags",
            "corroborating_source_identifiers",
            "supersedes_identifiers",
        ):
            object.__setattr__(self, field_name, _texts(getattr(self, field_name), field_name=field_name))
        if not isinstance(self.impact_channels, tuple) or not all(
            isinstance(item, PortfolioImpactChannel) for item in self.impact_channels
        ):
            raise TypeError("impact_channels must contain PortfolioImpactChannel values")
        if len(self.impact_channels) != len(set(self.impact_channels)):
            raise ValueError("impact_channels cannot contain duplicates")
        for field_name in ("reliability", "relevance", "materiality", "independence"):
            object.__setattr__(self, field_name, _ratio(getattr(self, field_name), field_name=field_name))

    def available_to(self, decision_time: datetime) -> bool:
        timestamp = _aware(decision_time, field_name="decision_time")
        return self.available_at <= timestamp and self.knowledge_cutoff <= timestamp

    def require_available_to(self, decision_time: datetime) -> None:
        if not self.available_to(decision_time):
            raise DecisionInformationError(
                f"{self.identifier} was not available at the decision boundary"
            )

    @property
    def evidence_strength(self) -> float:
        return round(
            self.reliability
            * self.relevance
            * self.materiality
            * max(self.independence, 0.1),
            8,
        )

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "topic": self.topic,
            "summary": self.summary,
            "event_at": self.event_at.isoformat(),
            "published_at": self.published_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "knowledge_cutoff": self.knowledge_cutoff.isoformat(),
            "canonical_event_identifier": self.canonical_event_identifier,
            "entities": list(self.entities),
            "instruments": list(self.instruments),
            "geographies": list(self.geographies),
            "sectors": list(self.sectors),
            "tags": list(self.tags),
            "impact_channels": [item.value for item in self.impact_channels],
            "reliability": self.reliability,
            "relevance": self.relevance,
            "materiality": self.materiality,
            "independence": self.independence,
            "corroborating_source_identifiers": list(self.corroborating_source_identifiers),
            "supersedes_identifiers": list(self.supersedes_identifiers),
            "provenance": {
                "provider": self.provenance.provider,
                "source_identifier": self.provenance.source_identifier,
                "source_type": self.provenance.source_type.value,
                "retrieved_at": self.provenance.retrieved_at.isoformat(),
                "license_identifier": self.provenance.license_identifier,
                "usage_rights_identifier": self.provenance.usage_rights_identifier,
                "raw_content_hash": self.provenance.raw_content_hash,
                "quality_state": self.provenance.quality_state.value,
                "correction_of_identifier": self.provenance.correction_of_identifier,
                "limitations": list(self.provenance.limitations),
            },
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class PortfolioInformationImpact:
    information_identifier: str
    portfolio_identifier: str
    assessed_at: datetime
    affected_instrument_identifiers: tuple[str, ...]
    impact_channels: tuple[PortfolioImpactChannel, ...]
    portfolio_relevance: float
    actionability: float
    market_confirmation: float
    requires_cio_review: bool
    explanation: str
    evidence_identifiers: tuple[str, ...]
    schema_version: str = "portfolio-information-impact.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "information_identifier",
            "portfolio_identifier",
            "explanation",
            "schema_version",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name=field_name))
        _aware(self.assessed_at, field_name="assessed_at")
        object.__setattr__(
            self,
            "affected_instrument_identifiers",
            _texts(self.affected_instrument_identifiers, field_name="affected_instrument_identifiers"),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(self.evidence_identifiers, field_name="evidence_identifiers"),
        )
        if not self.evidence_identifiers:
            raise ValueError("evidence_identifiers cannot be empty")
        if not isinstance(self.impact_channels, tuple) or not all(
            isinstance(item, PortfolioImpactChannel) for item in self.impact_channels
        ):
            raise TypeError("impact_channels must contain PortfolioImpactChannel values")
        for field_name in ("portfolio_relevance", "actionability", "market_confirmation"):
            object.__setattr__(self, field_name, _ratio(getattr(self, field_name), field_name=field_name))
        if not isinstance(self.requires_cio_review, bool):
            raise TypeError("requires_cio_review must be a bool")


class DecisionInformationProvider(Protocol):
    def records(
        self,
        *,
        start_at: datetime,
        as_of: datetime,
        topics: tuple[str, ...] = (),
        entities: tuple[str, ...] = (),
    ) -> tuple[DecisionInformationRecord, ...]: ...


class CurrentEventPortfolioAnalyzer:
    """Fail-closed prioritization of current information for CIO review.

    The analyzer does not infer expected returns or issue trades. It determines
    whether a governed current event is sufficiently reliable, material,
    portfolio-relevant, and market-confirmed to require CIO review.
    """

    def __init__(
        self,
        *,
        minimum_evidence_strength: float = 0.20,
        minimum_portfolio_relevance: float = 0.20,
        minimum_market_confirmation: float = 0.10,
    ) -> None:
        self.minimum_evidence_strength = _ratio(
            minimum_evidence_strength, field_name="minimum_evidence_strength"
        )
        self.minimum_portfolio_relevance = _ratio(
            minimum_portfolio_relevance, field_name="minimum_portfolio_relevance"
        )
        self.minimum_market_confirmation = _ratio(
            minimum_market_confirmation, field_name="minimum_market_confirmation"
        )

    def assess(
        self,
        record: DecisionInformationRecord,
        *,
        portfolio_identifier: str,
        assessed_at: datetime,
        owned_instrument_identifiers: tuple[str, ...],
        market_confirmation: float,
    ) -> PortfolioInformationImpact:
        timestamp = _aware(assessed_at, field_name="assessed_at")
        record.require_available_to(timestamp)
        owned = set(_texts(owned_instrument_identifiers, field_name="owned_instrument_identifiers"))
        directly_affected = tuple(sorted(owned.intersection(record.instruments)))
        portfolio_relevance = 1.0 if directly_affected else record.relevance
        confirmation = _ratio(market_confirmation, field_name="market_confirmation")
        actionability = round(record.evidence_strength * portfolio_relevance * max(confirmation, 0.1), 8)
        requires_review = (
            record.evidence_strength >= self.minimum_evidence_strength
            and portfolio_relevance >= self.minimum_portfolio_relevance
            and confirmation >= self.minimum_market_confirmation
            and record.provenance.quality_state
            not in {InformationQualityState.DISPUTED, InformationQualityState.UNVERIFIED, InformationQualityState.MISSING}
        )
        explanation = (
            "Current information requires CIO review because reliability, materiality, portfolio relevance, and market confirmation meet policy."
            if requires_review
            else "Current information remains monitored because one or more evidence, relevance, or confirmation thresholds are not met."
        )
        return PortfolioInformationImpact(
            information_identifier=record.identifier,
            portfolio_identifier=_text(portfolio_identifier, field_name="portfolio_identifier"),
            assessed_at=timestamp,
            affected_instrument_identifiers=directly_affected,
            impact_channels=record.impact_channels,
            portfolio_relevance=portfolio_relevance,
            actionability=actionability,
            market_confirmation=confirmation,
            requires_cio_review=requires_review,
            explanation=explanation,
            evidence_identifiers=(
                record.identifier,
                record.provenance.source_identifier,
                *record.corroborating_source_identifiers,
            ),
        )


__all__ = [
    "CurrentEventPortfolioAnalyzer",
    "DecisionInformationError",
    "DecisionInformationProvider",
    "DecisionInformationRecord",
    "InformationProvenance",
    "InformationQualityState",
    "InformationSourceType",
    "PortfolioImpactChannel",
    "PortfolioInformationImpact",
]
