"""Versioned fixed-weight synthesis for normalized analytical engines."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Iterable

from intelligence.analytical_engine import EngineDataStatus
from intelligence.normalization import (
    EXPECTED_ENGINE_ORDER,
    MultiEngineNormalizationBundle,
    NormalizedEngineAssessment,
)

BASIS_POINTS = 10_000
SYNTHESIS_WEIGHT_POLICY_VERSION = "multi-engine-synthesis-weights.v1"


class MissingWeightPolicy(str, Enum):
    """How unavailable engine weight is handled."""

    PRESERVE_UNALLOCATED = "preserve_unallocated"


class SynthesisStatus(str, Enum):
    """Whether a weighted synthesis is defensible."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _basis_points(value: object, name: str, *, allow_zero: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    minimum = 0 if allow_zero else 1
    if not minimum <= value <= BASIS_POINTS:
        raise ValueError(f"{name} must be between {minimum} and {BASIS_POINTS}")
    return value


def _score(value: object, name: str, *, optional: bool = False) -> int | None:
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if not 0 <= value <= 100:
        raise ValueError(f"{name} must be between 0 and 100")
    return value


def _round_score(value: float) -> int:
    return max(0, min(100, int(value + 0.5)))


@dataclass(frozen=True, slots=True)
class EngineSynthesisWeight:
    """One engine's fixed policy weights in basis points."""

    engine: str
    opportunity_weight_bps: int
    risk_weight_bps: int
    evidence_weight_bps: int
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "engine", _required_text(self.engine, "engine"))
        object.__setattr__(self, "rationale", _required_text(self.rationale, "rationale"))
        for name in (
            "opportunity_weight_bps",
            "risk_weight_bps",
            "evidence_weight_bps",
        ):
            _basis_points(getattr(self, name), name)
        if not any(
            getattr(self, name)
            for name in (
                "opportunity_weight_bps",
                "risk_weight_bps",
                "evidence_weight_bps",
            )
        ):
            raise ValueError("at least one synthesis weight must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "opportunity_weight_bps": self.opportunity_weight_bps,
            "risk_weight_bps": self.risk_weight_bps,
            "evidence_weight_bps": self.evidence_weight_bps,
            "opportunity_weight": self.opportunity_weight_bps / BASIS_POINTS,
            "risk_weight": self.risk_weight_bps / BASIS_POINTS,
            "evidence_weight": self.evidence_weight_bps / BASIS_POINTS,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class SynthesisWeightPolicy:
    """Immutable, versioned cross-engine weighting policy."""

    version: str
    published_at: datetime
    weights: tuple[EngineSynthesisWeight, ...]
    minimum_opportunity_coverage_bps: int
    minimum_risk_coverage_bps: int
    minimum_evidence_coverage_bps: int
    minimum_available_engines: int
    missing_weight_policy: MissingWeightPolicy
    regime_sensitive: bool
    change_rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _required_text(self.version, "version"))
        _aware(self.published_at, "published_at")
        object.__setattr__(
            self,
            "change_rationale",
            _required_text(self.change_rationale, "change_rationale"),
        )
        if not isinstance(self.weights, tuple) or not all(
            isinstance(item, EngineSynthesisWeight) for item in self.weights
        ):
            raise TypeError("weights must contain EngineSynthesisWeight values")
        engines = tuple(item.engine for item in self.weights)
        if engines != EXPECTED_ENGINE_ORDER:
            raise ValueError("weights must match the canonical engine order")
        for dimension in (
            "opportunity_weight_bps",
            "risk_weight_bps",
            "evidence_weight_bps",
        ):
            if sum(getattr(item, dimension) for item in self.weights) != BASIS_POINTS:
                raise ValueError(f"{dimension} must sum to {BASIS_POINTS}")
        for name in (
            "minimum_opportunity_coverage_bps",
            "minimum_risk_coverage_bps",
            "minimum_evidence_coverage_bps",
        ):
            _basis_points(getattr(self, name), name, allow_zero=False)
        if (
            isinstance(self.minimum_available_engines, bool)
            or not isinstance(self.minimum_available_engines, int)
            or not 1 <= self.minimum_available_engines <= len(EXPECTED_ENGINE_ORDER)
        ):
            raise ValueError("minimum_available_engines is outside the engine count")
        if not isinstance(self.missing_weight_policy, MissingWeightPolicy):
            raise TypeError("missing_weight_policy must be a MissingWeightPolicy")
        if not isinstance(self.regime_sensitive, bool):
            raise TypeError("regime_sensitive must be a bool")

    @property
    def by_engine(self) -> dict[str, EngineSynthesisWeight]:
        return {item.engine: item for item in self.weights}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "multi-engine-synthesis-weight-policy.v1",
            "version": self.version,
            "published_at": self.published_at.isoformat(),
            "weights": [item.to_dict() for item in self.weights],
            "minimum_opportunity_coverage_bps": (
                self.minimum_opportunity_coverage_bps
            ),
            "minimum_risk_coverage_bps": self.minimum_risk_coverage_bps,
            "minimum_evidence_coverage_bps": (
                self.minimum_evidence_coverage_bps
            ),
            "minimum_available_engines": self.minimum_available_engines,
            "missing_weight_policy": self.missing_weight_policy.value,
            "missing_weights_redistributed": False,
            "regime_sensitive": self.regime_sensitive,
            "change_rationale": self.change_rationale,
        }


