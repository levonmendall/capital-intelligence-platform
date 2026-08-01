"""Final-queue probability must match each candidate's strongest other use."""

from __future__ import annotations

import pytest

from opportunity import AlternativeKind, OpportunityEngine
from opportunity.competitive import prepare_competitive_opportunity_set
from tests.test_opportunity_engine import _candidate, _context


def test_qualified_peer_cannot_create_false_final_consistency_veto() -> None:
    engine = OpportunityEngine()
    baseline = _context(cash_return=0.04)
    candidate = _candidate(
        "FIRST",
        base=0.12,
        bull=0.30,
        bear=-0.15,
        probability=0.80,
    )
    stronger_peer = _candidate(
        "PEER",
        base=0.35,
        bull=0.70,
        bear=-0.10,
        probability=0.80,
    )

    prepared = prepare_competitive_opportunity_set(
        engine,
        (candidate, stronger_peer),
        baseline,
    )

    assert candidate.identifier in prepared.candidate_alternative_identifiers
    assert stronger_peer.identifier in prepared.candidate_alternative_identifiers
    aligned = next(
        item for item in prepared.candidates if item.identifier == candidate.identifier
    )
    peer_alternative = next(
        item
        for item in prepared.context.alternatives
        if item.kind is AlternativeKind.QUALIFIED_CANDIDATE
        and item.identifier == stronger_peer.identifier
    )
    peer_return = engine._alternative_comparable_return(
        peer_alternative,
        cash_anchor=baseline.alternatives[0].net_expected_return,
    )
    horizon_peer_return = engine.robust_assessor.horizon_return(
        peer_return,
        horizon_days=aligned.decision_horizon_days,
    )
    expected_success = round(
        sum(
            outcome.probability
            for outcome in aligned.scenario_distribution
            if outcome.total_return - aligned.implementation_cost_return
            > horizon_peer_return
        ),
        8,
    )

    assert aligned.probability_of_success == pytest.approx(expected_success)
    assert aligned.probability_of_success != candidate.probability_of_success
    ranked = next(
        (
            item.qualification
            for item in prepared.queue.ranked
            if item.candidate.identifier == candidate.identifier
        ),
        None,
    )
    final_qualification = ranked or next(
        item
        for item in prepared.queue.rejected
        if item.candidate_identifier == candidate.identifier
    )
    assert not any(
        "inconsistent with the disclosed scenarios" in reason
        for reason in final_qualification.reasons
    )
