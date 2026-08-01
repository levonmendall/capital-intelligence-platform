"""Explicit CIO authority for cycles with no candidate-level review queue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from cio.models import CIOAction


class QualificationReasonCategory(str, Enum):
    """Typed governance meaning of an opportunity-qualification rejection."""

    EVIDENCE_OR_AUTHORITY = "evidence_or_authority"
    ECONOMIC_RETURN = "economic_return"
    DOWNSIDE_OR_TAIL_RISK = "downside_or_tail_risk"
    LIQUIDITY_OR_COST = "liquidity_or_cost"
    ROBUSTNESS = "robustness"
    OPERATIONAL = "operational"
    UNCLASSIFIED = "unclassified"


_CANONICAL_REASON_CATEGORIES = {
    "recorded candidate opportunity cost does not match the point-in-time opportunity set baseline alternatives": QualificationReasonCategory.EVIDENCE_OR_AUTHORITY,
    "aggregate evidence quality is below threshold": QualificationReasonCategory.EVIDENCE_OR_AUTHORITY,
    "at least one evidence-quality dimension is below threshold": QualificationReasonCategory.EVIDENCE_OR_AUTHORITY,
    "candidate liquidity is below threshold": QualificationReasonCategory.LIQUIDITY_OR_COST,
    "horizon-normalized evidence-adjusted expected return is below the full-conviction threshold": QualificationReasonCategory.ECONOMIC_RETURN,
    "horizon-normalized opportunity edge is below the full-conviction margin": QualificationReasonCategory.ECONOMIC_RETURN,
    "expected downside exceeds the qualification limit": QualificationReasonCategory.DOWNSIDE_OR_TAIL_RISK,
    "scenario-derived probability of outperforming the best alternative is below the full-conviction threshold": QualificationReasonCategory.ECONOMIC_RETURN,
    "implementation costs exceed the qualification limit": QualificationReasonCategory.LIQUIDITY_OR_COST,
    "horizon-normalized expected return does not clearly exceed the best capital alternative": QualificationReasonCategory.ECONOMIC_RETURN,
    "scenario ordering must satisfy bear case <= base case <= bull case": QualificationReasonCategory.ROBUSTNESS,
    "at least one scenario produces non-positive portfolio wealth at the reference weight": QualificationReasonCategory.ROBUSTNESS,
    "evidence-adjusted geometric return does not clear the best alternative by the required margin": QualificationReasonCategory.ROBUSTNESS,
    "the candidate loses its opportunity edge after an adverse scenario-probability shift": QualificationReasonCategory.ROBUSTNESS,
    "the robust opportunity edge is too small relative to scenario uncertainty": QualificationReasonCategory.ROBUSTNESS,
    "scenario-implied probability of loss exceeds policy": QualificationReasonCategory.DOWNSIDE_OR_TAIL_RISK,
    "stated probability of success is inconsistent with the disclosed scenarios": QualificationReasonCategory.ROBUSTNESS,
    "worst-case portfolio loss at the reference weight exceeds policy": QualificationReasonCategory.DOWNSIDE_OR_TAIL_RISK,
    "average daily dollar volume is below the recommendation liquidity floor": QualificationReasonCategory.LIQUIDITY_OR_COST,
    "market data is older than the recommendation freshness limit": QualificationReasonCategory.EVIDENCE_OR_AUTHORITY,
    "analytical coverage is below the recommendation minimum": QualificationReasonCategory.EVIDENCE_OR_AUTHORITY,
    "instrument is not a U.S. listing": QualificationReasonCategory.EVIDENCE_OR_AUTHORITY,
    "listing venue is outside the approved U.S. venue set": QualificationReasonCategory.EVIDENCE_OR_AUTHORITY,
    "cash-equivalent recommendation is not identified as a U.S. Treasury equivalent": QualificationReasonCategory.EVIDENCE_OR_AUTHORITY,
    "Treasury-equivalent duration is unavailable": QualificationReasonCategory.EVIDENCE_OR_AUTHORITY,
    "Treasury-equivalent duration exceeds the short-duration limit": QualificationReasonCategory.EVIDENCE_OR_AUTHORITY,
}

_EVIDENCE_AUTHORITY_PREFIXES = (
    "instrument is intelligence-only because ",
    "intelligence-only: ",
)
_EVIDENCE_AUTHORITY_SUFFIXES = (
    " is unclassified or outside the supported liquid public-market taxonomy",
)


def classify_qualification_reason(reason: str) -> QualificationReasonCategory:
    """Classify only known canonical reasons; unknown text fails closed."""

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("qualification reason cannot be empty")
    normalized = reason.strip()
    category = _CANONICAL_REASON_CATEGORIES.get(normalized)
    if category is not None:
        return category
    if normalized.startswith(_EVIDENCE_AUTHORITY_PREFIXES):
        return QualificationReasonCategory.EVIDENCE_OR_AUTHORITY
    if normalized.endswith(_EVIDENCE_AUTHORITY_SUFFIXES):
        return QualificationReasonCategory.EVIDENCE_OR_AUTHORITY
    return QualificationReasonCategory.UNCLASSIFIED


@dataclass(frozen=True, slots=True)
class CIOCycleDisposition:
    identifier: str
    as_of: datetime
    action: CIOAction
    classification: str
    rationale: str
    primary_reason: str
    contributing_reasons: tuple[str, ...]
    reason_categories: tuple[QualificationReasonCategory, ...]
    authority: str = "CHIEF_INVESTMENT_OFFICER"
    policy_version: str = "cio-empty-queue-disposition.v2"

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.classification.strip():
            raise ValueError("cycle disposition identifiers cannot be empty")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("cycle disposition as_of must be timezone-aware")
        if self.action not in {
            CIOAction.INSUFFICIENT_EVIDENCE,
            CIOAction.NO_SUPERIOR_OPPORTUNITY,
        }:
            raise ValueError("empty-queue disposition must be a governed no-action")
        if not self.rationale.strip() or not self.primary_reason.strip():
            raise ValueError("cycle disposition rationale cannot be empty")
        if not self.contributing_reasons:
            raise ValueError("cycle disposition requires contributing reasons")
        if (
            not isinstance(self.reason_categories, tuple)
            or len(self.reason_categories) != len(self.contributing_reasons)
            or not all(
                isinstance(item, QualificationReasonCategory)
                for item in self.reason_categories
            )
        ):
            raise ValueError(
                "reason_categories must align one-for-one with contributing_reasons"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "action": self.action.value,
            "classification": self.classification,
            "rationale": self.rationale,
            "primary_reason": self.primary_reason,
            "contributing_reasons": list(self.contributing_reasons),
            "reason_categories": [
                item.value for item in self.reason_categories
            ],
            "authority": self.authority,
            "policy_version": self.policy_version,
        }


class CIOCycleDispositionAuthority:
    """Issue the final CIO no-action record when no candidate reaches committee."""

    _ECONOMIC_CATEGORIES = frozenset(
        {
            QualificationReasonCategory.ECONOMIC_RETURN,
            QualificationReasonCategory.DOWNSIDE_OR_TAIL_RISK,
            QualificationReasonCategory.LIQUIDITY_OR_COST,
            QualificationReasonCategory.ROBUSTNESS,
        }
    )

    def decide(self, queue, *, as_of: datetime) -> CIOCycleDisposition | None:
        from opportunity.models import OpportunityQueue

        if not isinstance(queue, OpportunityQueue):
            raise TypeError("queue must be an OpportunityQueue")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if queue.ranked:
            return None
        reasons = tuple(
            dict.fromkeys(
                reason.strip()
                for rejection in queue.rejected
                for reason in rejection.reasons
                if reason.strip()
            )
        ) or (
            "Complete candidate evidence is unavailable; no candidate reached CIO review",
        )
        categories = tuple(
            classify_qualification_reason(reason) for reason in reasons
        )
        economically_complete = bool(categories) and all(
            category in self._ECONOMIC_CATEGORIES for category in categories
        )
        if not economically_complete:
            action = CIOAction.INSUFFICIENT_EVIDENCE
            classification = "evidence_or_authority_block"
            rationale = (
                "The CIO cannot conclude that cash or current holdings are superior "
                "because one or more qualification reasons are evidence, authority, "
                "operational, or not mapped to a governed reason category."
            )
        else:
            action = CIOAction.NO_SUPERIOR_OPPORTUNITY
            classification = "economically_unqualified"
            rationale = (
                "The CIO reviewed the completed qualification record and found no "
                "candidate that clears the governed return, downside, liquidity, cost, "
                "and robustness hurdles."
            )
        return CIOCycleDisposition(
            identifier=(
                f"cio-cycle-disposition:{queue.context_identifier}:{as_of.isoformat()}"
            ),
            as_of=as_of,
            action=action,
            classification=classification,
            rationale=rationale,
            primary_reason=reasons[0],
            contributing_reasons=reasons,
            reason_categories=categories,
        )


__all__ = [
    "CIOCycleDisposition",
    "CIOCycleDispositionAuthority",
    "QualificationReasonCategory",
    "classify_qualification_reason",
]
