"""Advisory committee challenge, disagreement, and input-depth diagnostics.

This module runs after the six independent specialist analyses and before the CIO
service is invoked.  Its output is deliberately non-authoritative: it cannot remove a
candidate from the queue, create an evidence veto, change qualification thresholds,
change a position size, or issue an investment action.  It exists to make the CIO's
information package more adversarial and more explicit without suppressing viable
opportunities.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from cio.adversarial_challenge import (
    AdversarialCIOChallengeEngine,
    ChallengePackage,
    CommitteeChallengeProposal,
)
from cio.committee import IndependentSpecialistPacket
from cio.models import (
    CapitalAlternativeComparison,
    CandidateDecisionRecord,
    SpecialistPosition,
    SpecialistRole,
)


def _unique(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.strip()
            for group in groups
            for item in group
            if isinstance(item, str) and item.strip()
        )
    )


@dataclass(frozen=True, slots=True)
class SpecialistInputDepth:
    """Descriptive evidence depth for one specialist; never a qualification gate."""

    role: SpecialistRole
    supporting_evidence_count: int
    contradictory_evidence_count: int
    assumption_count: int
    risk_count: int
    change_condition_count: int
    evidence_origin_count: int
    historical_calibration_present: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "supporting_evidence_count": self.supporting_evidence_count,
            "contradictory_evidence_count": self.contradictory_evidence_count,
            "assumption_count": self.assumption_count,
            "risk_count": self.risk_count,
            "change_condition_count": self.change_condition_count,
            "evidence_origin_count": self.evidence_origin_count,
            "historical_calibration_present": self.historical_calibration_present,
            "minimum_required_for_candidate_qualification": None,
        }


@dataclass(frozen=True, slots=True)
class CommitteeDisagreementMap:
    """Explain disagreement and evidence overlap without converting them into vetoes."""

    role_positions: tuple[tuple[SpecialistRole, SpecialistPosition], ...]
    opposing_roles: tuple[SpecialistRole, ...]
    abstaining_roles: tuple[SpecialistRole, ...]
    confidence_dispersion: float
    evidence_independence_ratio: float
    effective_directional_count: float
    evidence_clusters: tuple[tuple[SpecialistRole, ...], ...]
    shared_assumptions: tuple[str, ...]
    input_depth: tuple[SpecialistInputDepth, ...]
    historical_learning_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_positions": [
                {"role": role.value, "position": position.value}
                for role, position in self.role_positions
            ],
            "opposing_roles": [item.value for item in self.opposing_roles],
            "abstaining_roles": [item.value for item in self.abstaining_roles],
            "confidence_dispersion": self.confidence_dispersion,
            "evidence_independence_ratio": self.evidence_independence_ratio,
            "effective_directional_count": self.effective_directional_count,
            "evidence_clusters": [
                [role.value for role in cluster] for cluster in self.evidence_clusters
            ],
            "shared_assumptions": list(self.shared_assumptions),
            "input_depth": [item.to_dict() for item in self.input_depth],
            "historical_learning_status": self.historical_learning_status,
            "advisory_only": True,
        }


@dataclass(frozen=True, slots=True)
class CommitteeAdvisoryReport:
    """Pre-CIO challenge package that is structurally unable to restrict a candidate."""

    candidate_identifier: str
    challenge: ChallengePackage
    disagreement: CommitteeDisagreementMap
    stage: str = "after_six_specialists_before_cio"
    schema_version: str = "committee-advisory.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_identifier": self.candidate_identifier,
            "stage": self.stage,
            "challenge": self.challenge.to_dict(),
            "disagreement": self.disagreement.to_dict(),
            "advisory_only": True,
            "can_authorize_action": False,
            "can_veto_action": False,
            "can_create_evidence_veto": False,
            "can_change_candidate_qualification": False,
            "can_remove_candidate": False,
            "can_change_position_size": False,
            "can_change_cash_hurdle": False,
            "can_change_policy_thresholds": False,
        }


def _shared_assumptions(specialists: IndependentSpecialistPacket) -> tuple[str, ...]:
    assumptions = [
        assumption.strip()
        for analysis in specialists.analyses
        for assumption in analysis.critical_assumptions
        if assumption.strip()
    ]
    counts = Counter(assumptions)
    return tuple(sorted(item for item, count in counts.items() if count > 1))


def _input_depth(
    specialists: IndependentSpecialistPacket,
) -> tuple[SpecialistInputDepth, ...]:
    historical_status = getattr(specialists.historical_learning, "status", None)
    historical_value = str(getattr(historical_status, "value", historical_status or ""))
    calibrated = historical_value in {"available", "limited"}
    return tuple(
        SpecialistInputDepth(
            role=analysis.role,
            supporting_evidence_count=len(analysis.supporting_evidence),
            contradictory_evidence_count=len(analysis.contradictory_evidence),
            assumption_count=len(analysis.critical_assumptions),
            risk_count=len(analysis.risks),
            change_condition_count=len(analysis.change_conditions),
            evidence_origin_count=len(analysis.evidence_origin_identifiers),
            historical_calibration_present=calibrated,
        )
        for analysis in specialists.analyses
    )


def _challenge_proposal(
    candidate: CandidateDecisionRecord,
    specialists: IndependentSpecialistPacket,
    *,
    capital_comparison: CapitalAlternativeComparison | None,
) -> CommitteeChallengeProposal:
    supportive = tuple(
        item
        for item in specialists.directional_analyses
        if item.position is SpecialistPosition.SUPPORTIVE
    )
    opposition = tuple(
        item
        for item in specialists.directional_analyses
        if item.position in {SpecialistPosition.OPPOSED, SpecialistPosition.ABSTAIN}
    )
    supporting = _unique(
        candidate.supporting_evidence,
        tuple(item.conclusion for item in supportive),
        tuple(
            evidence
            for item in supportive
            for evidence in item.supporting_evidence
        ),
    )
    opposing = _unique(
        candidate.contradictory_evidence,
        tuple(item.conclusion for item in opposition),
        tuple(
            evidence
            for item in specialists.analyses
            for evidence in item.contradictory_evidence
        ),
        tuple(risk for item in opposition for risk in item.risks),
        tuple(limit for item in opposition for limit in item.limitations),
    )
    assumptions = _unique(
        candidate.critical_assumptions,
        tuple(
            assumption
            for item in specialists.analyses
            for assumption in item.critical_assumptions
        ),
    )
    cash_case = (
        (
            f"Candidate net expected return={candidate.net_expected_return:.2%}; "
            f"current opportunity-cost hurdle={candidate.opportunity_cost_return:.2%}."
        ),
    )
    replacement: tuple[str, ...] = ()
    if capital_comparison is not None:
        cash_case = _unique(
            cash_case,
            (
                f"Best available alternative={capital_comparison.best_alternative_identifier}; "
                f"effective opportunity cost={capital_comparison.effective_opportunity_cost:.2%}.",
            ),
        )
        replacement = (
            f"Compare directly with {capital_comparison.best_alternative_identifier} "
            f"({capital_comparison.best_alternative_kind}) at an effective return hurdle "
            f"of {capital_comparison.effective_opportunity_cost:.2%}.",
        )
    tail_risks = _unique(
        candidate.key_risks,
        tuple(risk for item in specialists.analyses for risk in item.risks),
        (
            f"Governed bear-case return is {candidate.bear_case_return:.2%} over "
            f"{candidate.decision_horizon_days} days.",
        ),
    )
    rationale = _unique(
        (
            f"Candidate net expected return is {candidate.net_expected_return:.2%} with "
            f"probability of success {candidate.probability_of_success:.0%}.",
        ),
        candidate.primary_catalysts,
    )
    return CommitteeChallengeProposal(
        identifier=f"pre-cio-challenge:{candidate.identifier}:{candidate.as_of.isoformat()}",
        as_of=candidate.as_of,
        rationale=rationale,
        supporting_evidence=supporting,
        opposing_evidence=opposing,
        hidden_assumptions=assumptions,
        cash_case_evidence=cash_case,
        replacement_evidence=replacement,
        tail_risks=tail_risks,
    )


def build_committee_advisory_report(
    candidate: CandidateDecisionRecord,
    specialists: IndependentSpecialistPacket,
    *,
    capital_comparison: CapitalAlternativeComparison | None = None,
    challenge_engine: AdversarialCIOChallengeEngine | None = None,
) -> CommitteeAdvisoryReport:
    """Build a descriptive Red Team package without changing committee authority."""

    if not isinstance(candidate, CandidateDecisionRecord):
        raise TypeError("candidate must be CandidateDecisionRecord")
    if not isinstance(specialists, IndependentSpecialistPacket):
        raise TypeError("specialists must be IndependentSpecialistPacket")
    specialists.validate_against(candidate)
    if capital_comparison is not None and not isinstance(
        capital_comparison, CapitalAlternativeComparison
    ):
        raise TypeError("capital_comparison must be CapitalAlternativeComparison or None")
    if (
        capital_comparison is not None
        and capital_comparison.candidate_identifier != candidate.identifier
    ):
        raise ValueError("capital comparison does not match candidate")

    independence = specialists.evidence_independence
    active_confidence = tuple(
        item.confidence
        for item in specialists.directional_analyses
        if item.position is not SpecialistPosition.ABSTAIN
    )
    dispersion = (
        0.0
        if not active_confidence
        else round(max(active_confidence) - min(active_confidence), 8)
    )
    historical_status = getattr(specialists.historical_learning, "status", None)
    historical_value = str(
        getattr(historical_status, "value", historical_status or "unavailable")
    )
    disagreement = CommitteeDisagreementMap(
        role_positions=tuple(
            (item.role, item.position) for item in specialists.analyses
        ),
        opposing_roles=tuple(item.role for item in specialists.opposing),
        abstaining_roles=tuple(item.role for item in specialists.abstentions),
        confidence_dispersion=dispersion,
        evidence_independence_ratio=specialists.evidence_independence_ratio,
        effective_directional_count=specialists.effective_directional_count,
        evidence_clusters=independence.cluster_roles,
        shared_assumptions=_shared_assumptions(specialists),
        input_depth=_input_depth(specialists),
        historical_learning_status=historical_value,
    )
    proposal = _challenge_proposal(
        candidate,
        specialists,
        capital_comparison=capital_comparison,
    )
    challenge = (challenge_engine or AdversarialCIOChallengeEngine()).challenge_committee(
        proposal
    )
    return CommitteeAdvisoryReport(
        candidate_identifier=candidate.identifier,
        challenge=challenge,
        disagreement=disagreement,
    )


__all__ = [
    "CommitteeAdvisoryReport",
    "CommitteeDisagreementMap",
    "SpecialistInputDepth",
    "build_committee_advisory_report",
]
