"""Explicit CIO authority for cycles with no candidate-level review queue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cio.models import CIOAction


_EVIDENCE_OR_AUTHORITY_TERMS = (
    "evidence",
    "stale",
    "missing",
    "incomplete",
    "unavailable",
    "uncertified",
    "unapproved",
    "coverage",
    "provider",
    "integrity",
    "operational",
    "capability",
    "authority",
    "outside the exact configured",
    "intelligence-only",
)


@dataclass(frozen=True, slots=True)
class CIOCycleDisposition:
    identifier: str
    as_of: datetime
    action: CIOAction
    classification: str
    rationale: str
    primary_reason: str
    contributing_reasons: tuple[str, ...]
    authority: str = "CHIEF_INVESTMENT_OFFICER"
    policy_version: str = "cio-empty-queue-disposition.v1"

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

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "action": self.action.value,
            "classification": self.classification,
            "rationale": self.rationale,
            "primary_reason": self.primary_reason,
            "contributing_reasons": list(self.contributing_reasons),
            "authority": self.authority,
            "policy_version": self.policy_version,
        }


class CIOCycleDispositionAuthority:
    """Issue the final CIO no-action record when no candidate reaches committee."""

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
        ) or ("No decision-complete candidate reached the CIO review queue",)
        evidence_or_authority_block = any(
            term in reason.lower()
            for reason in reasons
            for term in _EVIDENCE_OR_AUTHORITY_TERMS
        )
        if evidence_or_authority_block:
            action = CIOAction.INSUFFICIENT_EVIDENCE
            classification = "evidence_or_authority_block"
            rationale = (
                "The CIO cannot conclude that cash or current holdings are superior "
                "because the complete opportunity set did not reach decision-ready review."
            )
        else:
            action = CIOAction.NO_SUPERIOR_OPPORTUNITY
            classification = "economically_unqualified"
            rationale = (
                "The CIO reviewed the completed qualification record and found no "
                "candidate that clears the governed return, downside, liquidity, cost, "
                "and opportunity hurdles."
            )
        return CIOCycleDisposition(
            identifier=f"cio-cycle-disposition:{queue.context_identifier}:{as_of.isoformat()}",
            as_of=as_of,
            action=action,
            classification=classification,
            rationale=rationale,
            primary_reason=reasons[0],
            contributing_reasons=reasons,
        )


__all__ = ["CIOCycleDisposition", "CIOCycleDispositionAuthority"]
