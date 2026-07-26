"""Versioned missing-data, conflict, confidence-ceiling, and veto governance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any

from intelligence.analytical_engine import EngineDataStatus, EngineDirection
from intelligence.normalization import (
    EXPECTED_ENGINE_ORDER,
    MultiEngineNormalizationBundle,
    NormalizedEngineAssessment,
)
from intelligence.synthesis_weights import MultiEngineSynthesisResult, SynthesisStatus

GOVERNANCE_POLICY_VERSION = "multi-engine-governance.v1"


class GovernanceStatus(str, Enum):
    """Governed evidence disposition before committee submission."""

    CLEARED = "cleared"
    INCOMPLETE = "incomplete"
    STALE = "stale"
    CONFLICTED = "conflicted"
    VETOED = "vetoed"
    DECISION_UNAVAILABLE = "decision_unavailable"


class IssueSeverity(str, Enum):
    INFORMATIONAL = "informational"
    WARNING = "warning"
    BLOCKING = "blocking"


class VetoType(str, Enum):
    CREDIT_STRESS = "credit_stress"
    RISK_STRESS = "risk_stress"


class PositiveConclusionCeiling(str, Enum):
    """Maximum positive conclusion permitted by evidence governance."""

    UNRESTRICTED = "unrestricted"
    LIMITED = "limited"
    NO_HIGH_CONVICTION_POSITIVE = "no_high_conviction_positive"
    UNAVAILABLE = "unavailable"


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


def _score(value: object, name: str, *, optional: bool = False) -> int | None:
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if not 0 <= value <= 100:
        raise ValueError(f"{name} must be between 0 and 100")
    return value


def _positive_int(value: object, name: str, *, maximum: int = 100) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class MultiEngineGovernancePolicy:
    """Immutable evidence-governance policy applied after weighted synthesis."""

    version: str
    published_at: datetime
    minimum_confidence_score: int
    minimum_data_quality_score: int
    hard_minimum_confidence_score: int
    hard_minimum_data_quality_score: int
    conflict_opportunity_threshold: int
    conflict_risk_threshold: int
    engine_support_threshold: int
    engine_risk_threshold: int
    minimum_conflict_engines_per_side: int
    credit_veto_risk_threshold: int
    risk_veto_risk_threshold: int
    veto_minimum_confidence_score: int
    veto_minimum_data_quality_score: int
    incomplete_confidence_ceiling: int
    stale_confidence_ceiling: int
    critical_stale_confidence_ceiling: int
    conflict_confidence_ceiling: int
    veto_confidence_ceiling: int
    critical_engines: tuple[str, ...]
    change_rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _required_text(self.version, "version"))
        _aware(self.published_at, "published_at")
        object.__setattr__(
            self,
            "change_rationale",
            _required_text(self.change_rationale, "change_rationale"),
        )
        for name in (
            "minimum_confidence_score",
            "minimum_data_quality_score",
            "hard_minimum_confidence_score",
            "hard_minimum_data_quality_score",
            "conflict_opportunity_threshold",
            "conflict_risk_threshold",
            "engine_support_threshold",
            "engine_risk_threshold",
            "credit_veto_risk_threshold",
            "risk_veto_risk_threshold",
            "veto_minimum_confidence_score",
            "veto_minimum_data_quality_score",
            "incomplete_confidence_ceiling",
            "stale_confidence_ceiling",
            "critical_stale_confidence_ceiling",
            "conflict_confidence_ceiling",
            "veto_confidence_ceiling",
        ):
            _score(getattr(self, name), name)
        _positive_int(
            self.minimum_conflict_engines_per_side,
            "minimum_conflict_engines_per_side",
            maximum=len(EXPECTED_ENGINE_ORDER),
        )
        if self.hard_minimum_confidence_score > self.minimum_confidence_score:
            raise ValueError("hard confidence minimum cannot exceed warning minimum")
        if self.hard_minimum_data_quality_score > self.minimum_data_quality_score:
            raise ValueError("hard data-quality minimum cannot exceed warning minimum")
        if not isinstance(self.critical_engines, tuple) or not self.critical_engines:
            raise TypeError("critical_engines must be a non-empty tuple")
        critical = tuple(
            _required_text(engine, "critical_engine") for engine in self.critical_engines
        )
        if len(critical) != len(set(critical)):
            raise ValueError("critical_engines must be unique")
        unknown = set(critical) - set(EXPECTED_ENGINE_ORDER)
        if unknown:
            raise ValueError(f"unknown critical engines: {sorted(unknown)}")
        object.__setattr__(self, "critical_engines", critical)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "multi-engine-governance-policy.v1",
            "version": self.version,
            "published_at": self.published_at.isoformat(),
            "minimum_confidence_score": self.minimum_confidence_score,
            "minimum_data_quality_score": self.minimum_data_quality_score,
            "hard_minimum_confidence_score": self.hard_minimum_confidence_score,
            "hard_minimum_data_quality_score": self.hard_minimum_data_quality_score,
            "conflict_opportunity_threshold": self.conflict_opportunity_threshold,
            "conflict_risk_threshold": self.conflict_risk_threshold,
            "engine_support_threshold": self.engine_support_threshold,
            "engine_risk_threshold": self.engine_risk_threshold,
            "minimum_conflict_engines_per_side": (
                self.minimum_conflict_engines_per_side
            ),
            "credit_veto_risk_threshold": self.credit_veto_risk_threshold,
            "risk_veto_risk_threshold": self.risk_veto_risk_threshold,
            "veto_minimum_confidence_score": self.veto_minimum_confidence_score,
            "veto_minimum_data_quality_score": self.veto_minimum_data_quality_score,
            "incomplete_confidence_ceiling": self.incomplete_confidence_ceiling,
            "stale_confidence_ceiling": self.stale_confidence_ceiling,
            "critical_stale_confidence_ceiling": (
                self.critical_stale_confidence_ceiling
            ),
            "conflict_confidence_ceiling": self.conflict_confidence_ceiling,
            "veto_confidence_ceiling": self.veto_confidence_ceiling,
            "critical_engines": list(self.critical_engines),
            "change_rationale": self.change_rationale,
        }


DEFAULT_MULTI_ENGINE_GOVERNANCE_POLICY = MultiEngineGovernancePolicy(
    version=GOVERNANCE_POLICY_VERSION,
    published_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
    minimum_confidence_score=50,
    minimum_data_quality_score=60,
    hard_minimum_confidence_score=30,
    hard_minimum_data_quality_score=40,
    conflict_opportunity_threshold=65,
    conflict_risk_threshold=65,
    engine_support_threshold=65,
    engine_risk_threshold=65,
    minimum_conflict_engines_per_side=2,
    credit_veto_risk_threshold=75,
    risk_veto_risk_threshold=75,
    veto_minimum_confidence_score=50,
    veto_minimum_data_quality_score=50,
    incomplete_confidence_ceiling=65,
    stale_confidence_ceiling=60,
    critical_stale_confidence_ceiling=45,
    conflict_confidence_ceiling=55,
    veto_confidence_ceiling=50,
    critical_engines=("credit_cycle", "risk"),
    change_rationale=(
        "Initial governance policy separates evidence sufficiency, disagreement, "
        "confidence ceilings, and credit/risk vetoes from weighted measurement and "
        "committee authority."
    ),
)


@dataclass(frozen=True, slots=True)
class GovernanceIssue:
    code: str
    severity: IssueSeverity
    message: str
    confidence_ceiling: int
    engine: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _required_text(self.code, "code"))
        object.__setattr__(self, "message", _required_text(self.message, "message"))
        if not isinstance(self.severity, IssueSeverity):
            raise TypeError("severity must be an IssueSeverity")
        _score(self.confidence_ceiling, "confidence_ceiling")
        if self.engine is not None:
            object.__setattr__(self, "engine", _required_text(self.engine, "engine"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "confidence_ceiling": self.confidence_ceiling,
            "engine": self.engine,
        }


@dataclass(frozen=True, slots=True)
class ActiveGovernanceVeto:
    veto_type: VetoType
    engine: str
    normalized_assessment_identifier: str
    source_direction: EngineDirection
    risk_score: int
    confidence_score: int
    data_quality_score: int
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.veto_type, VetoType):
            raise TypeError("veto_type must be a VetoType")
        object.__setattr__(self, "engine", _required_text(self.engine, "engine"))
        object.__setattr__(
            self,
            "normalized_assessment_identifier",
            _required_text(
                self.normalized_assessment_identifier,
                "normalized_assessment_identifier",
            ),
        )
        if not isinstance(self.source_direction, EngineDirection):
            raise TypeError("source_direction must be an EngineDirection")
        for name in ("risk_score", "confidence_score", "data_quality_score"):
            _score(getattr(self, name), name)
        object.__setattr__(self, "reason", _required_text(self.reason, "reason"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "veto_type": self.veto_type.value,
            "engine": self.engine,
            "normalized_assessment_identifier": (
                self.normalized_assessment_identifier
            ),
            "source_direction": self.source_direction.value,
            "risk_score": self.risk_score,
            "confidence_score": self.confidence_score,
            "data_quality_score": self.data_quality_score,
            "reason": self.reason,
            "high_conviction_positive_blocked": True,
            "transaction_instruction": None,
        }


@dataclass(frozen=True, slots=True)
class MultiEngineGovernanceResult:
    """Evidence-governance result without committee or portfolio authority."""

    identifier: str
    policy_version: str
    policy_published_at: datetime
    synthesis_result_identifier: str
    synthesis_policy_version: str
    normalization_bundle_identifier: str
    normalization_policy_version: str
    as_of: datetime
    generated_at: datetime
    status: GovernanceStatus
    source_synthesis_status: SynthesisStatus
    aggregate_opportunity_score: int | None
    aggregate_risk_score: int | None
    aggregate_confidence_score: int | None
    aggregate_data_quality_score: int | None
    governed_confidence_score: int | None
    confidence_ceiling: int
    decision_available: bool
    committee_submission_eligible: bool
    requires_human_review: bool
    positive_conclusion_ceiling: PositiveConclusionCeiling
    issues: tuple[GovernanceIssue, ...]
    active_vetoes: tuple[ActiveGovernanceVeto, ...]
    supportive_engines: tuple[str, ...]
    adverse_engines: tuple[str, ...]
    incomplete_engines: tuple[str, ...]
    stale_engines: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "identifier",
            "policy_version",
            "synthesis_result_identifier",
            "synthesis_policy_version",
            "normalization_bundle_identifier",
            "normalization_policy_version",
        ):
            object.__setattr__(
                self, name, _required_text(getattr(self, name), name)
            )
        _aware(self.policy_published_at, "policy_published_at")
        _aware(self.as_of, "as_of")
        _aware(self.generated_at, "generated_at")
        if not isinstance(self.status, GovernanceStatus):
            raise TypeError("status must be a GovernanceStatus")
        if not isinstance(self.source_synthesis_status, SynthesisStatus):
            raise TypeError("source_synthesis_status must be a SynthesisStatus")
        if not isinstance(self.positive_conclusion_ceiling, PositiveConclusionCeiling):
            raise TypeError(
                "positive_conclusion_ceiling must be a PositiveConclusionCeiling"
            )
        for name in (
            "aggregate_opportunity_score",
            "aggregate_risk_score",
            "aggregate_confidence_score",
            "aggregate_data_quality_score",
            "governed_confidence_score",
        ):
            _score(getattr(self, name), name, optional=True)
        _score(self.confidence_ceiling, "confidence_ceiling")
        for name in (
            "decision_available",
            "committee_submission_eligible",
            "requires_human_review",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        if not isinstance(self.issues, tuple) or not all(
            isinstance(item, GovernanceIssue) for item in self.issues
        ):
            raise TypeError("issues must contain GovernanceIssue values")
        if not isinstance(self.active_vetoes, tuple) or not all(
            isinstance(item, ActiveGovernanceVeto) for item in self.active_vetoes
        ):
            raise TypeError("active_vetoes must contain ActiveGovernanceVeto values")
        for name in (
            "supportive_engines",
            "adverse_engines",
            "incomplete_engines",
            "stale_engines",
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise TypeError(f"{name} must be a tuple")
            object.__setattr__(
                self,
                name,
                tuple(_required_text(item, name) for item in values),
            )
        if self.status is GovernanceStatus.DECISION_UNAVAILABLE:
            if self.decision_available or self.committee_submission_eligible:
                raise ValueError("unavailable governance cannot be decision-eligible")
            if self.governed_confidence_score is not None:
                raise ValueError("unavailable governance cannot publish confidence")
        else:
            if not self.decision_available or not self.committee_submission_eligible:
                raise ValueError("available governance must be committee-eligible")
            if self.governed_confidence_score is None:
                raise ValueError("available governance requires governed confidence")
        if self.status is GovernanceStatus.VETOED and not self.active_vetoes:
            raise ValueError("vetoed governance requires an active veto")
        if self.active_vetoes and self.positive_conclusion_ceiling not in (
            PositiveConclusionCeiling.NO_HIGH_CONVICTION_POSITIVE,
            PositiveConclusionCeiling.UNAVAILABLE,
        ):
            raise ValueError("active vetoes must block high-conviction positive conclusions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "multi-engine-governance-result.v1",
            "identifier": self.identifier,
            "policy_version": self.policy_version,
            "policy_published_at": self.policy_published_at.isoformat(),
            "synthesis_result_identifier": self.synthesis_result_identifier,
            "synthesis_policy_version": self.synthesis_policy_version,
            "normalization_bundle_identifier": self.normalization_bundle_identifier,
            "normalization_policy_version": self.normalization_policy_version,
            "as_of": self.as_of.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "status": self.status.value,
            "source_synthesis_status": self.source_synthesis_status.value,
            "aggregate_opportunity_score": self.aggregate_opportunity_score,
            "aggregate_risk_score": self.aggregate_risk_score,
            "aggregate_confidence_score": self.aggregate_confidence_score,
            "aggregate_data_quality_score": self.aggregate_data_quality_score,
            "source_scores_unchanged": True,
            "governed_confidence_score": self.governed_confidence_score,
            "confidence_ceiling": self.confidence_ceiling,
            "decision_available": self.decision_available,
            "committee_submission_eligible": self.committee_submission_eligible,
            "committee_submitted": False,
            "requires_human_review": self.requires_human_review,
            "positive_conclusion_ceiling": self.positive_conclusion_ceiling.value,
            "issues": [item.to_dict() for item in self.issues],
            "active_vetoes": [item.to_dict() for item in self.active_vetoes],
            "supportive_engines": list(self.supportive_engines),
            "adverse_engines": list(self.adverse_engines),
            "incomplete_engines": list(self.incomplete_engines),
            "stale_engines": list(self.stale_engines),
            "veto_policy_applied": True,
            "market_stance": None,
            "unapproved_action_default": "no_action",
            "personal_cio_action_affected": False,
            "capital_intelligence_score_affected": False,
            "portfolio_mutation_authority": False,
            "transaction_authority": False,
        }


class MultiEngineGovernor:
    """Apply governed evidence constraints without changing measured scores."""

    def __init__(
        self,
        policy: MultiEngineGovernancePolicy = DEFAULT_MULTI_ENGINE_GOVERNANCE_POLICY,
    ) -> None:
        if not isinstance(policy, MultiEngineGovernancePolicy):
            raise TypeError("policy must be a MultiEngineGovernancePolicy")
        self.policy = policy

    def evaluate(
        self,
        bundle: MultiEngineNormalizationBundle,
        synthesis: MultiEngineSynthesisResult,
    ) -> MultiEngineGovernanceResult:
        if not isinstance(bundle, MultiEngineNormalizationBundle):
            raise TypeError("bundle must be a MultiEngineNormalizationBundle")
        if not isinstance(synthesis, MultiEngineSynthesisResult):
            raise TypeError("synthesis must be a MultiEngineSynthesisResult")
        if synthesis.normalization_bundle_identifier != bundle.identifier:
            raise ValueError("synthesis and normalization lineage do not match")
        if synthesis.normalization_policy_version != bundle.policy_version:
            raise ValueError("synthesis and normalization policy versions do not match")
        if synthesis.as_of != bundle.as_of:
            raise ValueError("synthesis and normalization timestamps do not match")

        by_engine = {item.engine: item for item in bundle.assessments}
        issues: list[GovernanceIssue] = []
        vetoes: list[ActiveGovernanceVeto] = []
        confidence_ceiling = 100

        insufficient = (
            synthesis.status is SynthesisStatus.INSUFFICIENT_EVIDENCE
            or synthesis.aggregate_opportunity_score is None
            or synthesis.aggregate_risk_score is None
            or synthesis.aggregate_confidence_score is None
            or synthesis.aggregate_data_quality_score is None
        )
        if insufficient:
            issues.append(
                GovernanceIssue(
                    code="decision_unavailable",
                    severity=IssueSeverity.BLOCKING,
                    message=(
                        "Weighted synthesis did not meet its governed evidence thresholds; "
                        "no institutional conclusion is available."
                    ),
                    confidence_ceiling=0,
                )
            )
            return self._build_result(
                bundle,
                synthesis,
                status=GovernanceStatus.DECISION_UNAVAILABLE,
                confidence_ceiling=0,
                issues=tuple(issues),
                vetoes=(),
                supportive=(),
                adverse=(),
                incomplete=tuple(synthesis.missing_engines),
                stale=(),
            )

        assert synthesis.aggregate_confidence_score is not None
        assert synthesis.aggregate_data_quality_score is not None
        assert synthesis.aggregate_opportunity_score is not None
        assert synthesis.aggregate_risk_score is not None

        if synthesis.aggregate_confidence_score < self.policy.hard_minimum_confidence_score:
            issues.append(
                GovernanceIssue(
                    code="confidence_below_hard_minimum",
                    severity=IssueSeverity.BLOCKING,
                    message="Aggregate confidence is below the hard decision threshold.",
                    confidence_ceiling=0,
                )
            )
        if synthesis.aggregate_data_quality_score < self.policy.hard_minimum_data_quality_score:
            issues.append(
                GovernanceIssue(
                    code="data_quality_below_hard_minimum",
                    severity=IssueSeverity.BLOCKING,
                    message="Aggregate data quality is below the hard decision threshold.",
                    confidence_ceiling=0,
                )
            )
        if any(item.severity is IssueSeverity.BLOCKING for item in issues):
            return self._build_result(
                bundle,
                synthesis,
                status=GovernanceStatus.DECISION_UNAVAILABLE,
                confidence_ceiling=0,
                issues=tuple(issues),
                vetoes=(),
                supportive=(),
                adverse=(),
                incomplete=tuple(synthesis.missing_engines),
                stale=(),
            )

        incomplete = tuple(
            item.engine
            for item in bundle.assessments
            if item.data_status in (
                EngineDataStatus.INCOMPLETE,
                EngineDataStatus.UNAVAILABLE,
            )
        )
        stale = tuple(
            item.engine
            for item in bundle.assessments
            if item.data_status is EngineDataStatus.STALE
        )
        critical_missing = tuple(
            engine for engine in self.policy.critical_engines if engine in incomplete
        )
        critical_stale = tuple(
            engine for engine in self.policy.critical_engines if engine in stale
        )

        if synthesis.status is SynthesisStatus.PARTIAL or incomplete:
            confidence_ceiling = min(
                confidence_ceiling, self.policy.incomplete_confidence_ceiling
            )
            issues.append(
                GovernanceIssue(
                    code="incomplete_evidence",
                    severity=IssueSeverity.WARNING,
                    message=(
                        "One or more engine assessments are incomplete or unavailable; "
                        "missing weight remains unallocated."
                    ),
                    confidence_ceiling=self.policy.incomplete_confidence_ceiling,
                )
            )
        if critical_missing:
            confidence_ceiling = min(
                confidence_ceiling, self.policy.critical_stale_confidence_ceiling
            )
            for engine in critical_missing:
                issues.append(
                    GovernanceIssue(
                        code="critical_engine_unavailable",
                        severity=IssueSeverity.WARNING,
                        message=(
                            f"Critical engine {engine} is unavailable; high-conviction "
                            "positive conclusions are blocked."
                        ),
                        confidence_ceiling=(
                            self.policy.critical_stale_confidence_ceiling
                        ),
                        engine=engine,
                    )
                )
        if stale:
            confidence_ceiling = min(
                confidence_ceiling, self.policy.stale_confidence_ceiling
            )
            issues.append(
                GovernanceIssue(
                    code="stale_evidence",
                    severity=IssueSeverity.WARNING,
                    message="One or more engine assessments rely on stale evidence.",
                    confidence_ceiling=self.policy.stale_confidence_ceiling,
                )
            )
        if critical_stale:
            confidence_ceiling = min(
                confidence_ceiling, self.policy.critical_stale_confidence_ceiling
            )
            for engine in critical_stale:
                issues.append(
                    GovernanceIssue(
                        code="critical_engine_stale",
                        severity=IssueSeverity.WARNING,
                        message=(
                            f"Critical engine {engine} is stale; high-conviction positive "
                            "conclusions are blocked."
                        ),
                        confidence_ceiling=(
                            self.policy.critical_stale_confidence_ceiling
                        ),
                        engine=engine,
                    )
                )
        if synthesis.aggregate_confidence_score < self.policy.minimum_confidence_score:
            confidence_ceiling = min(
                confidence_ceiling, self.policy.incomplete_confidence_ceiling
            )
            issues.append(
                GovernanceIssue(
                    code="low_confidence",
                    severity=IssueSeverity.WARNING,
                    message="Aggregate confidence is below the preferred policy level.",
                    confidence_ceiling=self.policy.incomplete_confidence_ceiling,
                )
            )
        if synthesis.aggregate_data_quality_score < self.policy.minimum_data_quality_score:
            confidence_ceiling = min(
                confidence_ceiling, self.policy.incomplete_confidence_ceiling
            )
            issues.append(
                GovernanceIssue(
                    code="low_data_quality",
                    severity=IssueSeverity.WARNING,
                    message="Aggregate data quality is below the preferred policy level.",
                    confidence_ceiling=self.policy.incomplete_confidence_ceiling,
                )
            )

        supportive = tuple(
            item.engine
            for item in bundle.assessments
            if self._is_supportive(item)
        )
        adverse = tuple(
            item.engine
            for item in bundle.assessments
            if self._is_adverse(item)
        )
        aggregate_conflict = (
            synthesis.aggregate_opportunity_score
            >= self.policy.conflict_opportunity_threshold
            and synthesis.aggregate_risk_score >= self.policy.conflict_risk_threshold
        )
        engine_conflict = (
            len(supportive) >= self.policy.minimum_conflict_engines_per_side
            and len(adverse) >= self.policy.minimum_conflict_engines_per_side
        )
        conflicted = aggregate_conflict or engine_conflict
        if conflicted:
            confidence_ceiling = min(
                confidence_ceiling, self.policy.conflict_confidence_ceiling
            )
            issues.append(
                GovernanceIssue(
                    code="material_engine_conflict",
                    severity=IssueSeverity.WARNING,
                    message=(
                        "Material opportunity and risk evidence disagree; a high-conviction "
                        "conclusion requires human review."
                    ),
                    confidence_ceiling=self.policy.conflict_confidence_ceiling,
                )
            )

        for veto in self._active_vetoes(by_engine):
            vetoes.append(veto)
            confidence_ceiling = min(
                confidence_ceiling, self.policy.veto_confidence_ceiling
            )
            issues.append(
                GovernanceIssue(
                    code=f"{veto.veto_type.value}_veto",
                    severity=IssueSeverity.WARNING,
                    message=veto.reason,
                    confidence_ceiling=self.policy.veto_confidence_ceiling,
                    engine=veto.engine,
                )
            )

        if vetoes:
            status = GovernanceStatus.VETOED
        elif conflicted:
            status = GovernanceStatus.CONFLICTED
        elif critical_stale or stale:
            status = GovernanceStatus.STALE
        elif incomplete or synthesis.status is SynthesisStatus.PARTIAL:
            status = GovernanceStatus.INCOMPLETE
        else:
            status = GovernanceStatus.CLEARED

        return self._build_result(
            bundle,
            synthesis,
            status=status,
            confidence_ceiling=confidence_ceiling,
            issues=tuple(issues),
            vetoes=tuple(vetoes),
            supportive=supportive,
            adverse=adverse,
            incomplete=incomplete,
            stale=stale,
            block_high_conviction=bool(
                vetoes or conflicted or critical_missing or critical_stale
            ),
        )

    def _active_vetoes(
        self,
        by_engine: dict[str, NormalizedEngineAssessment],
    ) -> tuple[ActiveGovernanceVeto, ...]:
        vetoes: list[ActiveGovernanceVeto] = []
        for engine, veto_type, threshold in (
            (
                "credit_cycle",
                VetoType.CREDIT_STRESS,
                self.policy.credit_veto_risk_threshold,
            ),
            ("risk", VetoType.RISK_STRESS, self.policy.risk_veto_risk_threshold),
        ):
            assessment = by_engine[engine]
            if (
                assessment.risk_score is None
                or assessment.risk_score < threshold
                or assessment.confidence_score
                < self.policy.veto_minimum_confidence_score
                or assessment.data_quality_score
                < self.policy.veto_minimum_data_quality_score
                or assessment.source_direction
                not in (EngineDirection.CONTRACTING, EngineDirection.STRESSED)
            ):
                continue
            label = "Credit" if engine == "credit_cycle" else "Risk"
            vetoes.append(
                ActiveGovernanceVeto(
                    veto_type=veto_type,
                    engine=engine,
                    normalized_assessment_identifier=assessment.identifier,
                    source_direction=assessment.source_direction,
                    risk_score=assessment.risk_score,
                    confidence_score=assessment.confidence_score,
                    data_quality_score=assessment.data_quality_score,
                    reason=(
                        f"{label} evidence confirms elevated pressure. The veto blocks a "
                        "high-conviction positive conclusion but does not instruct a sale, "
                        "hedge, allocation change, or transaction."
                    ),
                )
            )
        return tuple(vetoes)

    def _is_supportive(self, assessment: NormalizedEngineAssessment) -> bool:
        return bool(
            assessment.opportunity_score is not None
            and assessment.opportunity_score >= self.policy.engine_support_threshold
            and assessment.confidence_score >= self.policy.hard_minimum_confidence_score
            and assessment.materiality_score >= 20
        )

    def _is_adverse(self, assessment: NormalizedEngineAssessment) -> bool:
        return bool(
            assessment.risk_score is not None
            and assessment.risk_score >= self.policy.engine_risk_threshold
            and assessment.confidence_score >= self.policy.hard_minimum_confidence_score
            and assessment.materiality_score >= 20
        )

    def _build_result(
        self,
        bundle: MultiEngineNormalizationBundle,
        synthesis: MultiEngineSynthesisResult,
        *,
        status: GovernanceStatus,
        confidence_ceiling: int,
        issues: tuple[GovernanceIssue, ...],
        vetoes: tuple[ActiveGovernanceVeto, ...],
        supportive: tuple[str, ...],
        adverse: tuple[str, ...],
        incomplete: tuple[str, ...],
        stale: tuple[str, ...],
        block_high_conviction: bool = False,
    ) -> MultiEngineGovernanceResult:
        available = status is not GovernanceStatus.DECISION_UNAVAILABLE
        governed_confidence = (
            None
            if not available or synthesis.aggregate_confidence_score is None
            else min(synthesis.aggregate_confidence_score, confidence_ceiling)
        )
        if not available:
            positive_ceiling = PositiveConclusionCeiling.UNAVAILABLE
        elif block_high_conviction:
            positive_ceiling = PositiveConclusionCeiling.NO_HIGH_CONVICTION_POSITIVE
        elif status in (
            GovernanceStatus.INCOMPLETE,
            GovernanceStatus.STALE,
        ):
            positive_ceiling = PositiveConclusionCeiling.LIMITED
        else:
            positive_ceiling = PositiveConclusionCeiling.UNRESTRICTED
        digest = sha256(
            (
                f"{self.policy.version}|{synthesis.identifier}|{bundle.identifier}|"
                f"{status.value}|{confidence_ceiling}"
            ).encode()
        ).hexdigest()[:20]
        return MultiEngineGovernanceResult(
            identifier=f"multi-engine-governance:{digest}",
            policy_version=self.policy.version,
            policy_published_at=self.policy.published_at,
            synthesis_result_identifier=synthesis.identifier,
            synthesis_policy_version=synthesis.policy_version,
            normalization_bundle_identifier=bundle.identifier,
            normalization_policy_version=bundle.policy_version,
            as_of=synthesis.as_of,
            generated_at=synthesis.as_of,
            status=status,
            source_synthesis_status=synthesis.status,
            aggregate_opportunity_score=synthesis.aggregate_opportunity_score,
            aggregate_risk_score=synthesis.aggregate_risk_score,
            aggregate_confidence_score=synthesis.aggregate_confidence_score,
            aggregate_data_quality_score=synthesis.aggregate_data_quality_score,
            governed_confidence_score=governed_confidence,
            confidence_ceiling=confidence_ceiling,
            decision_available=available,
            committee_submission_eligible=available,
            requires_human_review=status is not GovernanceStatus.CLEARED,
            positive_conclusion_ceiling=positive_ceiling,
            issues=issues,
            active_vetoes=vetoes,
            supportive_engines=supportive,
            adverse_engines=adverse,
            incomplete_engines=incomplete,
            stale_engines=stale,
        )


__all__ = [
    "ActiveGovernanceVeto",
    "DEFAULT_MULTI_ENGINE_GOVERNANCE_POLICY",
    "GOVERNANCE_POLICY_VERSION",
    "GovernanceIssue",
    "GovernanceStatus",
    "IssueSeverity",
    "MultiEngineGovernancePolicy",
    "MultiEngineGovernanceResult",
    "MultiEngineGovernor",
    "PositiveConclusionCeiling",
    "VetoType",
]