DEFAULT_SYNTHESIS_WEIGHT_POLICY = SynthesisWeightPolicy(
    version=SYNTHESIS_WEIGHT_POLICY_VERSION,
    published_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
    weights=(
        EngineSynthesisWeight(
            "global_liquidity",
            2000,
            1000,
            1500,
            "Liquidity is a primary opportunity driver and a secondary risk channel.",
        ),
        EngineSynthesisWeight(
            "business_cycle",
            2000,
            1000,
            1500,
            "Growth breadth materially shapes opportunity but moves more slowly than market risk.",
        ),
        EngineSynthesisWeight(
            "credit_cycle",
            1500,
            2000,
            1500,
            "Credit supports opportunity and receives greater weight when measuring fragility.",
        ),
        EngineSynthesisWeight(
            "market_breadth",
            1500,
            1000,
            1500,
            "Participation confirms opportunity and reveals concentration risk.",
        ),
        EngineSynthesisWeight(
            "valuation",
            1000,
            1000,
            1000,
            "Valuation informs margin of safety without becoming a timing signal.",
        ),
        EngineSynthesisWeight(
            "technical_momentum",
            1000,
            1500,
            1000,
            "Price confirmation is supporting evidence and a meaningful downside-risk channel.",
        ),
        EngineSynthesisWeight(
            "risk",
            1000,
            2500,
            2000,
            "Observed resilience has the largest explicit risk and evidence weight.",
        ),
    ),
    minimum_opportunity_coverage_bps=7000,
    minimum_risk_coverage_bps=7000,
    minimum_evidence_coverage_bps=7000,
    minimum_available_engines=5,
    missing_weight_policy=MissingWeightPolicy.PRESERVE_UNALLOCATED,
    regime_sensitive=False,
    change_rationale=(
        "Initial fixed weights establish a transparent baseline before historical "
        "calibration, veto policy, committee governance, or regime sensitivity."
    ),
)


