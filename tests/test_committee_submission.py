from datetime import datetime, timezone

import pytest

from institutional_market.committee_submission import (
    CommitteeMemberAssessment,
    CommitteeOutcome,
    CommitteeSubmissionService,
    MarketStance,
)


AS_OF = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)


def _governance(**overrides):
    payload = {
        "identifier": "governance:1",
        "policy_version": "multi-engine-governance.v1",
        "as_of": AS_OF.isoformat(),
        "status": "cleared",
        "aggregate_opportunity_score": 72,
        "aggregate_risk_score": 42,
        "governed_confidence_score": 78,
        "aggregate_data_quality_score": 84,
        "active_vetoes": [],
        "issues": [],
    }
    payload.update(overrides)
    return payload


def _members(outcome=CommitteeOutcome.APPROVE):
    return (
        CommitteeMemberAssessment(
            member="macro",
            outcome=outcome,
            confidence=80,
            rationale="Evidence supports the governed conclusion.",
        ),
        CommitteeMemberAssessment(
            member="risk",
            outcome=outcome,
            confidence=75,
            rationale="Risk remains within the approved boundary.",
        ),
    )


def test_cleared_constructive_submission_is_replayable_and_non_executing():
    decision = CommitteeSubmissionService().submit(_governance(), _members())
    assert decision.outcome is CommitteeOutcome.APPROVE
    assert decision.stance is MarketStance.CONSTRUCTIVE
    assert decision.committee_submitted is True
    assert decision.portfolio_mutation_authority is False
    assert decision.transaction_authority is False
    assert decision.to_dict()["schema_version"] == "institutional-market-decision.v1"


def test_veto_blocks_positive_conclusion_without_creating_trade_authority():
    governance = _governance(
        status="vetoed",
        active_vetoes=[{"veto_type": "credit_stress"}],
    )
    decision = CommitteeSubmissionService().submit(
        governance,
        _members(CommitteeOutcome.VETOED),
    )
    assert decision.outcome is CommitteeOutcome.VETOED
    assert decision.stance is MarketStance.DEFENSIVE
    assert "credit_stress" in decision.constraints
    assert decision.personal_cio_action_affected is False


def test_conflict_becomes_monitor_and_preserves_dissent():
    members = (
        _members(CommitteeOutcome.MONITOR)[0],
        CommitteeMemberAssessment(
            member="risk",
            outcome=CommitteeOutcome.NO_ACTION,
            confidence=65,
            rationale="Risk evidence remains adverse.",
            dissent=True,
        ),
    )
    decision = CommitteeSubmissionService().submit(
        _governance(status="conflicted"),
        members,
    )
    assert decision.outcome is CommitteeOutcome.MONITOR
    assert decision.stance is MarketStance.NEUTRAL
    assert decision.dissent


def test_unavailable_evidence_requests_more_evidence():
    decision = CommitteeSubmissionService().submit(
        _governance(
            status="decision_unavailable",
            aggregate_opportunity_score=None,
            aggregate_risk_score=None,
        ),
        _members(CommitteeOutcome.REQUEST_MORE_EVIDENCE),
    )
    assert decision.outcome is CommitteeOutcome.REQUEST_MORE_EVIDENCE
    assert decision.stance is MarketStance.UNAVAILABLE
    assert decision.resolution_conditions


def test_submission_requires_member_assessment():
    with pytest.raises(ValueError, match="at least one"):
        CommitteeSubmissionService().submit(_governance(), ())
