"""Committee submission and institutional market decision contracts.

This module deliberately stops at institutional judgment. It does not create a
portfolio proposal, personalized action, order, or transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Any, Iterable, Mapping


class CommitteeOutcome(str, Enum):
    APPROVE = "approve"
    APPROVE_WITH_CONSTRAINTS = "approve_with_constraints"
    MONITOR = "monitor"
    NO_ACTION = "no_action"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"
    REJECT = "reject"
    VETOED = "vetoed"


class MarketStance(str, Enum):
    CONSTRUCTIVE = "constructive"
    CONSTRUCTIVE_SELECTIVE = "constructive_but_selective"
    NEUTRAL = "neutral"
    DEFENSIVE = "defensive"
    UNAVAILABLE = "decision_unavailable"


@dataclass(frozen=True, slots=True)
class CommitteeMemberAssessment:
    member: str
    outcome: CommitteeOutcome
    confidence: int
    rationale: str
    constraints: tuple[str, ...] = ()
    dissent: bool = False

    def __post_init__(self) -> None:
        if not self.member.strip():
            raise ValueError("member is required")
        if not 0 <= self.confidence <= 100:
            raise ValueError("confidence must be between 0 and 100")
        if not self.rationale.strip():
            raise ValueError("rationale is required")


@dataclass(frozen=True, slots=True)
class InstitutionalMarketDecision:
    identifier: str
    as_of: datetime
    governance_identifier: str
    governance_policy_version: str
    outcome: CommitteeOutcome
    stance: MarketStance
    opportunity_score: int | None
    risk_score: int | None
    confidence_score: int | None
    data_quality_score: int | None
    constraints: tuple[str, ...]
    dissent: tuple[str, ...]
    resolution_conditions: tuple[str, ...]
    review_triggers: tuple[str, ...]
    member_assessments: tuple[CommitteeMemberAssessment, ...]
    committee_submitted: bool = True
    personal_cio_action_affected: bool = False
    capital_intelligence_score_affected: bool = False
    portfolio_mutation_authority: bool = False
    transaction_authority: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "institutional-market-decision.v1",
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "governance_identifier": self.governance_identifier,
            "governance_policy_version": self.governance_policy_version,
            "outcome": self.outcome.value,
            "stance": self.stance.value,
            "opportunity_score": self.opportunity_score,
            "risk_score": self.risk_score,
            "confidence_score": self.confidence_score,
            "data_quality_score": self.data_quality_score,
            "constraints": list(self.constraints),
            "dissent": list(self.dissent),
            "resolution_conditions": list(self.resolution_conditions),
            "review_triggers": list(self.review_triggers),
            "member_assessments": [
                {
                    "member": item.member,
                    "outcome": item.outcome.value,
                    "confidence": item.confidence,
                    "rationale": item.rationale,
                    "constraints": list(item.constraints),
                    "dissent": item.dissent,
                }
                for item in self.member_assessments
            ],
            "committee_submitted": self.committee_submitted,
            "personal_cio_action_affected": self.personal_cio_action_affected,
            "capital_intelligence_score_affected": self.capital_intelligence_score_affected,
            "portfolio_mutation_authority": self.portfolio_mutation_authority,
            "transaction_authority": self.transaction_authority,
        }


class CommitteeSubmissionService:
    """Turn one governed evidence result into one replayable committee decision."""

    def submit(
        self,
        governance: Mapping[str, Any],
        assessments: Iterable[CommitteeMemberAssessment],
    ) -> InstitutionalMarketDecision:
        members = tuple(assessments)
        if not members:
            raise ValueError("at least one committee assessment is required")
        identifier = str(governance.get("identifier", "")).strip()
        policy_version = str(governance.get("policy_version", "")).strip()
        as_of_raw = governance.get("as_of")
        if not identifier or not policy_version or not isinstance(as_of_raw, str):
            raise ValueError("governance identifier, policy_version, and as_of are required")
        as_of = datetime.fromisoformat(as_of_raw)
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("governance as_of must be timezone-aware")

        status = str(governance.get("status", "decision_unavailable"))
        opportunity = _optional_score(governance.get("aggregate_opportunity_score"))
        risk = _optional_score(governance.get("aggregate_risk_score"))
        confidence = _optional_score(
            governance.get(
                "governed_confidence_score",
                governance.get("aggregate_confidence_score"),
            )
        )
        quality = _optional_score(governance.get("aggregate_data_quality_score"))
        active_vetoes = tuple(
            str(item.get("veto_type", item)) if isinstance(item, Mapping) else str(item)
            for item in governance.get("active_vetoes", ())
        )
        issues = tuple(
            str(item.get("issue_type", item)) if isinstance(item, Mapping) else str(item)
            for item in governance.get("issues", ())
        )

        outcome, stance, base_constraints = self._classify(
            status=status,
            opportunity=opportunity,
            risk=risk,
            active_vetoes=active_vetoes,
        )
        member_constraints = tuple(
            constraint for member in members for constraint in member.constraints
        )
        constraints = _dedupe(base_constraints + active_vetoes + member_constraints)
        dissent = tuple(
            f"{member.member}: {member.rationale}"
            for member in members
            if member.dissent or member.outcome is not outcome
        )
        resolution = self._resolution_conditions(status, active_vetoes, issues)
        triggers = _dedupe(
            (
                "material change in any normalized engine assessment",
                "governance confidence crosses a policy threshold",
                "an active veto is added or resolved",
            )
            + tuple(f"resolve {item}" for item in issues)
        )
        digest = sha256(
            (
                f"{identifier}|{policy_version}|{as_of.isoformat()}|"
                f"{outcome.value}|{','.join(item.member for item in members)}"
            ).encode()
        ).hexdigest()[:20]
        return InstitutionalMarketDecision(
            identifier=f"institutional-market-decision:{digest}",
            as_of=as_of,
            governance_identifier=identifier,
            governance_policy_version=policy_version,
            outcome=outcome,
            stance=stance,
            opportunity_score=opportunity,
            risk_score=risk,
            confidence_score=confidence,
            data_quality_score=quality,
            constraints=constraints,
            dissent=dissent,
            resolution_conditions=resolution,
            review_triggers=triggers,
            member_assessments=members,
        )

    @staticmethod
    def _classify(
        *,
        status: str,
        opportunity: int | None,
        risk: int | None,
        active_vetoes: tuple[str, ...],
    ) -> tuple[CommitteeOutcome, MarketStance, tuple[str, ...]]:
        if status == "decision_unavailable" or opportunity is None or risk is None:
            return (
                CommitteeOutcome.REQUEST_MORE_EVIDENCE,
                MarketStance.UNAVAILABLE,
                ("no institutional stance until evidence clears hard minimums",),
            )
        if status == "vetoed" or active_vetoes:
            return (
                CommitteeOutcome.VETOED,
                MarketStance.DEFENSIVE,
                ("high-conviction positive conclusions are blocked by active veto",),
            )
        if status == "conflicted":
            return (
                CommitteeOutcome.MONITOR,
                MarketStance.NEUTRAL,
                ("material disagreement requires explicit committee resolution",),
            )
        if risk >= 70:
            return (
                CommitteeOutcome.NO_ACTION,
                MarketStance.DEFENSIVE,
                ("risk pressure is too high for a constructive institutional stance",),
            )
        if opportunity >= 65 and risk < 55:
            return CommitteeOutcome.APPROVE, MarketStance.CONSTRUCTIVE, ()
        if opportunity >= 55 and risk < 70:
            return (
                CommitteeOutcome.APPROVE_WITH_CONSTRAINTS,
                MarketStance.CONSTRUCTIVE_SELECTIVE,
                ("new risk-taking requires selective confirmation",),
            )
        return CommitteeOutcome.MONITOR, MarketStance.NEUTRAL, ()

    @staticmethod
    def _resolution_conditions(
        status: str,
        vetoes: tuple[str, ...],
        issues: tuple[str, ...],
    ) -> tuple[str, ...]:
        values: list[str] = []
        if status == "decision_unavailable":
            values.append("restore minimum evidence coverage, confidence, and data quality")
        if status == "conflicted":
            values.append("resolve material supportive and adverse evidence disagreement")
        values.extend(f"resolve veto: {item}" for item in vetoes)
        values.extend(f"resolve issue: {item}" for item in issues)
        return _dedupe(tuple(values))


def _optional_score(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise ValueError("scores must be integer values between 0 and 100")
    return value


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in values if item.strip()))