@dataclass(frozen=True, slots=True)
class WeightedEngineContribution:
    """One normalized assessment under one versioned synthesis policy."""

    engine: str
    normalized_assessment_identifier: str
    available: bool
    opportunity_weight_bps: int
    risk_weight_bps: int
    evidence_weight_bps: int
    opportunity_score: int | None
    risk_score: int | None
    confidence_score: int
    data_quality_score: int
    opportunity_weighted_points: float | None
    risk_weighted_points: float | None
    confidence_weighted_points: float | None
    data_quality_weighted_points: float | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "engine", _required_text(self.engine, "engine"))
        object.__setattr__(
            self,
            "normalized_assessment_identifier",
            _required_text(
                self.normalized_assessment_identifier,
                "normalized_assessment_identifier",
            ),
        )
        if not isinstance(self.available, bool):
            raise TypeError("available must be a bool")
        for name in (
            "opportunity_weight_bps",
            "risk_weight_bps",
            "evidence_weight_bps",
        ):
            _basis_points(getattr(self, name), name)
        _score(self.opportunity_score, "opportunity_score", optional=True)
        _score(self.risk_score, "risk_score", optional=True)
        _score(self.confidence_score, "confidence_score")
        _score(self.data_quality_score, "data_quality_score")
        point_fields = (
            "opportunity_weighted_points",
            "risk_weighted_points",
            "confidence_weighted_points",
            "data_quality_weighted_points",
        )
        for name in point_fields:
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
            ):
                raise TypeError(f"{name} must be numeric or None")
        if self.available:
            if self.opportunity_score is None or self.risk_score is None:
                raise ValueError("available contributions require opportunity and risk")
            if any(getattr(self, name) is None for name in point_fields):
                raise ValueError("available contributions require weighted points")
        else:
            if self.opportunity_score is not None or self.risk_score is not None:
                raise ValueError("unavailable contributions cannot contain scores")
            if self.confidence_score or self.data_quality_score:
                raise ValueError("unavailable contributions require zero evidence scores")
            if any(getattr(self, name) is not None for name in point_fields):
                raise ValueError("unavailable contributions cannot contain weighted points")

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "normalized_assessment_identifier": (
                self.normalized_assessment_identifier
            ),
            "available": self.available,
            "opportunity_weight_bps": self.opportunity_weight_bps,
            "risk_weight_bps": self.risk_weight_bps,
            "evidence_weight_bps": self.evidence_weight_bps,
            "opportunity_score": self.opportunity_score,
            "risk_score": self.risk_score,
            "confidence_score": self.confidence_score,
            "data_quality_score": self.data_quality_score,
            "opportunity_weighted_points": self.opportunity_weighted_points,
            "risk_weighted_points": self.risk_weighted_points,
            "confidence_weighted_points": self.confidence_weighted_points,
            "data_quality_weighted_points": self.data_quality_weighted_points,
        }


