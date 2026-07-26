"""Living investment-thesis contracts for continuous monitoring."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from math import isfinite

from cio import CIOAction, CIODecision, CandidateDecisionRecord, ThesisState


class ThesisReviewProposal(str, Enum):
    """Monitoring proposal requiring CIO review; never a final portfolio action."""

    CONTINUE_MONITORING = "continue_monitoring"
    REVIEW_INCREASE = "review_increase"
    REVIEW_REDUCE = "review_reduce"
    REVIEW_EXIT = "review_exit"
    REVIEW_EVIDENCE = "review_evidence"
    INVALIDATE = "invalidate"


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
    return round(normalized, 8)


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
        raise ValueError(
            f"{field_name} must contain at least {minimum} item(s)"
        )
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class LivingThesis:
    """Current immutable snapshot of an append-only investment thesis."""

    identifier: str
    decision_identifier: str
    candidate_identifier: str
    asset: str
    created_at: datetime
    updated_at: datetime
    state: ThesisState
    original_rationale: str
    assumptions: tuple[str, ...]
    expected_return: float
    expected_downside: float
    horizon_days: int
    catalysts: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    monitoring_indicators: tuple[str, ...]
    initial_confidence: float
    current_confidence: float
    evidence_identifiers: tuple[str, ...]
    performance_since_approval: float
    next_review_at: datetime
    review_count: int = 0

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "decision_identifier",
            "candidate_identifier",
            "asset",
            "original_rationale",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.created_at, field_name="created_at")
        _aware(self.updated_at, field_name="updated_at")
        _aware(self.next_review_at, field_name="next_review_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot predate created_at")
        if self.next_review_at <= self.updated_at:
            raise ValueError("next_review_at must be later than updated_at")
        if not isinstance(self.state, ThesisState):
            raise TypeError("state must be a ThesisState")
        for field_name in (
            "expected_return",
            "expected_downside",
            "performance_since_approval",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(getattr(self, field_name), field_name=field_name),
            )
        for field_name in ("initial_confidence", "current_confidence"):
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
        if isinstance(self.horizon_days, bool) or not isinstance(
            self.horizon_days,
            int,
        ):
            raise TypeError("horizon_days must be an integer")
        if self.horizon_days < 1:
            raise ValueError("horizon_days must be positive")
        if isinstance(self.review_count, bool) or not isinstance(
            self.review_count,
            int,
        ):
            raise TypeError("review_count must be an integer")
        if self.review_count < 0:
            raise ValueError("review_count cannot be negative")
        for field_name, minimum in (
            ("assumptions", 1),
            ("catalysts", 1),
            ("invalidation_conditions", 1),
            ("monitoring_indicators", 1),
            ("evidence_identifiers", 1),
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

    @classmethod
    def from_decision(
        cls,
        candidate: CandidateDecisionRecord,
        decision: CIODecision,
    ) -> "LivingThesis":
        if not isinstance(candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be a CandidateDecisionRecord")
        if not isinstance(decision, CIODecision):
            raise TypeError("decision must be a CIODecision")
        if decision.candidate_identifier != candidate.identifier:
            raise ValueError("decision and candidate identifiers do not match")
        if decision.action not in {
            CIOAction.BUY,
            CIOAction.INCREASE,
            CIOAction.HOLD,
        }:
            raise ValueError(
                "only approved ownership decisions can create an active thesis"
            )
        return cls(
            identifier=f"thesis:{decision.identifier}",
            decision_identifier=decision.identifier,
            candidate_identifier=candidate.identifier,
            asset=candidate.instrument.symbol,
            created_at=decision.as_of,
            updated_at=decision.as_of,
            state=ThesisState.ACTIVE,
            original_rationale=decision.thesis,
            assumptions=decision.key_assumptions,
            expected_return=decision.expected_return,
            expected_downside=candidate.expected_downside,
            horizon_days=decision.decision_horizon_days,
            catalysts=decision.catalysts,
            invalidation_conditions=decision.invalidation_conditions,
            monitoring_indicators=decision.monitoring_indicators,
            initial_confidence=decision.final_confidence,
            current_confidence=decision.final_confidence,
            evidence_identifiers=candidate.evidence_identifiers,
            performance_since_approval=0.0,
            next_review_at=decision.review_at,
        )

    def apply(self, review: "ThesisReview") -> "LivingThesis":
        if not isinstance(review, ThesisReview):
            raise TypeError("review must be a ThesisReview")
        if review.thesis_identifier != self.identifier:
            raise ValueError("review does not match thesis")
        if review.prior_state is not self.state:
            raise ValueError("review prior_state does not match current thesis")
        if review.reviewed_at <= self.updated_at:
            raise ValueError("review must be later than the current thesis snapshot")
        return replace(
            self,
            updated_at=review.reviewed_at,
            state=review.new_state,
            expected_return=review.current_expected_return,
            expected_downside=review.current_expected_downside,
            current_confidence=review.current_confidence,
            evidence_identifiers=review.evidence_identifiers,
            performance_since_approval=review.performance_since_approval,
            next_review_at=review.next_review_at,
            review_count=self.review_count + 1,
        )


@dataclass(frozen=True, slots=True)
class ThesisEvidenceUpdate:
    """New point-in-time evidence used to challenge one active thesis."""

    thesis_identifier: str
    as_of: datetime
    expected_return: float
    expected_downside: float
    confidence: float
    evidence_identifiers: tuple[str, ...]
    strengthened_indicators: tuple[str, ...]
    weakened_indicators: tuple[str, ...]
    triggered_invalidation_conditions: tuple[str, ...]
    data_current: bool
    performance_since_approval: float
    best_replacement_expected_return: float
    next_review_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "thesis_identifier",
            _required_text(
                self.thesis_identifier,
                field_name="thesis_identifier",
            ),
        )
        _aware(self.as_of, field_name="as_of")
        _aware(self.next_review_at, field_name="next_review_at")
        if self.next_review_at <= self.as_of:
            raise ValueError("next_review_at must be later than as_of")
        for field_name in (
            "expected_return",
            "expected_downside",
            "performance_since_approval",
            "best_replacement_expected_return",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "confidence",
            _finite(
                self.confidence,
                field_name="confidence",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        if not isinstance(self.data_current, bool):
            raise TypeError("data_current must be a bool")
        for field_name, minimum in (
            ("evidence_identifiers", 1),
            ("strengthened_indicators", 0),
            ("weakened_indicators", 0),
            ("triggered_invalidation_conditions", 0),
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


@dataclass(frozen=True, slots=True)
class ThesisReview:
    """Append-only monitoring conclusion and CIO-review proposal."""

    identifier: str
    thesis_identifier: str
    reviewed_at: datetime
    prior_state: ThesisState
    new_state: ThesisState
    proposal: ThesisReviewProposal
    rationale: str
    evidence_identifiers: tuple[str, ...]
    current_expected_return: float
    expected_return_change: float
    current_expected_downside: float
    downside_change: float
    current_confidence: float
    confidence_change: float
    performance_since_approval: float
    replacement_opportunity_edge: float
    triggered_invalidation_conditions: tuple[str, ...]
    required_cio_review: bool
    next_review_at: datetime
    policy_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "thesis_identifier",
            "rationale",
            "policy_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.reviewed_at, field_name="reviewed_at")
        _aware(self.next_review_at, field_name="next_review_at")
        if self.next_review_at <= self.reviewed_at:
            raise ValueError("next_review_at must be later than reviewed_at")
        for field_name in ("prior_state", "new_state"):
            if not isinstance(getattr(self, field_name), ThesisState):
                raise TypeError(f"{field_name} must be a ThesisState")
        if not isinstance(self.proposal, ThesisReviewProposal):
            raise TypeError("proposal must be a ThesisReviewProposal")
        if not isinstance(self.required_cio_review, bool):
            raise TypeError("required_cio_review must be a bool")
        for field_name in (
            "current_expected_return",
            "expected_return_change",
            "current_expected_downside",
            "downside_change",
            "performance_since_approval",
            "replacement_opportunity_edge",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(getattr(self, field_name), field_name=field_name),
            )
        for field_name in ("current_confidence", "confidence_change"):
            value = _finite(getattr(self, field_name), field_name=field_name)
            if field_name == "current_confidence" and not 0.0 <= value <= 1.0:
                raise ValueError("current_confidence must be between 0.0 and 1.0")
            object.__setattr__(self, field_name, value)
        for field_name, minimum in (
            ("evidence_identifiers", 1),
            ("triggered_invalidation_conditions", 0),
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
        if self.proposal is ThesisReviewProposal.INVALIDATE:
            if self.new_state is not ThesisState.INVALIDATED:
                raise ValueError("invalidate proposal must transition to invalidated")
            if not self.triggered_invalidation_conditions:
                raise ValueError(
                    "invalidate proposal requires triggered invalidation conditions"
                )
        if self.proposal is not ThesisReviewProposal.CONTINUE_MONITORING:
            if not self.required_cio_review:
                raise ValueError(
                    "action-oriented thesis proposals require CIO review"
                )


__all__ = [
    "LivingThesis",
    "ThesisEvidenceUpdate",
    "ThesisReview",
    "ThesisReviewProposal",
]