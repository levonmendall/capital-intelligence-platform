from __future__ import annotations

from pathlib import Path


path = Path(__file__).resolve().parents[1] / "tests/test_canonical_cio.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
    "    IndependentSpecialistPacket,\n    RecommendationUniversePolicy,\n",
    "    IndependentSpecialistPacket,\n    PriorDecisionContext,\n    RecommendationUniversePolicy,\n",
    1,
)
text = text.replace(
    "    SpecialistRole,\n    UniverseDisposition,\n",
    "    SpecialistRole,\n    ThesisState,\n    UniverseDisposition,\n",
    1,
)
old = '''def test_existing_holding_can_be_increased_reduced_or_exited() -> None:
    cio = ChiefInvestmentOfficer()

    increase_candidate = _candidate(current_weight=0.03)
    increase = cio.synthesize(
        increase_candidate,
        RecommendationUniversePolicy().evaluate(increase_candidate.instrument),
        _packet(weight=0.07),
    )
    assert increase.action is CIOAction.INCREASE
    assert increase.recommended_position_weight == pytest.approx(0.07)

    reduce_candidate = _candidate(
        current_weight=0.08,
        base_return=-0.01,
        bull_return=0.04,
        bear_return=-0.08,
    )
    reduce = cio.synthesize(
        reduce_candidate,
        RecommendationUniversePolicy().evaluate(reduce_candidate.instrument),
        _packet(weight=0.04),
    )
    assert reduce.action is CIOAction.REDUCE
    assert reduce.recommended_position_weight == pytest.approx(0.04)

    exit_candidate = _candidate(
        current_weight=0.08,
        base_return=-0.08,
        bull_return=-0.02,
        bear_return=-0.25,
    )
    exit_decision = cio.synthesize(
        exit_candidate,
        RecommendationUniversePolicy().evaluate(exit_candidate.instrument),
        _packet(weight=0.0),
    )
    assert exit_decision.action is CIOAction.EXIT
    assert exit_decision.recommended_position_weight == pytest.approx(0.0)
'''
new = '''def test_existing_holding_requires_continuity_for_ordinary_changes_but_emergency_exit_is_immediate() -> None:
    cio = ChiefInvestmentOfficer()

    increase_candidate = _candidate(current_weight=0.03)
    first_increase = cio.synthesize(
        increase_candidate,
        RecommendationUniversePolicy().evaluate(increase_candidate.instrument),
        _packet(weight=0.07),
    )
    assert first_increase.action is CIOAction.HOLD
    assert first_increase.deferred_action is CIOAction.INCREASE
    assert first_increase.recommended_position_weight is None

    increase_prior = PriorDecisionContext(
        candidate_identifier=increase_candidate.identifier,
        prior_decision_identifier=first_increase.identifier,
        prior_action=first_increase.action,
        prior_target_weight=None,
        decided_at=AS_OF - timedelta(days=1),
        thesis_state=ThesisState.ACTIVE,
        consecutive_supportive_cycles=1,
        consecutive_opposing_cycles=0,
    )
    increase = cio.synthesize(
        increase_candidate,
        RecommendationUniversePolicy().evaluate(increase_candidate.instrument),
        _packet(weight=0.07),
        prior_context=increase_prior,
    )
    assert increase.action is CIOAction.INCREASE
    assert increase.recommended_position_weight == pytest.approx(0.07)

    reduce_candidate = _candidate(
        current_weight=0.08,
        base_return=-0.01,
        bull_return=0.04,
        bear_return=-0.08,
    )
    first_reduce = cio.synthesize(
        reduce_candidate,
        RecommendationUniversePolicy().evaluate(reduce_candidate.instrument),
        _packet(weight=0.04),
    )
    assert first_reduce.action is CIOAction.HOLD
    assert first_reduce.deferred_action is CIOAction.REDUCE
    assert first_reduce.recommended_position_weight is None

    reduce_prior = PriorDecisionContext(
        candidate_identifier=reduce_candidate.identifier,
        prior_decision_identifier=first_reduce.identifier,
        prior_action=first_reduce.action,
        prior_target_weight=None,
        decided_at=AS_OF - timedelta(days=1),
        thesis_state=ThesisState.ACTIVE,
        consecutive_supportive_cycles=0,
        consecutive_opposing_cycles=1,
    )
    reduce = cio.synthesize(
        reduce_candidate,
        RecommendationUniversePolicy().evaluate(reduce_candidate.instrument),
        _packet(weight=0.04),
        prior_context=reduce_prior,
    )
    assert reduce.action is CIOAction.REDUCE
    assert reduce.recommended_position_weight == pytest.approx(0.04)

    exit_candidate = _candidate(
        current_weight=0.08,
        base_return=-0.08,
        bull_return=-0.02,
        bear_return=-0.25,
    )
    exit_decision = cio.synthesize(
        exit_candidate,
        RecommendationUniversePolicy().evaluate(exit_candidate.instrument),
        _packet(weight=0.0),
    )
    assert exit_decision.action is CIOAction.EXIT
    assert exit_decision.recommended_position_weight == pytest.approx(0.0)
'''
if text.count(old) != 1:
    raise RuntimeError("expected one legacy existing-holding persistence test")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