@dataclass(frozen=True, slots=True)
class MultiEngineSynthesisResult:
    """Weighted scores without veto, stance, committee, or product authority."""

    identifier: str
    policy_version: str
    policy_published_at: datetime
    normalization_bundle_identifier: str
    normalization_policy_version: str
    as_of: datetime
    generated_at: datetime
    status: SynthesisStatus
    aggregate_opportunity_score: int | None
    aggregate_risk_score: int | None
    aggregate_confidence_score: int | None
    aggregate_data_quality_score: int | None
    opportunity_weight_coverage_bps: int
    risk_weight_coverage_bps: int
    evidence_weight_coverage_bps: int
    minimum_available_engines: int
    available_engine_count: int
    missing_engines: tuple[str, ...]
    insufficiency_reasons: tuple[str, ...]
    contributions: tuple[WeightedEngineContribution, ...]

    def __post_init__(self) -> None:
        for name in (
            "identifier",
            "policy_version",
            "normalization_bundle_identifier",
            "normalization_policy_version",
        ):
            object.__setattr__(
                self,
                name,
                _required_text(getattr(self, name), name),
            )
        _aware(self.policy_published_at, "policy_published_at")
        _aware(self.as_of, "as_of")
        _aware(self.generated_at, "generated_at")
        if not isinstance(self.status, SynthesisStatus):
            raise TypeError("status must be a SynthesisStatus")
        for name in (
            "aggregate_opportunity_score",
            "aggregate_risk_score",
            "aggregate_confidence_score",
            "aggregate_data_quality_score",
        ):
            _score(getattr(self, name), name, optional=True)
        for name in (
            "opportunity_weight_coverage_bps",
            "risk_weight_coverage_bps",
            "evidence_weight_coverage_bps",
        ):
            _basis_points(getattr(self, name), name)
        if (
            isinstance(self.available_engine_count, bool)
            or not isinstance(self.available_engine_count, int)
            or not 0 <= self.available_engine_count <= len(EXPECTED_ENGINE_ORDER)
        ):
            raise ValueError("available_engine_count is outside the engine count")
        if (
            isinstance(self.minimum_available_engines, bool)
            or not isinstance(self.minimum_available_engines, int)
            or not 1 <= self.minimum_available_engines <= len(EXPECTED_ENGINE_ORDER)
        ):
            raise ValueError("minimum_available_engines is outside the engine count")
        object.__setattr__(
            self,
            "missing_engines",
            tuple(_required_text(item, "missing_engine") for item in self.missing_engines),
        )
        object.__setattr__(
            self,
            "insufficiency_reasons",
            tuple(
                _required_text(item, "insufficiency_reason")
                for item in self.insufficiency_reasons
            ),
        )
        if not isinstance(self.contributions, tuple) or not all(
            isinstance(item, WeightedEngineContribution)
            for item in self.contributions
        ):
            raise TypeError("contributions must contain weighted contributions")
        if tuple(item.engine for item in self.contributions) != EXPECTED_ENGINE_ORDER:
            raise ValueError("contributions must match the canonical engine order")
        scores = (
            self.aggregate_opportunity_score,
            self.aggregate_risk_score,
            self.aggregate_confidence_score,
            self.aggregate_data_quality_score,
        )
        if self.status is SynthesisStatus.INSUFFICIENT_EVIDENCE:
            if any(value is not None for value in scores):
                raise ValueError("insufficient synthesis cannot publish aggregate scores")
            if not self.insufficiency_reasons:
                raise ValueError("insufficient synthesis requires reasons")
        elif any(value is None for value in scores):
            raise ValueError("complete or partial synthesis requires all aggregate scores")
        if self.status is SynthesisStatus.COMPLETE and self.missing_engines:
            raise ValueError("complete synthesis cannot contain missing engines")
        if self.status is SynthesisStatus.PARTIAL and not self.missing_engines:
            raise ValueError("partial synthesis requires missing engines")

    @property
    def opportunity_weight_coverage(self) -> float:
        return self.opportunity_weight_coverage_bps / BASIS_POINTS

    @property
    def risk_weight_coverage(self) -> float:
        return self.risk_weight_coverage_bps / BASIS_POINTS

    @property
    def evidence_weight_coverage(self) -> float:
        return self.evidence_weight_coverage_bps / BASIS_POINTS

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "multi-engine-synthesis-result.v1",
            "identifier": self.identifier,
            "policy_version": self.policy_version,
            "policy_published_at": self.policy_published_at.isoformat(),
            "normalization_bundle_identifier": (
                self.normalization_bundle_identifier
            ),
            "normalization_policy_version": self.normalization_policy_version,
            "as_of": self.as_of.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "status": self.status.value,
            "aggregate_opportunity_score": self.aggregate_opportunity_score,
            "aggregate_risk_score": self.aggregate_risk_score,
            "aggregate_confidence_score": self.aggregate_confidence_score,
            "aggregate_data_quality_score": self.aggregate_data_quality_score,
            "opportunity_weight_coverage_bps": (
                self.opportunity_weight_coverage_bps
            ),
            "risk_weight_coverage_bps": self.risk_weight_coverage_bps,
            "evidence_weight_coverage_bps": (
                self.evidence_weight_coverage_bps
            ),
            "opportunity_weight_coverage": self.opportunity_weight_coverage,
            "risk_weight_coverage": self.risk_weight_coverage,
            "evidence_weight_coverage": self.evidence_weight_coverage,
            "minimum_available_engines": self.minimum_available_engines,
            "available_engine_count": self.available_engine_count,
            "missing_engines": list(self.missing_engines),
            "unallocated_opportunity_weight_bps": (
                BASIS_POINTS - self.opportunity_weight_coverage_bps
            ),
            "unallocated_risk_weight_bps": (
                BASIS_POINTS - self.risk_weight_coverage_bps
            ),
            "unallocated_evidence_weight_bps": (
                BASIS_POINTS - self.evidence_weight_coverage_bps
            ),
            "insufficiency_reasons": list(self.insufficiency_reasons),
            "weights_applied": True,
            "missing_weight_policy": MissingWeightPolicy.PRESERVE_UNALLOCATED.value,
            "missing_weights_redistributed": False,
            "score_basis": "observed_weight_normalized_above_threshold",
            "veto_policy_applied": False,
            "committee_submitted": False,
            "market_stance": None,
            "personal_cio_action_affected": False,
            "capital_intelligence_score_affected": False,
            "contributions": [item.to_dict() for item in self.contributions],
        }


