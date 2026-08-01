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
                    # without a reconstructable thesis. A deferred HOLD must create
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


def patch_governed_adapter_lineage() -> None:
    path = ROOT / "application/production_context_adapter.py"
    replace_once(
        path,
        '''            code_version=base_context.code_version,
            manifest=manifest,
            knowledge_cutoff=cutoff,
''',
        '''            code_version=base_context.code_version,
            manifest=manifest,
            opportunity_snapshot_hash=(
                base_context.opportunity_snapshot_hash
            ),
            publication_code_version=(
                base_context.publication_code_version
            ),
            knowledge_cutoff=cutoff,
''',
        label="governed adapter snapshot lineage",
    )


def patch_governed_executor_authority() -> None:
    path = ROOT / "application/production_context_contract.py"
    replace_once(
        path,
        "from opportunity import OpportunityEngine\n",
        "from opportunity import OpportunityEngine\n"
        "from opportunity.snapshot import (\n"
        "    DECISION_SNAPSHOT_KIND,\n"
        "    build_opportunity_snapshot,\n"
        "    load_opportunity_snapshot,\n"
        ")\n",
        label="governed executor snapshot imports",
    )
    old = '''        if governed_context:
            publication_identifiers = qualified_identifiers + rejected_identifiers
            candidate_identifiers = tuple(item.identifier for item in candidates)
            if set(publication_identifiers) != set(candidate_identifiers):
                missing = sorted(
                    set(candidate_identifiers) - set(publication_identifiers)
                )
                extra = sorted(
                    set(publication_identifiers) - set(candidate_identifiers)
                )
                raise ValueError(
                    "persisted opportunity queue must reconcile every screened "
                    f"candidate: missing={missing} extra={extra}"
                )
            runtime_queue = cycle.opportunity_engine.build_queue(
                candidates,
                context.opportunity_context,
            )
            runtime_ranked = tuple(
                item.candidate.identifier for item in runtime_queue.ranked
            )
            runtime_rejected = tuple(
                item.candidate_identifier for item in runtime_queue.rejected
            )
            persisted_policy = _required_text(
                publication.opportunity_queue_payload.get("policy_version"),
                field_name="persisted opportunity policy version",
            )
            if runtime_queue.policy_version != persisted_policy:
                raise ValueError(
                    "runtime opportunity policy version differs from the "
                    "persisted screening publication"
                )
            if runtime_ranked != qualified_identifiers:
                raise ValueError(
                    "runtime opportunity ranking differs from the completed "
                    "screening publication"
                )
            if runtime_rejected != rejected_identifiers:
                raise ValueError(
                    "runtime rejection set differs from the completed screening "
                    "publication"
                )

        portfolio = context.portfolio
'''
    new = '''        decision_context = context.opportunity_context
        authoritative_queue = None
        if governed_context:
            publication_identifiers = qualified_identifiers + rejected_identifiers
            candidate_identifiers = tuple(item.identifier for item in candidates)
            if set(publication_identifiers) != set(candidate_identifiers):
                missing = sorted(
                    set(candidate_identifiers) - set(publication_identifiers)
                )
                extra = sorted(
                    set(publication_identifiers) - set(candidate_identifiers)
                )
                raise ValueError(
                    "persisted opportunity queue must reconcile every screened "
                    f"candidate: missing={missing} extra={extra}"
                )
            if context.opportunity_snapshot_hash is None:
                raise RuntimeError(
                    "governed production context lacks immutable opportunity lineage"
                )
            if cycle.journal is None:
                raise RuntimeError(
                    "exact opportunity authority requires the append-only CIO journal"
                )
            candidate_map = {item.identifier: item for item in candidates}
            snapshot_event = cycle.journal.latest(
                aggregate_identifier=context.screening_cycle_identifier,
                event_type=CIOJournalEventType.OPPORTUNITY_DECISION_SNAPSHOT,
            )
            if snapshot_event is None:
                if (
                    context.publication_code_version not in {None, "unknown"}
                    and context.code_version != "unknown"
                    and context.publication_code_version != context.code_version
                ):
                    raise RuntimeError(
                        "screening publication and CIO execution code versions differ; "
                        "a new publication is required"
                    )
                ranking_inputs = cycle.prepare_ranking_inputs(
                    candidates,
                    context.portfolio,
                    minimum_cash_weight=(
                        cycle.construction_engine.policy.minimum_cash_weight
                    ),
                )
                decision_context = replace(
                    context.opportunity_context,
                    ranking_inputs=ranking_inputs,
                )
                authoritative_queue = cycle.opportunity_engine.build_queue(
                    candidates,
                    decision_context,
                )
                snapshot_payload = build_opportunity_snapshot(
                    snapshot_kind=DECISION_SNAPSHOT_KIND,
                    context=decision_context,
                    queue=authoritative_queue,
                    engine=cycle.opportunity_engine,
                    created_at=decision_time,
                    code_version=context.code_version,
                    parent_snapshot_hash=context.opportunity_snapshot_hash,
                    screening_publication_identifier=publication.identifier,
                )
                cycle.journal.append(
                    event_type=(
                        CIOJournalEventType.OPPORTUNITY_DECISION_SNAPSHOT
                    ),
                    aggregate_identifier=context.screening_cycle_identifier,
                    occurred_at=decision_time,
                    payload=snapshot_payload,
                    schema_version="opportunity-decision-snapshot.v1",
                    event_identifier=(
                        "event:opportunity-decision-snapshot:"
                        + context.screening_cycle_identifier
                    ),
                )
            else:
                loaded = load_opportunity_snapshot(
                    snapshot_event.payload,
                    candidates=candidate_map,
                )
                if loaded.snapshot_kind != DECISION_SNAPSHOT_KIND:
                    raise RuntimeError(
                        "persisted decision snapshot kind is invalid"
                    )
                if loaded.parent_snapshot_hash != context.opportunity_snapshot_hash:
                    raise RuntimeError(
                        "persisted decision snapshot does not descend from the publication"
                    )
                if (
                    loaded.screening_publication_identifier
                    != publication.identifier
                ):
                    raise RuntimeError(
                        "persisted decision snapshot belongs to another publication"
                    )
                decision_context = loaded.context
                authoritative_queue = loaded.queue
            final_qualified = tuple(
                item.candidate.identifier for item in authoritative_queue.ranked
            )
            final_rejected = tuple(
                item.candidate_identifier for item in authoritative_queue.rejected
            )
            if set(final_qualified) != set(qualified_identifiers):
                raise ValueError(
                    "portfolio ranking changed the persisted qualified candidate set"
                )
            if set(final_rejected) != set(rejected_identifiers):
                raise ValueError(
                    "portfolio ranking changed the persisted rejected candidate set"
                )
            if set(context_identifiers) != set(final_qualified):
                raise ValueError(
                    "specialist context coverage does not match the immutable decision queue"
                )

        portfolio = context.portfolio
'''
    replace_once(path, old, new, label="governed immutable decision authority")
    replace_once(
        path,
        '''            opportunity_context=context.opportunity_context,
            specialist_contexts=context.specialist_contexts,
''',
        '''            opportunity_context=decision_context,
            specialist_contexts=context.specialist_contexts,
''',
        label="governed decision context handoff",
    )
    replace_once(
        path,
        '''            active_theses=active_theses,
            code_version=context.code_version,
''',
        '''            active_theses=active_theses,
            authoritative_opportunity_queue=authoritative_queue,
            code_version=context.code_version,
''',
        label="governed authoritative queue handoff",
    )


def main() -> None:
    patch_continuity_thesis()
    patch_policy_tests()
    patch_production_test_cycle_identifier()
    patch_governed_adapter_lineage()
    patch_governed_executor_authority()


if __name__ == "__main__":
    main()
