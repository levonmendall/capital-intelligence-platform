"""Regression coverage for persistence semantics and immutable opportunity authority."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from cio import (
    CIOAction,
    CandidateAssetClass,
    ChiefInvestmentOfficer,
    PriorDecisionContext,
    ThesisState,
)
from opportunity import OpportunityEngine
from opportunity.snapshot import (
    DECISION_SNAPSHOT_KIND,
    PUBLICATION_SNAPSHOT_KIND,
    build_opportunity_snapshot,
    load_opportunity_snapshot,
)
from tests.test_decision_quality_reconciliation import (
    _candidate,
    _context,
    _packet,
)


def _decision(candidate, *, prior_context=None, analysis_lane="acquisition"):
    qualification = OpportunityEngine().qualify(candidate, _context())
    return ChiefInvestmentOfficer().synthesize(
        candidate,
        qualification.universe,
        _packet(candidate, duplicate_origins=False),
        capital_comparison=qualification.capital_comparison,
        prior_context=prior_context,
        analysis_lane=analysis_lane,
    )


def _hysteresis(candidate, *, progressive_lane=False, prior_context=None):
    cio = ChiefInvestmentOfficer()
    return cio._apply_hysteresis(
        candidate,
        action=CIOAction.BUY,
        position_weight=0.03,
        reason="Candidate qualifies for acquisition.",
        prior_context=prior_context,
        profile=cio.policy_matrix.resolve(candidate),
        progressive_lane=progressive_lane,
        emergency=False,
    )


def test_standard_first_cycle_entry_follows_one_cycle_policy() -> None:
    candidate = _candidate("STANDARD")

    action, target, _reason, applied, cycles = _hysteresis(candidate)

    assert action is CIOAction.BUY
    assert target == pytest.approx(0.03)
    assert cycles == 1
    assert not applied


def test_speculative_first_cycle_entry_honors_two_cycle_policy() -> None:
    candidate = _candidate("SPEC")
    candidate = replace(
        candidate,
        instrument=replace(
            candidate.instrument,
            economic_exposure_class=CandidateAssetClass.CRYPTO,
            replication_method="us-listed-economic-exposure-wrapper",
        ),
    )

    action, target, _reason, applied, cycles = _hysteresis(candidate)

    assert action is CIOAction.WATCH
    assert target is None
    assert applied
    assert cycles == 1

    prior = PriorDecisionContext(
        candidate_identifier=candidate.identifier,
        prior_decision_identifier="cio-decision:prior",
        prior_action=CIOAction.WATCH,
        prior_target_weight=None,
        decided_at=candidate.as_of - timedelta(days=1),
        thesis_state=ThesisState.CANDIDATE,
        consecutive_supportive_cycles=1,
        consecutive_opposing_cycles=0,
    )
    action, target, _reason, applied, cycles = _hysteresis(
        candidate,
        prior_context=prior,
    )

    assert action is CIOAction.BUY
    assert target == pytest.approx(0.03)
    assert not applied
    assert cycles == 2


def test_progressive_lane_remains_immediate_and_risk_capped() -> None:
    candidate = _candidate("PROGRESSIVE")
    candidate = replace(
        candidate,
        instrument=replace(
            candidate.instrument,
            economic_exposure_class=CandidateAssetClass.CRYPTO,
            replication_method="us-listed-economic-exposure-wrapper",
        ),
    )

    action, target, _reason, applied, cycles = _hysteresis(
        candidate,
        progressive_lane=True,
    )

    assert action is CIOAction.BUY
    assert target == pytest.approx(0.03)
    assert not applied
    assert cycles == 1


def test_opportunity_snapshot_round_trip_is_exact_and_hash_guarded() -> None:
    engine = OpportunityEngine()
    candidate = _candidate("SNAPSHOT")
    context = _context()
    queue = engine.build_queue((candidate,), context)

    payload = build_opportunity_snapshot(
        snapshot_kind=PUBLICATION_SNAPSHOT_KIND,
        context=context,
        queue=queue,
        engine=engine,
        created_at=context.as_of,
        code_version="commit-a",
        screening_publication_identifier="publication:test",
    )
    loaded = load_opportunity_snapshot(
        payload,
        candidates={candidate.identifier: candidate},
    )

    assert loaded.snapshot_kind == PUBLICATION_SNAPSHOT_KIND
    assert loaded.context == context
    assert loaded.queue == queue
    assert loaded.code_version == "commit-a"
    assert loaded.screening_publication_identifier == "publication:test"

    decision_payload = build_opportunity_snapshot(
        snapshot_kind=DECISION_SNAPSHOT_KIND,
        context=context,
        queue=queue,
        engine=engine,
        created_at=context.as_of,
        code_version="commit-a",
        parent_snapshot_hash=loaded.content_hash,
        screening_publication_identifier="publication:test",
    )
    decision_loaded = load_opportunity_snapshot(
        decision_payload,
        candidates={candidate.identifier: candidate},
    )
    assert decision_loaded.parent_snapshot_hash == loaded.content_hash

    tampered = dict(payload)
    tampered_context = dict(tampered["context"])
    alternatives = [dict(item) for item in tampered_context["alternatives"]]
    alternatives[0]["expected_return"] = alternatives[0]["expected_return"] + 0.01
    tampered_context["alternatives"] = alternatives
    tampered["context"] = tampered_context
    with pytest.raises(ValueError, match="content hash"):
        load_opportunity_snapshot(
            tampered,
            candidates={candidate.identifier: candidate},
        )
