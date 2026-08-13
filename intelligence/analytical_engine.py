"""Reusable typed contracts for deterministic analytical engines."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from math import isfinite
from typing import Any


class EngineDirection(str, Enum):
    """Directional conclusion produced by one analytical engine."""

    EXPANDING = "expanding"
    NEUTRAL = "neutral"
    CONTRACTING = "contracting"
    STRESSED = "stressed"
    UNAVAILABLE = "unavailable"


class EngineDataStatus(str, Enum):
    """Honest operating state for an analytical engine result."""

    CURRENT = "current"
    INCOMPLETE = "incomplete"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _strings(values: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not all(
        isinstance(value, str) and value.strip() for value in values
    ):
        raise TypeError(f"{field_name} must contain non-empty strings")
    return tuple(dict.fromkeys(value.strip() for value in values))


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name)


def _optional_count(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an int or None")
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return value


@dataclass(frozen=True, slots=True)
class EngineEvidence:
    """One scored source observation used by an analytical engine."""

    identifier: str
    component: str
    indicator: str
    provider: str
    series_identifier: str
    observation_date: date
    released_at: datetime
    retrieved_at: datetime
    quality_state: str
    signal_score: float
    weighted_contribution: float
    explanation: str
    vintage_date: date | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "component",
            "indicator",
            "provider",
            "series_identifier",
            "quality_state",
            "explanation",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name),
            )
        if isinstance(self.observation_date, datetime) or not isinstance(
            self.observation_date,
            date,
        ):
            raise TypeError("observation_date must be a date")
        _aware(self.released_at, "released_at")
        _aware(self.retrieved_at, "retrieved_at")
        if self.released_at > self.retrieved_at:
            raise ValueError("released_at cannot be later than retrieved_at")
        if self.vintage_date is not None:
            if isinstance(self.vintage_date, datetime) or not isinstance(
                self.vintage_date,
                date,
            ):
                raise TypeError("vintage_date must be a date or None")
        for field_name in ("signal_score", "weighted_contribution"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be numeric")
            normalized = float(value)
            if not isfinite(normalized):
                raise ValueError(f"{field_name} must be finite")
            if not -1.0 <= normalized <= 1.0:
                raise ValueError(f"{field_name} must be between -1.0 and 1.0")
            object.__setattr__(self, field_name, normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "component": self.component,
            "indicator": self.indicator,
            "provider": self.provider,
            "series_identifier": self.series_identifier,
            "observation_date": self.observation_date.isoformat(),
            "released_at": self.released_at.isoformat(),
            "retrieved_at": self.retrieved_at.isoformat(),
            "vintage_date": (
                None if self.vintage_date is None else self.vintage_date.isoformat()
            ),
            "quality_state": self.quality_state,
            "signal_score": self.signal_score,
            "weighted_contribution": self.weighted_contribution,
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True)
class EngineContextEvidence:
    """Unscored point-in-time context retained alongside analytical evidence."""

    identifier: str
    component: str
    provider: str
    dataset_role: str
    format_hint: str
    available_at: datetime
    content_sha256: str
    byte_count: int
    source_identifier: str
    access_mode: str
    explanation: str
    source_file_id: str | None = None
    entitled_match_count: int | None = None
    catalog_pattern_count: int | None = None
    selection_policy: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "component",
            "provider",
            "dataset_role",
            "format_hint",
            "source_identifier",
            "access_mode",
            "explanation",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name),
            )
        _aware(self.available_at, "available_at")
        digest = _text(self.content_sha256, "content_sha256").lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("content_sha256 must be a 64-character SHA-256 hex digest")
        object.__setattr__(self, "content_sha256", digest)
        if isinstance(self.byte_count, bool) or not isinstance(self.byte_count, int):
            raise TypeError("byte_count must be an int")
        if self.byte_count < 1:
            raise ValueError("byte_count must be positive")
        for field_name in ("source_file_id", "selection_policy"):
            object.__setattr__(
                self,
                field_name,
                _optional_text(getattr(self, field_name), field_name),
            )
        for field_name in ("entitled_match_count", "catalog_pattern_count"):
            object.__setattr__(
                self,
                field_name,
                _optional_count(getattr(self, field_name), field_name),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "component": self.component,
            "provider": self.provider,
            "dataset_role": self.dataset_role,
            "format_hint": self.format_hint,
            "available_at": self.available_at.isoformat(),
            "content_sha256": self.content_sha256,
            "byte_count": self.byte_count,
            "source_identifier": self.source_identifier,
            "access_mode": self.access_mode,
            "source_file_id": self.source_file_id,
            "entitled_match_count": self.entitled_match_count,
            "catalog_pattern_count": self.catalog_pattern_count,
            "selection_policy": self.selection_policy,
            "explanation": self.explanation,
            "scoring_contribution_allowed": False,
            "decision_authority_granted": False,
            "execution_authority_granted": False,
            "real_money_authorized": False,
        }


@dataclass(frozen=True, slots=True)
class AnalyticalEngineResult:
    """Versioned, evidence-linked output shared by all analytical engines."""

    identifier: str
    engine: str
    scope: str
    policy_version: str
    as_of: datetime
    generated_at: datetime
    direction: EngineDirection
    score: int
    confidence: int
    coverage: float
    data_status: EngineDataStatus
    summary: str
    explanation: str
    risks: tuple[str, ...]
    transmission_channels: tuple[str, ...]
    review_conditions: tuple[str, ...]
    evidence: tuple[EngineEvidence, ...]
    context_evidence: tuple[EngineContextEvidence, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "engine",
            "scope",
            "policy_version",
            "summary",
            "explanation",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name),
            )
        _aware(self.as_of, "as_of")
        _aware(self.generated_at, "generated_at")
        if not isinstance(self.direction, EngineDirection):
            raise TypeError("direction must be an EngineDirection")
        if not isinstance(self.data_status, EngineDataStatus):
            raise TypeError("data_status must be an EngineDataStatus")
        for field_name in ("score", "confidence"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an int")
            if not 0 <= value <= 100:
                raise ValueError(f"{field_name} must be between 0 and 100")
        if isinstance(self.coverage, bool) or not isinstance(
            self.coverage,
            (int, float),
        ):
            raise TypeError("coverage must be numeric")
        coverage = float(self.coverage)
        if not isfinite(coverage) or not 0.0 <= coverage <= 1.0:
            raise ValueError("coverage must be between 0.0 and 1.0")
        object.__setattr__(self, "coverage", coverage)
        for field_name in (
            "risks",
            "transmission_channels",
            "review_conditions",
        ):
            object.__setattr__(
                self,
                field_name,
                _strings(getattr(self, field_name), field_name),
            )
        if not isinstance(self.evidence, tuple) or not all(
            isinstance(value, EngineEvidence) for value in self.evidence
        ):
            raise TypeError("evidence must contain EngineEvidence values")
        if not isinstance(self.context_evidence, tuple) or not all(
            isinstance(value, EngineContextEvidence) for value in self.context_evidence
        ):
            raise TypeError("context_evidence must contain EngineContextEvidence values")
        if self.direction is EngineDirection.UNAVAILABLE and self.evidence:
            raise ValueError("unavailable results cannot contain scored evidence")
        if self.data_status is EngineDataStatus.UNAVAILABLE and self.coverage != 0:
            raise ValueError("unavailable results must have zero coverage")
        if any(item.released_at > self.as_of for item in self.evidence):
            raise ValueError("engine evidence cannot use future releases")
        if any(item.available_at > self.as_of for item in self.context_evidence):
            raise ValueError("engine context evidence cannot use future availability")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": "analytical-engine-result.v1",
            "identifier": self.identifier,
            "engine": self.engine,
            "scope": self.scope,
            "policy_version": self.policy_version,
            "as_of": self.as_of.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "direction": self.direction.value,
            "score": self.score,
            "confidence": self.confidence,
            "coverage": self.coverage,
            "data_status": self.data_status.value,
            "summary": self.summary,
            "explanation": self.explanation,
            "risks": list(self.risks),
            "transmission_channels": list(self.transmission_channels),
            "review_conditions": list(self.review_conditions),
            "evidence": [item.to_dict() for item in self.evidence],
        }
        if self.context_evidence:
            payload["context_evidence"] = [
                item.to_dict() for item in self.context_evidence
            ]
        return payload


__all__ = [
    "AnalyticalEngineResult",
    "EngineContextEvidence",
    "EngineDataStatus",
    "EngineDirection",
    "EngineEvidence",
]
