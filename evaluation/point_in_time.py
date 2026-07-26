"""Point-in-time decision snapshots, outcome attribution, and calibration.

The evaluator never reconstructs a decision from hindsight data.  It first
captures the candidate, every available use of capital, specialist governance,
CIO decision, portfolio implementation, thesis, evidence lineage, models, and
code version in one immutable snapshot.  Realized outcomes are joined later
without changing that original decision record.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any

from cio import (
    CIOAction,
    CIODecision,
    CandidateDecisionRecord,
    IndependentSpecialistPacket,
)
from opportunity import AlternativeKind, OpportunitySetContext, RankedOpportunity
from portfolio.construction_api import (
    ConstructionStatus,
    PortfolioConstructionResult,
)
from thesis import LivingThesis


class EvaluationOutcome(str, Enum):
    VALUE_ADDED = "value_added"
    VALUE_DESTROYED = "value_destroyed"
    MATCHED_ALTERNATIVE = "matched_alternative"
    NOT_IMPLEMENTED = "not_implemented"


class EvaluationProcessVerdict(str, Enum):
    DISCIPLINED = "disciplined"
    FLAWED = "flawed"


def _required_text(value: object, *, field_name: str) -> str:
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


def _finite(
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
    return round(normalized, 10)


def _text_tuple(
    value: object,
    *,
    field_name: str,
    minimum: int = 0,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(
        _required_text(item, field_name=field_name) for item in value
    )
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} requires at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """One immutable source known no later than the decision timestamp."""

    identifier: str
    available_at: datetime
    source_type: str

    def __post_init__(self) -> None:
        for field_name in ("identifier", "source_type"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.available_at, field_name="available_at")


@dataclass(frozen=True, slots=True)
class CapitalAlternativeSnapshot:
    """One use of capital that was available at the decision boundary."""

    identifier: str
    kind: AlternativeKind
    expected_return: float
    implementation_cost_return: float
    evidence_quality: float
    liquidity_score: float
    current_weight: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _required_text(self.identifier, field_name="identifier"),
        )
        if not isinstance(self.kind, AlternativeKind):
            raise TypeError("kind must be an AlternativeKind")
        object.__setattr__(
            self,
            "expected_return",
            _finite(self.expected_return, field_name="expected_return"),
        )
        for field_name in (
            "implementation_cost_return",
            "evidence_quality",
            "liquidity_score",
            "current_weight",
        ):
            maximum = 1.0 if field_name != "implementation_cost_return" else None
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                    maximum=maximum,
                ),
            )

    @property
    def net_expected_return(self) -> float:
        return round(self.expected_return - self.implementation_cost_return, 10)


@dataclass(frozen=True, slots=True)
class DecisionEvidenceSnapshot:
    """Complete immutable information set used for one CIO decision."""

    identifier: str
    captured_at: datetime
    decision_as_of: datetime
    decision_identifier: str
    candidate_identifier: str
    opportunity_context_identifier: str
    symbol: str
    action: CIOAction
    decision_horizon_days: int
    current_price: float
    expected_return: float
    expected_downside: float
    probability_of_success: float
    final_confidence: float
    current_portfolio_weight: float
    recommended_position_weight: float | None
    implemented_position_weight: float
    implementation_status: ConstructionStatus | None
    estimated_implementation_cost_return: float
    opportunity_rank: int
    effective_opportunity_cost: float
    opportunity_edge: float
    alternatives: tuple[CapitalAlternativeSnapshot, ...]
    evidence_references: tuple[EvidenceReference, ...]
    model_versions: tuple[str, ...]
    policy_versions: tuple[str, ...]
    specialist_roles: tuple[str, ...]
    evidence_vetoes: tuple[str, ...]
    implementation_blocks: tuple[str, ...]
    thesis_identifier: str | None
    thesis_assumptions: tuple[str, ...]
    thesis_invalidation_conditions: tuple[str, ...]
    thesis_monitoring_indicators: tuple[str, ...]
    code_version: str
    schema_version: str = "decision-evidence-snapshot.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "decision_identifier",
            "candidate_identifier",
            "opportunity_context_identifier",
            "symbol",
            "code_version",
            "schema_version",
        ):
            value = _required_text(getattr(self, field_name), field_name=field_name)
            object.__setattr__(
                self,
                field_name,
                value.upper() if field_name == "symbol" else value,
            )
        _aware(self.captured_at, field_name="captured_at")
        _aware(self.decision_as_of, field_name="decision_as_of")
        if self.captured_at < self.decision_as_of:
            raise ValueError("captured_at cannot predate the decision")
        if not isinstance(self.action, CIOAction):
            raise TypeError("action must be a CIOAction")
        if isinstance(self.decision_horizon_days, bool) or not isinstance(
            self.decision_horizon_days,
            int,
        ):
            raise TypeError("decision_horizon_days must be an integer")
        if self.decision_horizon_days < 1:
            raise ValueError("decision_horizon_days must be positive")
        for field_name in (
            "current_price",
            "expected_return",
            "expected_downside",
            "effective_opportunity_cost",
            "opportunity_edge",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(getattr(self, field_name), field_name=field_name),
            )
        if self.current_price <= 0.0:
            raise ValueError("current_price must be positive")
        for field_name in (
            "probability_of_success",
            "final_confidence",
            "current_portfolio_weight",
            "implemented_position_weight",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                    maximum=1.0,
                ),
            )
        if self.recommended_position_weight is not None:
            object.__setattr__(
                self,
                "recommended_position_weight",
                _finite(
                    self.recommended_position_weight,
                    field_name="recommended_position_weight",
                    minimum=0.0,
                    maximum=1.0,
                ),
            )
        if self.implementation_status is not None and not isinstance(
            self.implementation_status,
            ConstructionStatus,
        ):
            raise TypeError(
                "implementation_status must be ConstructionStatus or None"
            )
        object.__setattr__(
            self,
            "estimated_implementation_cost_return",
            _finite(
                self.estimated_implementation_cost_return,
                field_name="estimated_implementation_cost_return",
                minimum=0.0,
            ),
        )
        if isinstance(self.opportunity_rank, bool) or not isinstance(
            self.opportunity_rank,
            int,
        ):
            raise TypeError("opportunity_rank must be an integer")
        if self.opportunity_rank < 1:
            raise ValueError("opportunity_rank must be positive")
        if not isinstance(self.alternatives, tuple) or not all(
            isinstance(item, CapitalAlternativeSnapshot)
            for item in self.alternatives
        ):
            raise TypeError(
                "alternatives must contain CapitalAlternativeSnapshot values"
            )
        if not self.alternatives:
            raise ValueError("all available capital alternatives are required")
        alternative_ids = tuple(item.identifier for item in self.alternatives)
        if len(alternative_ids) != len(set(alternative_ids)):
            raise ValueError("capital alternatives must be unique")
        if not any(item.kind is AlternativeKind.CASH for item in self.alternatives):
            raise ValueError("the original capital set must include cash")
        if not isinstance(self.evidence_references, tuple) or not all(
            isinstance(item, EvidenceReference)
            for item in self.evidence_references
        ):
            raise TypeError(
                "evidence_references must contain EvidenceReference values"
            )
        if not self.evidence_references:
            raise ValueError("exact point-in-time evidence references are required")
        evidence_ids = tuple(item.identifier for item in self.evidence_references)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence references must be unique")
        if any(
            item.available_at > self.decision_as_of
            for item in self.evidence_references
        ):
            raise ValueError(
                "decision snapshots cannot contain evidence unavailable at decision time"
            )
        for field_name, minimum in (
            ("model_versions", 1),
            ("policy_versions", 1),
            ("specialist_roles", 5),
            ("evidence_vetoes", 0),
            ("implementation_blocks", 0),
            ("thesis_assumptions", 0),
            ("thesis_invalidation_conditions", 0),
            ("thesis_monitoring_indicators", 0),
        ):
            object.__setattr__(
                self,
                field_name,
                _text_tuple(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=minimum,
                ),
            )
        if len(self.specialist_roles) != 5:
            raise ValueError("exactly five specialist roles are required")
        if self.thesis_identifier is not None:
            object.__setattr__(
                self,
                "thesis_identifier",
                _required_text(
                    self.thesis_identifier,
                    field_name="thesis_identifier",
                ),
            )
        ownership_action = self.action in {
            CIOAction.BUY,
            CIOAction.INCREASE,
            CIOAction.HOLD,
        }
        implemented_ownership = self.implemented_position_weight > 0.0
        if ownership_action and implemented_ownership:
            if self.thesis_identifier is None:
                raise ValueError(
                    "implemented ownership decisions require an explicit thesis"
                )
            for field_name in (
                "thesis_assumptions",
                "thesis_invalidation_conditions",
                "thesis_monitoring_indicators",
            ):
                if not getattr(self, field_name):
                    raise ValueError(
                        f"implemented ownership requires {field_name}"
                    )

    @property
    def fingerprint(self) -> str:
        payload = self.to_dict(include_fingerprint=False)
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def best_expected_alternative(self) -> CapitalAlternativeSnapshot:
        return max(
            self.alternatives,
            key=lambda item: (
                item.net_expected_return,
                item.evidence_quality,
                item.liquidity_score,
                item.identifier,
            ),
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "identifier": self.identifier,
            "captured_at": self.captured_at.isoformat(),
            "decision_as_of": self.decision_as_of.isoformat(),
            "decision_identifier": self.decision_identifier,
            "candidate_identifier": self.candidate_identifier,
            "opportunity_context_identifier": self.opportunity_context_identifier,
            "symbol": self.symbol,
            "action": self.action.value,
            "decision_horizon_days": self.decision_horizon_days,
            "current_price": self.current_price,
            "expected_return": self.expected_return,
            "expected_downside": self.expected_downside,
            "probability_of_success": self.probability_of_success,
            "final_confidence": self.final_confidence,
            "current_portfolio_weight": self.current_portfolio_weight,
            "recommended_position_weight": self.recommended_position_weight,
            "implemented_position_weight": self.implemented_position_weight,
            "implementation_status": (
                None
                if self.implementation_status is None
                else self.implementation_status.value
            ),
            "estimated_implementation_cost_return": (
                self.estimated_implementation_cost_return
            ),
            "opportunity_rank": self.opportunity_rank,
            "effective_opportunity_cost": self.effective_opportunity_cost,
            "opportunity_edge": self.opportunity_edge,
            "alternatives": [
                {
                    "identifier": item.identifier,
                    "kind": item.kind.value,
                    "expected_return": item.expected_return,
                    "implementation_cost_return": item.implementation_cost_return,
                    "net_expected_return": item.net_expected_return,
                    "evidence_quality": item.evidence_quality,
                    "liquidity_score": item.liquidity_score,
                    "current_weight": item.current_weight,
                }
                for item in self.alternatives
            ],
            "evidence_references": [
                {
                    "identifier": item.identifier,
                    "available_at": item.available_at.isoformat(),
                    "source_type": item.source_type,
                }
                for item in self.evidence_references
            ],
            "model_versions": list(self.model_versions),
            "policy_versions": list(self.policy_versions),
            "specialist_roles": list(self.specialist_roles),
            "evidence_vetoes": list(self.evidence_vetoes),
            "implementation_blocks": list(self.implementation_blocks),
            "thesis_identifier": self.thesis_identifier,
            "thesis_assumptions": list(self.thesis_assumptions),
            "thesis_invalidation_conditions": list(
                self.thesis_invalidation_conditions
            ),
            "thesis_monitoring_indicators": list(
                self.thesis_monitoring_indicators
            ),
            "code_version": self.code_version,
            "schema_version": self.schema_version,
        }
        if include_fingerprint:
            payload["fingerprint"] = self.fingerprint
        return payload

    @classmethod
    def capture(
        cls,
        *,
        candidate: CandidateDecisionRecord,
        ranked: RankedOpportunity,
        decision: CIODecision,
        packet: IndependentSpecialistPacket,
        opportunity_context: OpportunitySetContext,
        construction: PortfolioConstructionResult | None,
        thesis: LivingThesis | None,
        captured_at: datetime,
        code_version: str,
        evidence_references: tuple[EvidenceReference, ...] | None = None,
    ) -> "DecisionEvidenceSnapshot":
        if ranked.candidate.identifier != candidate.identifier:
            raise ValueError("ranked opportunity does not match candidate")
        if decision.candidate_identifier != candidate.identifier:
            raise ValueError("decision does not match candidate")
        if packet.candidate_identifier != candidate.identifier:
            raise ValueError("specialist packet does not match candidate")
        implemented_weight = candidate.current_portfolio_weight
        implementation_status: ConstructionStatus | None = None
        estimated_cost = 0.0
        if construction is not None:
            implementation_status = construction.status
            implemented_weight = dict(construction.target_weights).get(
                candidate.instrument.symbol,
                0.0,
            )
            estimated_cost = sum(
                item.estimated_cost_return
                for item in construction.trades
                if item.symbol == candidate.instrument.symbol
                or candidate.instrument.symbol in item.funding_for
            )
        if evidence_references is None:
            evidence_references = tuple(
                EvidenceReference(
                    identifier=identifier,
                    available_at=candidate.as_of,
                    source_type="candidate_evidence",
                )
                for identifier in candidate.evidence_identifiers
            )
        alternatives = tuple(
            CapitalAlternativeSnapshot(
                identifier=item.identifier,
                kind=item.kind,
                expected_return=item.expected_return,
                implementation_cost_return=item.implementation_cost_return,
                evidence_quality=item.evidence_quality,
                liquidity_score=item.liquidity_score,
                current_weight=item.current_weight,
            )
            for item in opportunity_context.alternatives
        )
        policy_versions = tuple(
            dict.fromkeys(
                (
                    ranked.qualification.policy_version,
                    ranked.qualification.universe.policy_version,
                    decision.policy_version,
                    *(
                        ()
                        if construction is None
                        else (construction.policy_version,)
                    ),
                )
            )
        )
        specialist_roles = tuple(
            item.role.value for item in packet.analyses
        )
        return cls(
            identifier=f"evaluation-snapshot:{decision.identifier}",
            captured_at=captured_at,
            decision_as_of=decision.as_of,
            decision_identifier=decision.identifier,
            candidate_identifier=candidate.identifier,
            opportunity_context_identifier=opportunity_context.identifier,
            symbol=candidate.instrument.symbol,
            action=decision.action,
            decision_horizon_days=decision.decision_horizon_days,
            current_price=candidate.current_price,
            expected_return=decision.expected_return,
            expected_downside=candidate.expected_downside,
            probability_of_success=candidate.probability_of_success,
            final_confidence=decision.final_confidence,
            current_portfolio_weight=candidate.current_portfolio_weight,
            recommended_position_weight=decision.recommended_position_weight,
            implemented_position_weight=implemented_weight,
            implementation_status=implementation_status,
            estimated_implementation_cost_return=estimated_cost,
            opportunity_rank=ranked.rank,
            effective_opportunity_cost=(
                ranked.qualification.effective_opportunity_cost
            ),
            opportunity_edge=ranked.qualification.opportunity_edge,
            alternatives=alternatives,
            evidence_references=evidence_references,
            model_versions=candidate.model_versions,
            policy_versions=policy_versions,
            specialist_roles=specialist_roles,
            evidence_vetoes=packet.evidence_vetoes,
            implementation_blocks=packet.implementation_blocks,
            thesis_identifier=None if thesis is None else thesis.identifier,
            thesis_assumptions=() if thesis is None else thesis.assumptions,
            thesis_invalidation_conditions=(
                () if thesis is None else thesis.invalidation_conditions
            ),
            thesis_monitoring_indicators=(
                () if thesis is None else thesis.monitoring_indicators
            ),
            code_version=code_version,
        )


@dataclass(frozen=True, slots=True)
class AlternativeRealizedReturn:
    alternative_identifier: str
    realized_return: float
    source_identifier: str

    def __post_init__(self) -> None:
        for field_name in ("alternative_identifier", "source_identifier"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "realized_return",
            _finite(self.realized_return, field_name="realized_return"),
        )


@dataclass(frozen=True, slots=True)
class RealizedDecisionOutcome:
    """Post-decision observations; never used to mutate the original snapshot."""

    snapshot_identifier: str
    horizon_ended_at: datetime
    observed_at: datetime
    decision_to_horizon_return: float
    implementation_to_horizon_return: float
    actual_implementation_cost_return: float
    cash_return: float
    benchmark_return: float
    passive_portfolio_return: float
    alternative_returns: tuple[AlternativeRealizedReturn, ...]
    source_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "snapshot_identifier",
            _required_text(
                self.snapshot_identifier,
                field_name="snapshot_identifier",
            ),
        )
        _aware(self.horizon_ended_at, field_name="horizon_ended_at")
        _aware(self.observed_at, field_name="observed_at")
        if self.observed_at < self.horizon_ended_at:
            raise ValueError("observed_at cannot predate the realized horizon")
        for field_name in (
            "decision_to_horizon_return",
            "implementation_to_horizon_return",
            "cash_return",
            "benchmark_return",
            "passive_portfolio_return",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "actual_implementation_cost_return",
            _finite(
                self.actual_implementation_cost_return,
                field_name="actual_implementation_cost_return",
                minimum=0.0,
            ),
        )
        if not isinstance(self.alternative_returns, tuple) or not all(
            isinstance(item, AlternativeRealizedReturn)
            for item in self.alternative_returns
        ):
            raise TypeError(
                "alternative_returns must contain AlternativeRealizedReturn values"
            )
        identifiers = tuple(
            item.alternative_identifier for item in self.alternative_returns
        )
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("alternative realized returns must be unique")
        object.__setattr__(
            self,
            "source_identifiers",
            _text_tuple(
                self.source_identifiers,
                field_name="source_identifiers",
                minimum=1,
            ),
        )


@dataclass(frozen=True, slots=True)
class DecisionReturnAttribution:
    selection: float
    sizing: float
    timing: float
    implementation_cost: float
    net_active_contribution: float

    def __post_init__(self) -> None:
        for field_name in (
            "selection",
            "sizing",
            "timing",
            "implementation_cost",
            "net_active_contribution",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(getattr(self, field_name), field_name=field_name),
            )
        reconciled = (
            self.selection
            + self.sizing
            + self.timing
            + self.implementation_cost
        )
        if abs(reconciled - self.net_active_contribution) > 0.0000001:
            raise ValueError("attribution must reconcile to net active contribution")


@dataclass(frozen=True, slots=True)
class PointInTimeDecisionEvaluation:
    identifier: str
    snapshot_identifier: str
    snapshot_fingerprint: str
    evaluated_at: datetime
    process_verdict: EvaluationProcessVerdict
    outcome: EvaluationOutcome
    candidate_return: float
    implemented_return: float
    cash_return: float
    benchmark_return: float
    passive_portfolio_return: float
    best_original_alternative_identifier: str
    best_original_alternative_return: float
    excess_return_vs_cash: float
    excess_return_vs_benchmark: float
    excess_return_vs_passive: float
    excess_return_vs_best_original_alternative: float
    attribution: DecisionReturnAttribution
    confidence_brier_score: float
    process_evidence: tuple[str, ...]
    process_failures: tuple[str, ...]
    outcome_evidence: tuple[str, ...]
    schema_version: str = "point-in-time-decision-evaluation.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "snapshot_identifier",
            "snapshot_fingerprint",
            "best_original_alternative_identifier",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.evaluated_at, field_name="evaluated_at")
        if not isinstance(self.process_verdict, EvaluationProcessVerdict):
            raise TypeError("process_verdict must be EvaluationProcessVerdict")
        if not isinstance(self.outcome, EvaluationOutcome):
            raise TypeError("outcome must be EvaluationOutcome")
        for field_name in (
            "candidate_return",
            "implemented_return",
            "cash_return",
            "benchmark_return",
            "passive_portfolio_return",
            "best_original_alternative_return",
            "excess_return_vs_cash",
            "excess_return_vs_benchmark",
            "excess_return_vs_passive",
            "excess_return_vs_best_original_alternative",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "confidence_brier_score",
            _finite(
                self.confidence_brier_score,
                field_name="confidence_brier_score",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        if not isinstance(self.attribution, DecisionReturnAttribution):
            raise TypeError("attribution must be DecisionReturnAttribution")
        for field_name, minimum in (
            ("process_evidence", 1),
            ("process_failures", 0),
            ("outcome_evidence", 1),
        ):
            object.__setattr__(
                self,
                field_name,
                _text_tuple(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=minimum,
                ),
            )
        if (
            self.process_verdict is EvaluationProcessVerdict.DISCIPLINED
            and self.process_failures
        ):
            raise ValueError("disciplined evaluations cannot contain process failures")
        if (
            self.process_verdict is EvaluationProcessVerdict.FLAWED
            and not self.process_failures
        ):
            raise ValueError("flawed evaluations require process failures")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "snapshot_identifier": self.snapshot_identifier,
            "snapshot_fingerprint": self.snapshot_fingerprint,
            "evaluated_at": self.evaluated_at.isoformat(),
            "process_verdict": self.process_verdict.value,
            "outcome": self.outcome.value,
            "candidate_return": self.candidate_return,
            "implemented_return": self.implemented_return,
            "cash_return": self.cash_return,
            "benchmark_return": self.benchmark_return,
            "passive_portfolio_return": self.passive_portfolio_return,
            "best_original_alternative_identifier": (
                self.best_original_alternative_identifier
            ),
            "best_original_alternative_return": (
                self.best_original_alternative_return
            ),
            "excess_return_vs_cash": self.excess_return_vs_cash,
            "excess_return_vs_benchmark": self.excess_return_vs_benchmark,
            "excess_return_vs_passive": self.excess_return_vs_passive,
            "excess_return_vs_best_original_alternative": (
                self.excess_return_vs_best_original_alternative
            ),
            "attribution": {
                "selection": self.attribution.selection,
                "sizing": self.attribution.sizing,
                "timing": self.attribution.timing,
                "implementation_cost": self.attribution.implementation_cost,
                "net_active_contribution": (
                    self.attribution.net_active_contribution
                ),
            },
            "confidence_brier_score": self.confidence_brier_score,
            "process_evidence": list(self.process_evidence),
            "process_failures": list(self.process_failures),
            "outcome_evidence": list(self.outcome_evidence),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class PointInTimeEvaluationPolicy:
    version: str = "point-in-time-evaluation.v1"
    flat_active_return_tolerance: float = 0.001

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "version",
            _required_text(self.version, field_name="version"),
        )
        object.__setattr__(
            self,
            "flat_active_return_tolerance",
            _finite(
                self.flat_active_return_tolerance,
                field_name="flat_active_return_tolerance",
                minimum=0.0,
            ),
        )


class PointInTimeDecisionEvaluator:
    """Evaluate process and outcome without allowing hindsight reconstruction."""

    def __init__(
        self,
        policy: PointInTimeEvaluationPolicy | None = None,
    ) -> None:
        self.policy = policy or PointInTimeEvaluationPolicy()

    def evaluate(
        self,
        snapshot: DecisionEvidenceSnapshot,
        realized: RealizedDecisionOutcome,
    ) -> PointInTimeDecisionEvaluation:
        if not isinstance(snapshot, DecisionEvidenceSnapshot):
            raise TypeError("snapshot must be DecisionEvidenceSnapshot")
        if not isinstance(realized, RealizedDecisionOutcome):
            raise TypeError("realized must be RealizedDecisionOutcome")
        if realized.snapshot_identifier != snapshot.identifier:
            raise ValueError("realized outcome does not match snapshot")
        if realized.horizon_ended_at <= snapshot.decision_as_of:
            raise ValueError("realized horizon must end after the decision")
        expected_alternative_ids = {
            item.identifier for item in snapshot.alternatives
        }
        observed_alternative_ids = {
            item.alternative_identifier for item in realized.alternative_returns
        }
        if observed_alternative_ids != expected_alternative_ids:
            missing = sorted(expected_alternative_ids - observed_alternative_ids)
            extra = sorted(observed_alternative_ids - expected_alternative_ids)
            raise ValueError(
                "realized alternatives must exactly match the original capital set; "
                f"missing={missing}, extra={extra}"
            )
        realized_map = {
            item.alternative_identifier: item.realized_return
            for item in realized.alternative_returns
        }
        best_identifier, best_return = max(
            realized_map.items(),
            key=lambda item: (item[1], item[0]),
        )
        recommended = snapshot.recommended_position_weight
        if recommended is None:
            recommended = snapshot.current_portfolio_weight
        implemented = snapshot.implemented_position_weight
        active_spread_at_decision = (
            realized.decision_to_horizon_return - best_return
        )
        selection = recommended * active_spread_at_decision
        sizing = (implemented - recommended) * active_spread_at_decision
        timing = implemented * (
            realized.implementation_to_horizon_return
            - realized.decision_to_horizon_return
        )
        cost = -realized.actual_implementation_cost_return
        net_active = selection + sizing + timing + cost
        attribution = DecisionReturnAttribution(
            selection=selection,
            sizing=sizing,
            timing=timing,
            implementation_cost=cost,
            net_active_contribution=net_active,
        )
        implemented_return = (
            implemented * realized.implementation_to_horizon_return
            - realized.actual_implementation_cost_return
        )
        active_tolerance = self.policy.flat_active_return_tolerance
        if implemented <= 0.0:
            outcome = EvaluationOutcome.NOT_IMPLEMENTED
        elif net_active > active_tolerance:
            outcome = EvaluationOutcome.VALUE_ADDED
        elif net_active < -active_tolerance:
            outcome = EvaluationOutcome.VALUE_DESTROYED
        else:
            outcome = EvaluationOutcome.MATCHED_ALTERNATIVE

        process_evidence = (
            "Every original use of capital is preserved in the snapshot",
            "All evidence references were available by the decision timestamp",
            "Five independent specialist roles are preserved",
            "Model, policy, and code versions are immutable",
            "Portfolio implementation status and costs are captured",
            "Implemented ownership is linked to an explicit monitored thesis",
        )
        process_failures: list[str] = []
        if snapshot.evidence_vetoes and snapshot.action not in {
            CIOAction.INSUFFICIENT_EVIDENCE,
            CIOAction.WATCH,
        }:
            process_failures.append("CIO action ignored an evidence veto")
        if snapshot.implementation_blocks and implemented > snapshot.current_portfolio_weight:
            process_failures.append(
                "portfolio exposure increased despite implementation blocks"
            )
        if snapshot.action in {
            CIOAction.BUY,
            CIOAction.INCREASE,
        } and implemented > 0.0 and snapshot.thesis_identifier is None:
            process_failures.append("implemented ownership lacks an explicit thesis")
        if snapshot.best_expected_alternative.net_expected_return > (
            snapshot.expected_return
            - snapshot.estimated_implementation_cost_return
            + 0.0000001
        ) and snapshot.action in {CIOAction.BUY, CIOAction.INCREASE}:
            process_failures.append(
                "approved candidate did not exceed the strongest expected alternative"
            )
        verdict = (
            EvaluationProcessVerdict.FLAWED
            if process_failures
            else EvaluationProcessVerdict.DISCIPLINED
        )
        success = 1.0 if net_active > 0.0 else 0.0
        brier = (snapshot.probability_of_success - success) ** 2
        outcome_evidence = (
            f"candidate decision-to-horizon return={realized.decision_to_horizon_return:.6f}",
            f"candidate implementation-to-horizon return={realized.implementation_to_horizon_return:.6f}",
            f"best original alternative={best_identifier}:{best_return:.6f}",
            f"cash return={realized.cash_return:.6f}",
            f"benchmark return={realized.benchmark_return:.6f}",
            f"passive portfolio return={realized.passive_portfolio_return:.6f}",
            *(
                f"outcome source={identifier}"
                for identifier in realized.source_identifiers
            ),
        )
        return PointInTimeDecisionEvaluation(
            identifier=(
                f"decision-evaluation:{snapshot.decision_identifier}:"
                f"{realized.horizon_ended_at.isoformat()}"
            ),
            snapshot_identifier=snapshot.identifier,
            snapshot_fingerprint=snapshot.fingerprint,
            evaluated_at=realized.observed_at,
            process_verdict=verdict,
            outcome=outcome,
            candidate_return=realized.decision_to_horizon_return,
            implemented_return=implemented_return,
            cash_return=realized.cash_return,
            benchmark_return=realized.benchmark_return,
            passive_portfolio_return=realized.passive_portfolio_return,
            best_original_alternative_identifier=best_identifier,
            best_original_alternative_return=best_return,
            excess_return_vs_cash=(
                realized.implementation_to_horizon_return - realized.cash_return
            ),
            excess_return_vs_benchmark=(
                realized.implementation_to_horizon_return
                - realized.benchmark_return
            ),
            excess_return_vs_passive=(
                realized.implementation_to_horizon_return
                - realized.passive_portfolio_return
            ),
            excess_return_vs_best_original_alternative=(
                realized.implementation_to_horizon_return - best_return
            ),
            attribution=attribution,
            confidence_brier_score=brier,
            process_evidence=process_evidence,
            process_failures=tuple(process_failures),
            outcome_evidence=outcome_evidence,
        )


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    lower_bound: float
    upper_bound: float
    count: int
    mean_confidence: float
    observed_success_rate: float
    mean_brier_score: float

    def __post_init__(self) -> None:
        for field_name in ("lower_bound", "upper_bound"):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                    maximum=1.0,
                ),
            )
        if self.lower_bound >= self.upper_bound:
            raise ValueError("calibration bucket lower bound must be below upper")
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise TypeError("count must be an integer")
        if self.count < 1:
            raise ValueError("calibration buckets cannot be empty")
        for field_name in (
            "mean_confidence",
            "observed_success_rate",
            "mean_brier_score",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                    maximum=1.0,
                ),
            )


@dataclass(frozen=True, slots=True)
class ConfidenceCalibrationReport:
    as_of: datetime
    count: int
    mean_brier_score: float
    calibration_error: float
    buckets: tuple[CalibrationBucket, ...]
    policy_version: str = "confidence-calibration.v1"

    def __post_init__(self) -> None:
        _aware(self.as_of, field_name="as_of")
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise TypeError("count must be an integer")
        if self.count < 1:
            raise ValueError("calibration requires at least one evaluation")
        for field_name in ("mean_brier_score", "calibration_error"):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                    maximum=1.0,
                ),
            )
        if not isinstance(self.buckets, tuple) or not all(
            isinstance(item, CalibrationBucket) for item in self.buckets
        ):
            raise TypeError("buckets must contain CalibrationBucket values")
        if sum(item.count for item in self.buckets) != self.count:
            raise ValueError("bucket counts must reconcile to report count")
        object.__setattr__(
            self,
            "policy_version",
            _required_text(self.policy_version, field_name="policy_version"),
        )


class ConfidenceCalibrator:
    """Aggregate frozen decision confidence against realized active outcomes."""

    def build(
        self,
        pairs: tuple[
            tuple[DecisionEvidenceSnapshot, PointInTimeDecisionEvaluation], ...
        ],
        *,
        as_of: datetime,
        bucket_width: float = 0.10,
    ) -> ConfidenceCalibrationReport:
        _aware(as_of, field_name="as_of")
        if not isinstance(pairs, tuple) or not pairs:
            raise ValueError("calibration requires snapshot/evaluation pairs")
        width = _finite(
            bucket_width,
            field_name="bucket_width",
            minimum=0.01,
            maximum=1.0,
        )
        grouped: dict[int, list[tuple[float, float, float]]] = {}
        for snapshot, evaluation in pairs:
            if not isinstance(snapshot, DecisionEvidenceSnapshot):
                raise TypeError("calibration snapshots are invalid")
            if not isinstance(evaluation, PointInTimeDecisionEvaluation):
                raise TypeError("calibration evaluations are invalid")
            if evaluation.snapshot_identifier != snapshot.identifier:
                raise ValueError("calibration pair identifiers do not match")
            index = min(int(snapshot.final_confidence / width), int(1.0 / width) - 1)
            success = (
                1.0
                if evaluation.outcome is EvaluationOutcome.VALUE_ADDED
                else 0.0
            )
            grouped.setdefault(index, []).append(
                (
                    snapshot.final_confidence,
                    success,
                    evaluation.confidence_brier_score,
                )
            )
        buckets: list[CalibrationBucket] = []
        weighted_error = 0.0
        total = len(pairs)
        for index in sorted(grouped):
            values = grouped[index]
            count = len(values)
            mean_confidence = sum(item[0] for item in values) / count
            success_rate = sum(item[1] for item in values) / count
            mean_brier = sum(item[2] for item in values) / count
            lower = index * width
            upper = min(1.0, lower + width)
            buckets.append(
                CalibrationBucket(
                    lower_bound=lower,
                    upper_bound=upper,
                    count=count,
                    mean_confidence=mean_confidence,
                    observed_success_rate=success_rate,
                    mean_brier_score=mean_brier,
                )
            )
            weighted_error += count / total * abs(mean_confidence - success_rate)
        return ConfidenceCalibrationReport(
            as_of=as_of,
            count=total,
            mean_brier_score=(
                sum(item[1].confidence_brier_score for item in pairs) / total
            ),
            calibration_error=weighted_error,
            buckets=tuple(buckets),
        )


__all__ = [
    "AlternativeRealizedReturn",
    "CalibrationBucket",
    "CapitalAlternativeSnapshot",
    "ConfidenceCalibrationReport",
    "ConfidenceCalibrator",
    "DecisionEvidenceSnapshot",
    "DecisionReturnAttribution",
    "EvaluationOutcome",
    "EvaluationProcessVerdict",
    "EvidenceReference",
    "PointInTimeDecisionEvaluation",
    "PointInTimeDecisionEvaluator",
    "PointInTimeEvaluationPolicy",
    "RealizedDecisionOutcome",
]
