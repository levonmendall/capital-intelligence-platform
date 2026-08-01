from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, *, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_continuity_thesis() -> None:
    path = ROOT / "application/cio_cycle.py"
    old = '''            if existing is None:
                if decision.action in {CIOAction.BUY, CIOAction.INCREASE} and implemented > current + 0.000001:
                    thesis = LivingThesis.from_decision(candidate, decision)
            else:
'''
    new = '''            if existing is None:
                if (
                    decision.action in {CIOAction.BUY, CIOAction.INCREASE}
                    and implemented > current + 0.000001
                ) or (
                    current > 0.000001
                    and decision.action is CIOAction.HOLD
                ):
                    # A pre-existing canonical holding may enter this decision epoch
                    # without a reconstructable thesis.  A deferred HOLD must create
                    # one immutable continuity thesis before evaluation is captured.
                    thesis = LivingThesis.from_decision(candidate, decision)
            else:
'''
    replace_once(path, old, new, label="continuity thesis bootstrap")


def patch_policy_tests() -> None:
    path = ROOT / "tests/test_opportunity_snapshot_authority.py"
    text = path.read_text(encoding="utf-8")
    start = text.index("def test_standard_first_cycle_entry_follows_one_cycle_policy")
    end = text.index("def test_opportunity_snapshot_round_trip_is_exact_and_hash_guarded")
    replacement = '''def _hysteresis(candidate, *, progressive_lane=False, prior_context=None):
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


'''
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


def patch_production_test_cycle_identifier() -> None:
    path = ROOT / "tests/test_production_opportunity_snapshot_authority.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "publication = screening.publication(result.screening_cycle_identifier)",
        "screening_cycle_identifier = result.screening_publication_identifier.replace(\n"
        "        \"publication:\", \"screening:\", 1\n"
        "    )\n"
        "    publication = screening.publication(screening_cycle_identifier)",
        1,
    )
    text = text.replace(
        "aggregate_identifier=result.screening_cycle_identifier,",
        "aggregate_identifier=screening_cycle_identifier,",
        1,
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_continuity_thesis()
    patch_policy_tests()
    patch_production_test_cycle_identifier()


if __name__ == "__main__":
    main()
