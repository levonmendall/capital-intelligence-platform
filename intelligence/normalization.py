"""Explicit, non-aggregating normalization for analytical-engine results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
from math import isfinite
from typing import Any, Iterable

from intelligence.analytical_engine import (
    AnalyticalEngineResult,
    EngineDataStatus,
    EngineDirection,
)

NORMALIZATION_POLICY_VERSION = "multi-engine-normalization.v1"
EXPECTED_ENGINE_ORDER = (
    "global_liquidity",
    "business_cycle",
    "credit_cycle",
    "market_breadth",
    "valuation",
    "technical_momentum",
    "risk",
)


class ScoreOrientation(str, Enum):
    HIGHER_IS_SUPPORTIVE = "higher_is_supportive"
    LOWER_IS_SUPPORTIVE = "lower_is_supportive"


@dataclass(frozen=True, slots=True)
class EngineNormalizationPolicy:
    engine: str
    role: str
    score_orientation: ScoreOrientation
    opportunity_interpretation: str
    risk_interpretation: str

    def __post_init__(self) -> None:
        for name in (
            "engine",
            "role",
            "opportunity_interpretation",
            "risk_interpretation",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        if not isinstance(self.score_orientation, ScoreOrientation):
            raise TypeError("score_orientation must be a ScoreOrientation")


def _policy(
    engine: str,
    role: str,
    opportunity: str,
    risk: str,
) -> EngineNormalizationPolicy:
    return EngineNormalizationPolicy(
        engine=engine,
        role=role,
        score_orientation=ScoreOrientation.HIGHER_IS_SUPPORTIVE,
        opportunity_interpretation=opportunity,
        risk_interpretation=risk,
    )


ENGINE_NORMALIZATION_POLICIES = {
    "global_liquidity": _policy(
        "global_liquidity",
        "system_liquidity",
        "Higher support means funding liquidity is more capable of sustaining risk assets.",
        "Lower support means liquidity withdrawal creates greater fragility.",
    ),
    "business_cycle": _policy(
        "business_cycle",
        "economic_growth",
        "Higher support means real-economy activity is more broadly constructive.",
        "Lower support means contraction or demand deterioration is more prominent.",
    ),
    "credit_cycle": _policy(
        "credit_cycle",
        "credit_availability",
        "Higher support means credit pricing and availability are more constructive.",
        "Lower support means financing or borrower stress is more prominent.",
    ),
    "market_breadth": _policy(
        "market_breadth",
        "market_participation",
        "Higher support means gains are confirmed by broader participation.",
        "Lower support means leadership is narrow or deterioration is broad.",
    ),
    "valuation": _policy(
        "valuation",
        "valuation_support",
        "Higher support means the benchmark offers more valuation support versus history.",
        "Lower support means valuation leaves less margin for disappointment.",
    ),
    "technical_momentum": _policy(
        "technical_momentum",
        "price_confirmation",
        "Higher support means price trends are more persistent across horizons.",
        "Lower support means trend, volatility, or drawdown pressure is more prominent.",
    ),
    "risk": _policy(
        "risk",
        "market_resilience",
        "Higher support means observed resilience is stronger and fragility is lower.",
        "Lower support means volatility, concentration, liquidity, or tail pressure is greater.",
    ),
}

_DIRECTION_ANCHOR = {
    EngineDirection.EXPANDING: 80,
    EngineDirection.NEUTRAL: 50,
    EngineDirection.CONTRACTING: 25,
    EngineDirection.STRESSED: 10,
}
_STATUS_QUALITY = {
    EngineDataStatus.CURRENT: 100,
    EngineDataStatus.INCOMPLETE: 65,
    EngineDataStatus.STALE: 35,
    EngineDataStatus.UNAVAILABLE: 0,
}
_EVIDENCE_QUALITY = {
    "live": 100,
    "cached": 85,
    "fixture": 75,
    "fallback": 50,
    "stale": 25,
    "missing": 0,
}


def _aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _bounded_int(
    value: object,
    name: str,
    *,
    optional: bool = False,
) -> int | None:
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if not 0 <= value <= 100:
        raise ValueError(f"{name} must be between 0 and 100")
    return value


def _strings(values: object, name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not all(
        isinstance(value, str) and value.strip() for value in values
    ):
        raise TypeError(f"{name} must contain non-empty strings")
    return tuple(dict.fromkeys(value.strip() for value in values))


@dataclass(frozen=True, slots=True)
class NormalizedEngineAssessment:
    identifier: str
    engine: str
    role: str
    normalization_policy_version: str
    source_result_identifier: str | None
    source_policy_version: str | None
    as_of: datetime
    generated_at: datetime
    source_direction: EngineDirection
    source_score: int | None
    source_confidence: int
    opportunity_score: int | None
    risk_score: int | None
    confidence_score: int
    data_quality_score: int
    coverage: float
    freshness_days: int | None
    materiality_score: int
    data_status: EngineDataStatus
    supporting_evidence_identifiers: tuple[str, ...]
    contradictory_evidence_identifiers: tuple[str, ...]
    explanation: str

    def __post_init__(self) -> None:
        for name in (
            "identifier",
            "engine",
            "role",
            "normalization_policy_version",
            "explanation",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        for name in ("source_result_identifier", "source_policy_version"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty string or None")
        _aware(self.as_of, "as_of")
        _aware(self.generated_at, "generated_at")
        if not isinstance(self.source_direction, EngineDirection):
            raise TypeError("source_direction must be an EngineDirection")
        if not isinstance(self.data_status, EngineDataStatus):
            raise TypeError("data_status must be an EngineDataStatus")
        for name in ("source_score", "opportunity_score", "risk_score"):
            _bounded_int(getattr(self, name), name, optional=True)
        for name in (
            "source_confidence",
            "confidence_score",
            "data_quality_score",
            "materiality_score",
        ):
            _bounded_int(getattr(self, name), name)
        if isinstance(self.coverage, bool) or not isinstance(
            self.coverage, (int, float)
        ):
            raise TypeError("coverage must be numeric")
        coverage = float(self.coverage)
        if not isfinite(coverage) or not 0 <= coverage <= 1:
            raise ValueError("coverage must be between 0 and 1")
        object.__setattr__(self, "coverage", coverage)
        if self.freshness_days is not None and (
            isinstance(self.freshness_days, bool)
            or not isinstance(self.freshness_days, int)
            or self.freshness_days < 0
        ):
            raise ValueError("freshness_days must be a non-negative int or None")
        for name in (
            "supporting_evidence_identifiers",
            "contradictory_evidence_identifiers",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name), name))
        if self.data_status is EngineDataStatus.UNAVAILABLE:
            if any(
                value is not None
                for value in (
                    self.source_score,
                    self.opportunity_score,
                    self.risk_score,
                    self.freshness_days,
                )
            ):
                raise ValueError("unavailable assessments cannot contain derived scores")
            if self.confidence_score or self.data_quality_score or self.materiality_score:
                raise ValueError("unavailable assessments require zero derived quality")
        elif self.opportunity_score is None or self.risk_score is None:
            raise ValueError("available assessments require opportunity and risk scores")
        elif self.opportunity_score + self.risk_score != 100:
            raise ValueError("opportunity and risk scores must sum to 100")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "normalized-engine-assessment.v1",
            "identifier": self.identifier,
            "engine": self.engine,
            "role": self.role,
            "normalization_policy_version": self.normalization_policy_version,
            "source_result_identifier": self.source_result_identifier,
            "source_policy_version": self.source_policy_version,
            "as_of": self.as_of.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "source_direction": self.source_direction.value,
            "source_score": self.source_score,
            "source_confidence": self.source_confidence,
            "opportunity_score": self.opportunity_score,
            "risk_score": self.risk_score,
            "confidence_score": self.confidence_score,
            "data_quality_score": self.data_quality_score,
            "coverage": self.coverage,
            "freshness_days": self.freshness_days,
            "materiality_score": self.materiality_score,
            "data_status": self.data_status.value,
            "supporting_evidence_identifiers": list(
                self.supporting_evidence_identifiers
            ),
            "contradictory_evidence_identifiers": list(
                self.contradictory_evidence_identifiers
            ),
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True)
class MultiEngineNormalizationBundle:
    identifier: str
    policy_version: str
    as_of: datetime
    generated_at: datetime
    expected_engines: tuple[str, ...]
    assessments: tuple[NormalizedEngineAssessment, ...]

    def __post_init__(self) -> None:
        for name in ("identifier", "policy_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        _aware(self.as_of, "as_of")
        _aware(self.generated_at, "generated_at")
        object.__setattr__(
            self,
            "expected_engines",
            _strings(self.expected_engines, "expected_engines"),
        )
        if not isinstance(self.assessments, tuple) or not all(
            isinstance(item, NormalizedEngineAssessment) for item in self.assessments
        ):
            raise TypeError("assessments must contain normalized assessments")
        if tuple(item.engine for item in self.assessments) != self.expected_engines:
            raise ValueError("assessments must match expected engine order")
        if any(item.as_of != self.as_of for item in self.assessments):
            raise ValueError("assessment timestamps must match the bundle timestamp")
        if any(
            item.normalization_policy_version != self.policy_version
            for item in self.assessments
        ):
            raise ValueError("assessment policy versions must match the bundle policy")

    @property
    def available_engine_count(self) -> int:
        return sum(
            item.data_status is not EngineDataStatus.UNAVAILABLE
            for item in self.assessments
        )

    @property
    def unavailable_engines(self) -> tuple[str, ...]:
        return tuple(
            item.engine
            for item in self.assessments
            if item.data_status is EngineDataStatus.UNAVAILABLE
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "multi-engine-normalization-bundle.v1",
            "identifier": self.identifier,
            "policy_version": self.policy_version,
            "as_of": self.as_of.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "expected_engines": list(self.expected_engines),
            "available_engine_count": self.available_engine_count,
            "unavailable_engines": list(self.unavailable_engines),
            "aggregation_status": "not_performed",
            "weights_applied": False,
            "veto_policy_applied": False,
            "committee_submitted": False,
            "market_stance": None,
            "aggregate_opportunity_score": None,
            "aggregate_risk_score": None,
            "assessments": [item.to_dict() for item in self.assessments],
        }


class MultiEngineNormalizer:
    policy_version = NORMALIZATION_POLICY_VERSION

    def __init__(
        self,
        policies: Iterable[EngineNormalizationPolicy] | None = None,
    ) -> None:
        resolved = (
            tuple(ENGINE_NORMALIZATION_POLICIES[name] for name in EXPECTED_ENGINE_ORDER)
            if policies is None
            else tuple(policies)
        )
        if not resolved:
            raise ValueError("normalization policies cannot be empty")
        engines = tuple(item.engine for item in resolved)
        if len(engines) != len(set(engines)):
            raise ValueError("normalization policy engines must be unique")
        self.policies = resolved
        self.expected_engines = engines
        self._by_engine = {item.engine: item for item in resolved}

    def normalize(
        self,
        results: Iterable[AnalyticalEngineResult],
        *,
        as_of: datetime,
    ) -> MultiEngineNormalizationBundle:
        resolved_as_of = _aware(as_of, "as_of")
        by_engine: dict[str, AnalyticalEngineResult] = {}
        for result in results:
            if not isinstance(result, AnalyticalEngineResult):
                raise TypeError("results must contain AnalyticalEngineResult values")
            if result.engine not in self._by_engine:
                raise ValueError(
                    f"no normalization policy exists for engine {result.engine!r}"
                )
            if result.engine in by_engine:
                raise ValueError(f"duplicate result for engine {result.engine!r}")
            if result.as_of > resolved_as_of:
                raise ValueError("normalization cannot use future engine results")
            by_engine[result.engine] = result
        assessments = tuple(
            self._normalize_one(
                self._by_engine[engine],
                by_engine.get(engine),
                resolved_as_of,
            )
            for engine in self.expected_engines
        )
        source_key = "|".join(
            item.source_result_identifier or f"{item.engine}:missing"
            for item in assessments
        )
        digest = sha256(
            f"{self.policy_version}|{resolved_as_of.isoformat()}|{source_key}".encode()
        ).hexdigest()[:20]
        return MultiEngineNormalizationBundle(
            identifier=f"multi-engine-normalization:{digest}",
            policy_version=self.policy_version,
            as_of=resolved_as_of,
            generated_at=resolved_as_of,
            expected_engines=self.expected_engines,
            assessments=assessments,
        )

    def _normalize_one(
        self,
        policy: EngineNormalizationPolicy,
        result: AnalyticalEngineResult | None,
        as_of: datetime,
    ) -> NormalizedEngineAssessment:
        if result is None:
            return self._unavailable(
                policy,
                as_of,
                None,
                "No engine result was available at or before the decision timestamp.",
            )
        if (
            result.direction is EngineDirection.UNAVAILABLE
            or result.data_status is EngineDataStatus.UNAVAILABLE
        ):
            return self._unavailable(
                policy,
                as_of,
                result,
                "The source engine reported unavailable evidence; no score was inferred.",
            )
        oriented = (
            result.score
            if policy.score_orientation is ScoreOrientation.HIGHER_IS_SUPPORTIVE
            else 100 - result.score
        )
        opportunity = max(
            0,
            min(
                100,
                round(0.7 * oriented + 0.3 * _DIRECTION_ANCHOR[result.direction]),
            ),
        )
        risk = 100 - opportunity
        quality = self._data_quality(result)
        confidence = max(
            0,
            min(
                100,
                round(result.confidence * result.coverage * quality / 100),
            ),
        )
        materiality = max(
            0,
            min(100, round(abs(opportunity - 50) * 2 * confidence / 100)),
        )
        latest_release = max(
            (item.released_at for item in result.evidence),
            default=None,
        )
        freshness = (
            None
            if latest_release is None
            else max(0, (as_of.date() - latest_release.date()).days)
        )
        supporting, contradictory = self._alignment(result)
        key = sha256(
            f"{self.policy_version}|{result.identifier}".encode()
        ).hexdigest()[:20]
        return NormalizedEngineAssessment(
            identifier=f"normalized:{policy.engine}:{key}",
            engine=policy.engine,
            role=policy.role,
            normalization_policy_version=self.policy_version,
            source_result_identifier=result.identifier,
            source_policy_version=result.policy_version,
            as_of=as_of,
            generated_at=as_of,
            source_direction=result.direction,
            source_score=result.score,
            source_confidence=result.confidence,
            opportunity_score=opportunity,
            risk_score=risk,
            confidence_score=confidence,
            data_quality_score=quality,
            coverage=result.coverage,
            freshness_days=freshness,
            materiality_score=materiality,
            data_status=result.data_status,
            supporting_evidence_identifiers=supporting,
            contradictory_evidence_identifiers=contradictory,
            explanation=(
                f"{policy.opportunity_interpretation} "
                f"{policy.risk_interpretation} No cross-engine weights, vetoes, "
                "committee judgment, or market stance were applied."
            ),
        )

    def _unavailable(
        self,
        policy: EngineNormalizationPolicy,
        as_of: datetime,
        result: AnalyticalEngineResult | None,
        explanation: str,
    ) -> NormalizedEngineAssessment:
        source_key = "missing" if result is None else result.identifier
        key = sha256(
            f"{self.policy_version}|{source_key}|{as_of.isoformat()}".encode()
        ).hexdigest()[:20]
        return NormalizedEngineAssessment(
            identifier=f"normalized:{policy.engine}:{key}",
            engine=policy.engine,
            role=policy.role,
            normalization_policy_version=self.policy_version,
            source_result_identifier=None if result is None else result.identifier,
            source_policy_version=None if result is None else result.policy_version,
            as_of=as_of,
            generated_at=as_of,
            source_direction=EngineDirection.UNAVAILABLE,
            source_score=None,
            source_confidence=0 if result is None else result.confidence,
            opportunity_score=None,
            risk_score=None,
            confidence_score=0,
            data_quality_score=0,
            coverage=0.0 if result is None else result.coverage,
            freshness_days=None,
            materiality_score=0,
            data_status=EngineDataStatus.UNAVAILABLE,
            supporting_evidence_identifiers=(),
            contradictory_evidence_identifiers=(),
            explanation=explanation,
        )

    @staticmethod
    def _data_quality(result: AnalyticalEngineResult) -> int:
        status = _STATUS_QUALITY[result.data_status]
        if not result.evidence:
            return status
        evidence = sum(
            _EVIDENCE_QUALITY.get(item.quality_state.lower(), 40)
            for item in result.evidence
        ) / len(result.evidence)
        return max(0, min(100, round(0.6 * status + 0.4 * evidence)))

    @staticmethod
    def _alignment(
        result: AnalyticalEngineResult,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        supporting: list[str] = []
        contradictory: list[str] = []
        for item in result.evidence:
            signal = item.signal_score
            if result.direction is EngineDirection.EXPANDING:
                target = supporting if signal >= 0.15 else contradictory if signal <= -0.15 else None
            elif result.direction in (
                EngineDirection.CONTRACTING,
                EngineDirection.STRESSED,
            ):
                target = supporting if signal <= -0.15 else contradictory if signal >= 0.15 else None
            else:
                target = supporting if abs(signal) <= 0.20 else contradictory if abs(signal) >= 0.35 else None
            if target is not None:
                target.append(item.identifier)
        return tuple(supporting), tuple(contradictory)


__all__ = [
    "ENGINE_NORMALIZATION_POLICIES",
    "EXPECTED_ENGINE_ORDER",
    "EngineNormalizationPolicy",
    "MultiEngineNormalizationBundle",
    "MultiEngineNormalizer",
    "NORMALIZATION_POLICY_VERSION",
    "NormalizedEngineAssessment",
    "ScoreOrientation",
]
