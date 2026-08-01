from __future__ import annotations

from pathlib import Path


path = Path(__file__).resolve().parents[1] / "tests/test_decision_process_upgrade.py"
text = path.read_text(encoding="utf-8")
old = '''def test_hysteresis_defers_first_buy_but_emergency_reduction_bypasses() -> None:
    candidate = _candidate("PERSIST")
    qualification = OpportunityEngine().qualify(candidate, _context())
    packet = _packet(candidate, duplicate_origins=False)
    prior = PriorDecisionContext(
        candidate_identifier=candidate.identifier,
        prior_decision_identifier="decision:prior",
        prior_action=CIOAction.WATCH,
        prior_target_weight=None,
        decided_at=candidate.as_of,
        thesis_state=ThesisState.CANDIDATE,
        consecutive_supportive_cycles=0,
    )
    deferred = ChiefInvestmentOfficer().synthesize(
        candidate,
        qualification.universe,
        packet,
        capital_comparison=qualification.capital_comparison,
        prior_context=prior,
    )
    assert deferred.action is CIOAction.WATCH
    assert deferred.hysteresis_applied

    holding = replace(
        candidate,
        identifier="candidate:persist-holding",
        current_portfolio_weight=0.05,
        base_case_return=-0.15,
        bull_case_return=0.02,
        bear_case_return=-0.50,
        estimated_fair_value=candidate.current_price * 0.85,
    )
    holding_packet = _packet(holding, duplicate_origins=False)
    holding_prior = replace(
        prior,
        candidate_identifier=holding.identifier,
        prior_action=CIOAction.HOLD,
        prior_target_weight=0.05,
        thesis_state=ThesisState.ACTIVE,
        consecutive_opposing_cycles=0,
    )
    holding_qualification = OpportunityEngine().qualify(holding, _context())
    reduced = ChiefInvestmentOfficer().synthesize(
        holding,
        holding_qualification.universe,
        holding_packet,
        capital_comparison=holding_qualification.capital_comparison,
        prior_context=holding_prior,
    )
    assert reduced.action in {CIOAction.REDUCE, CIOAction.EXIT}
    assert not reduced.hysteresis_applied
'''
new = '''def test_hysteresis_defers_two_cycle_buy_but_emergency_reduction_bypasses() -> None:
    candidate = _candidate("PERSIST")
    candidate = replace(
        candidate,
        instrument=replace(
            candidate.instrument,
            asset_class=CandidateAssetClass.US_ETF,
            economic_exposure_class=CandidateAssetClass.CRYPTO,
            replication_method="us-listed-economic-exposure-wrapper",
        ),
    )
    cio = ChiefInvestmentOfficer()
    profile = cio.policy_matrix.resolve(candidate)
    assert profile.entry_persistence_cycles == 2
    prior = PriorDecisionContext(
        candidate_identifier=candidate.identifier,
        prior_decision_identifier="decision:prior",
        prior_action=CIOAction.WATCH,
        prior_target_weight=None,
        decided_at=candidate.as_of,
        thesis_state=ThesisState.CANDIDATE,
        consecutive_supportive_cycles=0,
    )
    action, target, _reason, applied, cycles = cio._apply_hysteresis(
        candidate,
        action=CIOAction.BUY,
        position_weight=0.03,
        reason="Speculative wrapper clears the current-cycle decision gates.",
        prior_context=prior,
        profile=profile,
        progressive_lane=False,
        emergency=False,
    )
    assert action is CIOAction.WATCH
    assert target is None
    assert applied
    assert cycles == 1

    holding_base = _candidate("PERSIST-HOLDING")
    holding = replace(
        holding_base,
        current_portfolio_weight=0.05,
        base_case_return=-0.15,
        bull_case_return=0.02,
        bear_case_return=-0.50,
        estimated_fair_value=holding_base.current_price * 0.85,
    )
    holding_packet = _packet(holding, duplicate_origins=False)
    holding_prior = replace(
        prior,
        candidate_identifier=holding.identifier,
        prior_action=CIOAction.HOLD,
        prior_target_weight=0.05,
        thesis_state=ThesisState.ACTIVE,
        consecutive_opposing_cycles=0,
    )
    holding_qualification = OpportunityEngine().qualify(holding, _context())
    reduced = ChiefInvestmentOfficer().synthesize(
        holding,
        holding_qualification.universe,
        holding_packet,
        capital_comparison=holding_qualification.capital_comparison,
        prior_context=holding_prior,
    )
    assert reduced.action in {CIOAction.REDUCE, CIOAction.EXIT}
    assert not reduced.hysteresis_applied
'''
if text.count(old) != 1:
    raise RuntimeError("expected one legacy hysteresis test")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