class MultiEngineSynthesizer:
    """Apply one fixed, versioned policy to a normalization bundle."""

    def __init__(
        self,
        policy: SynthesisWeightPolicy = DEFAULT_SYNTHESIS_WEIGHT_POLICY,
    ) -> None:
        if not isinstance(policy, SynthesisWeightPolicy):
            raise TypeError("policy must be a SynthesisWeightPolicy")
        self.policy = policy

    def synthesize(
        self,
        bundle: MultiEngineNormalizationBundle,
    ) -> MultiEngineSynthesisResult:
        if not isinstance(bundle, MultiEngineNormalizationBundle):
            raise TypeError("bundle must be a MultiEngineNormalizationBundle")
        if bundle.expected_engines != EXPECTED_ENGINE_ORDER:
            raise ValueError("normalization bundle does not use the canonical engine set")
        by_engine = {item.engine: item for item in bundle.assessments}
        weights = self.policy.by_engine
        contributions = tuple(
            self._contribution(by_engine[engine], weights[engine])
            for engine in EXPECTED_ENGINE_ORDER
        )
        available = tuple(item for item in contributions if item.available)
        available_count = len(available)
        opportunity_coverage = sum(
            item.opportunity_weight_bps for item in available
        )
        risk_coverage = sum(item.risk_weight_bps for item in available)
        evidence_coverage = sum(item.evidence_weight_bps for item in available)
        reasons: list[str] = []
        if available_count < self.policy.minimum_available_engines:
            reasons.append(
                f"available engines {available_count} are below the required "
                f"{self.policy.minimum_available_engines}"
            )
        if opportunity_coverage < self.policy.minimum_opportunity_coverage_bps:
            reasons.append("opportunity weighted coverage is below policy minimum")
        if risk_coverage < self.policy.minimum_risk_coverage_bps:
            reasons.append("risk weighted coverage is below policy minimum")
        if evidence_coverage < self.policy.minimum_evidence_coverage_bps:
            reasons.append("evidence weighted coverage is below policy minimum")
        missing = tuple(item.engine for item in contributions if not item.available)

        if reasons:
            status = SynthesisStatus.INSUFFICIENT_EVIDENCE
            opportunity_score = None
            risk_score = None
            confidence_score = None
            data_quality_score = None
        else:
            status = (
                SynthesisStatus.COMPLETE
                if not missing
                else SynthesisStatus.PARTIAL
            )
            opportunity_score = self._observed_score(
                available,
                "opportunity_weight_bps",
                "opportunity_score",
                opportunity_coverage,
            )
            risk_score = self._observed_score(
                available,
                "risk_weight_bps",
                "risk_score",
                risk_coverage,
            )
            confidence_score = self._full_policy_evidence_score(
                available,
                "confidence_score",
            )
            data_quality_score = self._full_policy_evidence_score(
                available,
                "data_quality_score",
            )

        digest = sha256(
            (
                f"{self.policy.version}|{bundle.identifier}|"
                f"{bundle.as_of.isoformat()}"
            ).encode()
        ).hexdigest()[:20]
        return MultiEngineSynthesisResult(
            identifier=f"multi-engine-synthesis:{digest}",
            policy_version=self.policy.version,
            policy_published_at=self.policy.published_at,
            normalization_bundle_identifier=bundle.identifier,
            normalization_policy_version=bundle.policy_version,
            as_of=bundle.as_of,
            generated_at=bundle.as_of,
            status=status,
            aggregate_opportunity_score=opportunity_score,
            aggregate_risk_score=risk_score,
            aggregate_confidence_score=confidence_score,
            aggregate_data_quality_score=data_quality_score,
            opportunity_weight_coverage_bps=opportunity_coverage,
            risk_weight_coverage_bps=risk_coverage,
            evidence_weight_coverage_bps=evidence_coverage,
            minimum_available_engines=self.policy.minimum_available_engines,
            available_engine_count=available_count,
            missing_engines=missing,
            insufficiency_reasons=tuple(reasons),
            contributions=contributions,
        )

    @staticmethod
    def _contribution(
        assessment: NormalizedEngineAssessment,
        weight: EngineSynthesisWeight,
    ) -> WeightedEngineContribution:
        available = (
            assessment.data_status is not EngineDataStatus.UNAVAILABLE
            and assessment.opportunity_score is not None
            and assessment.risk_score is not None
        )
        if not available:
            return WeightedEngineContribution(
                engine=assessment.engine,
                normalized_assessment_identifier=assessment.identifier,
                available=False,
                opportunity_weight_bps=weight.opportunity_weight_bps,
                risk_weight_bps=weight.risk_weight_bps,
                evidence_weight_bps=weight.evidence_weight_bps,
                opportunity_score=None,
                risk_score=None,
                confidence_score=0,
                data_quality_score=0,
                opportunity_weighted_points=None,
                risk_weighted_points=None,
                confidence_weighted_points=None,
                data_quality_weighted_points=None,
            )
        return WeightedEngineContribution(
            engine=assessment.engine,
            normalized_assessment_identifier=assessment.identifier,
            available=True,
            opportunity_weight_bps=weight.opportunity_weight_bps,
            risk_weight_bps=weight.risk_weight_bps,
            evidence_weight_bps=weight.evidence_weight_bps,
            opportunity_score=assessment.opportunity_score,
            risk_score=assessment.risk_score,
            confidence_score=assessment.confidence_score,
            data_quality_score=assessment.data_quality_score,
            opportunity_weighted_points=round(
                weight.opportunity_weight_bps
                * assessment.opportunity_score
                / BASIS_POINTS,
                4,
            ),
            risk_weighted_points=round(
                weight.risk_weight_bps
                * assessment.risk_score
                / BASIS_POINTS,
                4,
            ),
            confidence_weighted_points=round(
                weight.evidence_weight_bps
                * assessment.confidence_score
                / BASIS_POINTS,
                4,
            ),
            data_quality_weighted_points=round(
                weight.evidence_weight_bps
                * assessment.data_quality_score
                / BASIS_POINTS,
                4,
            ),
        )

    @staticmethod
    def _observed_score(
        contributions: Iterable[WeightedEngineContribution],
        weight_name: str,
        score_name: str,
        coverage_bps: int,
    ) -> int:
        numerator = sum(
            getattr(item, weight_name) * int(getattr(item, score_name))
            for item in contributions
        )
        return _round_score(numerator / coverage_bps)

    @staticmethod
    def _full_policy_evidence_score(
        contributions: Iterable[WeightedEngineContribution],
        score_name: str,
    ) -> int:
        points = sum(
            item.evidence_weight_bps * int(getattr(item, score_name))
            for item in contributions
        )
        return _round_score(points / BASIS_POINTS)


__all__ = [
    "BASIS_POINTS",
    "DEFAULT_SYNTHESIS_WEIGHT_POLICY",
    "EngineSynthesisWeight",
    "MissingWeightPolicy",
    "MultiEngineSynthesisResult",
    "MultiEngineSynthesizer",
    "SYNTHESIS_WEIGHT_POLICY_VERSION",
    "SynthesisStatus",
    "SynthesisWeightPolicy",
    "WeightedEngineContribution",
]
