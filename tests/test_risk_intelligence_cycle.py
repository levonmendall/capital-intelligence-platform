from __future__ import annotations

from application.cio_cycle import CanonicalCIOCycle
from cio.persistence import CIOJournalEventType, SQLiteCIOJournal
from portfolio.risk_intelligence import JointCandidateRelation
from tests.test_canonical_cio_cycle import (
    _candidate,
    _construction_policy,
    _context,
    _opportunity_context,
    _portfolio,
)


def test_canonical_cycle_exposes_candidate_risk_and_joint_analysis() -> None:
    first = _candidate("RISKONE", base_return=0.15, bull_return=0.28)
    second = _candidate("RISKTWO", base_return=0.10, bull_return=0.20)

    result = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
    ).run(
        identifier="cycle:risk-intelligence",
        candidates=(first, second),
        opportunity_context=_opportunity_context(),
        specialist_contexts=(_context(first), _context(second)),
        portfolio=_portfolio((first, second)),
    )

    assert len(result.risk_assessments) == len(result.decisions) == 2
    assert len(result.joint_candidate_assessments) == 1
    assert result.joint_candidate_assessments[0].relation in set(
        JointCandidateRelation
    )
    assert all(item.diagnostics for item in result.risk_assessments)


def test_risk_diagnostics_reach_existing_portfolio_specialist_and_journal(tmp_path) -> None:
    candidate = _candidate("RISKJOURNAL")
    journal = SQLiteCIOJournal(tmp_path / "journal.db")

    result = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
        journal=journal,
    ).run(
        identifier="cycle:risk-intelligence-journal",
        candidates=(candidate,),
        opportunity_context=_opportunity_context(),
        specialist_contexts=(_context(candidate),),
        portfolio=_portfolio((candidate,)),
        code_version="test",
    )

    risk_event = next(
        item
        for item in journal.events()
        if item.event_type is CIOJournalEventType.CANDIDATE_RISK_ASSESSMENT
    )
    packet_event = next(
        item
        for item in journal.events()
        if item.event_type is CIOJournalEventType.SPECIALIST_PACKET
    )
    portfolio_analysis = next(
        item
        for item in packet_event.payload["analyses"]
        if item["role"] == "portfolio_risk_manager"
    )
    assert risk_event.payload["candidate_identifier"] == candidate.identifier
    assert any(
        "Candidate expected shortfall" in item
        for item in portfolio_analysis["supporting_evidence"]
    )
    assert result.risk_assessments[0].candidate_identifier == candidate.identifier
    assert journal.verify_integrity()
