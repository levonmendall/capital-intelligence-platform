from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, *, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_cio_service() -> None:
    path = ROOT / "cio/service.py"
    old = '''        if prior_context is None:
            return action, position_weight, reason, False, 1
        if emergency or prior_context.emergency_override:
            cycles = max(1, prior_context.consecutive_opposing_cycles + 1)
            return action, position_weight, reason, False, cycles

        required = 1
        observed = 1
        if action is CIOAction.BUY:
            # Participation and exploration lanes may establish a deliberately
            # small first position immediately. Ordinary acquisition still
            # requires confirmation across at least two completed cycles.
            required = (
                1
                if progressive_lane
                else max(2, profile.entry_persistence_cycles)
            )
            observed = prior_context.consecutive_supportive_cycles + 1
        elif action is CIOAction.INCREASE:
            required = profile.increase_persistence_cycles
            observed = prior_context.consecutive_supportive_cycles + 1
        elif action in {CIOAction.REDUCE, CIOAction.EXIT}:
            required = profile.reduce_persistence_cycles
            observed = prior_context.consecutive_opposing_cycles + 1

        cooldown_active = False
        if prior_context.last_material_change_at is not None and profile.cooldown_days > 0:
            elapsed = (candidate.as_of - prior_context.last_material_change_at).days
            cooldown_active = elapsed < profile.cooldown_days
'''
    new = '''        if emergency or (
            prior_context is not None and prior_context.emergency_override
        ):
            cycles = (
                1
                if prior_context is None
                else max(1, prior_context.consecutive_opposing_cycles + 1)
            )
            return action, position_weight, reason, False, cycles

        # The resolved policy profile is the sole persistence authority.  A first
        # valid observation counts as cycle one rather than bypassing the profile.
        required = 1
        observed = 1
        if action is CIOAction.BUY:
            required = (
                1
                if progressive_lane
                else max(1, profile.entry_persistence_cycles)
            )
            if prior_context is not None:
                observed = prior_context.consecutive_supportive_cycles + 1
        elif action is CIOAction.INCREASE:
            required = max(1, profile.increase_persistence_cycles)
            if prior_context is not None:
                observed = prior_context.consecutive_supportive_cycles + 1
        elif action in {CIOAction.REDUCE, CIOAction.EXIT}:
            required = max(1, profile.reduce_persistence_cycles)
            if prior_context is not None:
                observed = prior_context.consecutive_opposing_cycles + 1

        cooldown_active = False
        if (
            prior_context is not None
            and prior_context.last_material_change_at is not None
            and profile.cooldown_days > 0
        ):
            elapsed = (candidate.as_of - prior_context.last_material_change_at).days
            cooldown_active = elapsed < profile.cooldown_days
'''
    replace_once(path, old, new, label="policy-authoritative hysteresis")


def patch_persistence_event() -> None:
    path = ROOT / "cio/persistence.py"
    replace_once(
        path,
        '    OPPORTUNITY_QUEUE = "opportunity_queue"\n',
        '    OPPORTUNITY_QUEUE = "opportunity_queue"\n'
        '    OPPORTUNITY_DECISION_SNAPSHOT = "opportunity_decision_snapshot"\n',
        label="opportunity decision snapshot event",
    )


def patch_cycle() -> None:
    path = ROOT / "application/cio_cycle.py"
    replace_once(
        path,
        '        active_theses: tuple[LivingThesis, ...] = (),\n        code_version: str | None = None,\n',
        '        active_theses: tuple[LivingThesis, ...] = (),\n'
        '        authoritative_opportunity_queue: OpportunityQueue | None = None,\n'
        '        code_version: str | None = None,\n',
        label="authoritative queue argument",
    )
    old = '''        generated_ranking = self._ranking_inputs(
            candidates,
            portfolio,
            minimum_cash_weight=(
                self.construction_engine.policy.minimum_cash_weight
            ),
        )
        supplied_ranking = {
            item.candidate_identifier: item
            for item in opportunity_context.ranking_inputs
        }
        supplied_ranking.update(
            {
                item.candidate_identifier: item
                for item in generated_ranking
                if item.candidate_identifier not in supplied_ranking
            }
        )
        opportunity_context = replace(
            opportunity_context,
            ranking_inputs=tuple(supplied_ranking.values()),
        )
        context_map = {
            item.candidate_identifier: item for item in specialist_contexts
        }
        if len(context_map) != len(specialist_contexts):
            raise ValueError("specialist candidate contexts must be unique")

        queue = self.opportunity_engine.build_queue(
            candidates,
            opportunity_context,
        )
'''
    new = '''        if authoritative_opportunity_queue is None:
            generated_ranking = self._ranking_inputs(
                candidates,
                portfolio,
                minimum_cash_weight=(
                    self.construction_engine.policy.minimum_cash_weight
                ),
            )
            supplied_ranking = {
                item.candidate_identifier: item
                for item in opportunity_context.ranking_inputs
            }
            supplied_ranking.update(
                {
                    item.candidate_identifier: item
                    for item in generated_ranking
                    if item.candidate_identifier not in supplied_ranking
                }
            )
            opportunity_context = replace(
                opportunity_context,
                ranking_inputs=tuple(supplied_ranking.values()),
            )
            queue = self.opportunity_engine.build_queue(
                candidates,
                opportunity_context,
            )
        else:
            if not isinstance(authoritative_opportunity_queue, OpportunityQueue):
                raise TypeError(
                    "authoritative_opportunity_queue must be OpportunityQueue or None"
                )
            if (
                authoritative_opportunity_queue.context_identifier
                != opportunity_context.identifier
            ):
                raise ValueError(
                    "authoritative opportunity queue does not match the context"
                )
            represented = {
                *(
                    item.candidate.identifier
                    for item in authoritative_opportunity_queue.ranked
                ),
                *(
                    item.candidate_identifier
                    for item in authoritative_opportunity_queue.rejected
                ),
            }
            if represented != {item.identifier for item in candidates}:
                raise ValueError(
                    "authoritative opportunity queue candidate coverage is invalid"
                )
            queue = authoritative_opportunity_queue
        context_map = {
            item.candidate_identifier: item for item in specialist_contexts
        }
        if len(context_map) != len(specialist_contexts):
            raise ValueError("specialist candidate contexts must be unique")
'''
    replace_once(path, old, new, label="authoritative queue consumption")
    replace_once(
        path,
        '    @classmethod\n    def _ranking_inputs(\n',
        '    @classmethod\n'
        '    def prepare_ranking_inputs(\n'
        '        cls,\n'
        '        candidates: tuple[CandidateDecisionRecord, ...],\n'
        '        portfolio: CyclePortfolioState,\n'
        '        *,\n'
        '        minimum_cash_weight: float = 0.02,\n'
        '    ) -> tuple[OpportunityRankingInput, ...]:\n'
        '        """Return the exact portfolio-aware inputs frozen before CIO review."""\n'
        '        return cls._ranking_inputs(\n'
        '            candidates,\n'
        '            portfolio,\n'
        '            minimum_cash_weight=minimum_cash_weight,\n'
        '        )\n\n'
        '    @classmethod\n'
        '    def _ranking_inputs(\n',
        label="public ranking input preparation",
    )


def patch_production_publisher() -> None:
    path = ROOT / "production_context_publication_governed.py"
    replace_once(
        path,
        'from opportunity.competitive import prepare_competitive_opportunity_set\n',
        'from opportunity.competitive import prepare_competitive_opportunity_set\n'
        'from opportunity.snapshot import (\n'
        '    PUBLICATION_SNAPSHOT_KIND,\n'
        '    build_opportunity_snapshot,\n'
        ')\n',
        label="snapshot publisher imports",
    )
    replace_once(
        path,
        '    opportunity_context = competitive.context\n    queue = competitive.queue\n',
        '    opportunity_context = competitive.context\n'
        '    queue = competitive.queue\n'
        '    opportunity_context_snapshot = build_opportunity_snapshot(\n'
        '        snapshot_kind=PUBLICATION_SNAPSHOT_KIND,\n'
        '        context=opportunity_context,\n'
        '        queue=queue,\n'
        '        engine=opportunity_engine,\n'
        '        created_at=decision_as_of,\n'
        '        screening_publication_identifier=(\n'
        '            screening_publication_identifier\n'
        '        ),\n'
        '    )\n',
        label="publication snapshot creation",
    )
    replace_once(
        path,
        '        "candidate_alternative_identifiers": list(\n'
        '            competitive.candidate_alternative_identifiers\n'
        '        ),\n'
        '    }\n',
        '        "candidate_alternative_identifiers": list(\n'
        '            competitive.candidate_alternative_identifiers\n'
        '        ),\n'
        '        "opportunity_context_snapshot": opportunity_context_snapshot,\n'
        '    }\n',
        label="publication snapshot persistence",
    )


def patch_runtime_provider() -> None:
    path = ROOT / "application/production_context_runtime.py"
    replace_once(
        path,
        '    AlternativeUse,\n    OpportunityEngine,\n    OpportunitySetContext,\n)\n',
        '    AlternativeUse,\n)\n'
        'from opportunity.snapshot import (\n'
        '    PUBLICATION_SNAPSHOT_KIND,\n'
        '    load_opportunity_snapshot,\n'
        ')\n',
        label="runtime snapshot imports",
    )
    start = '''        alternatives: list[AlternativeUse] = [
            AlternativeUse(
                identifier="cash",
                kind=AlternativeKind.CASH,
                expected_return=evidence.cash_expected_return,
                implementation_cost_return=0.0,
                evidence_quality=evidence.cash_evidence_quality,
                liquidity_score=evidence.cash_liquidity_score,
                current_weight=cash_weight,
            )
        ]
        alternatives.extend(
            AlternativeUse(
                identifier=f"holding:{position.symbol}",
                kind=AlternativeKind.CURRENT_HOLDING,
                expected_return=holding_context[position.symbol].expected_return,
                implementation_cost_return=(
                    holding_context[position.symbol].implementation_cost_return
                ),
                evidence_quality=holding_context[
                    position.symbol
                ].evidence_quality,
                liquidity_score=holding_context[position.symbol].liquidity_score,
                current_weight=round(
                    position.market_value / portfolio_snapshot.nav,
                    8,
                ),
            )
            for position in portfolio_snapshot.positions
        )
        raw_candidate_alternatives = publication.opportunity_queue_payload.get(
            "candidate_alternative_identifiers"
        )
        if raw_candidate_alternatives is None:
            candidate_alternative_ids = tuple(
                identifier
                for identifier in qualified_ids
                if candidate_map[identifier].current_portfolio_weight <= 0.0
            )
        else:
            if not isinstance(raw_candidate_alternatives, (list, tuple)):
                raise ProductionContextError(
                    "persisted candidate alternative identifiers must be a sequence"
                )
            candidate_alternative_ids = tuple(
                _text(item, field_name="candidate alternative identifier")
                for item in raw_candidate_alternatives
            )
        if len(candidate_alternative_ids) != len(set(candidate_alternative_ids)):
            raise ProductionContextError(
                "persisted candidate alternative identifiers contain duplicates"
            )
        if not set(candidate_alternative_ids).issubset(candidate_map):
            raise ProductionContextError(
                "persisted candidate alternatives reference unknown candidates"
            )
        baseline_context = OpportunitySetContext(
            identifier=publication.opportunity_context_identifier,
            as_of=decision_time,
            alternatives=tuple(alternatives),
        )
        comparison_engine = OpportunityEngine()
        for candidate_identifier in candidate_alternative_ids:
            candidate = candidate_map[candidate_identifier]
            if candidate.current_portfolio_weight > 0.0:
                raise ProductionContextError(
                    "a current holding cannot be duplicated as a candidate alternative"
                )
            assessment = comparison_engine.robustness(
                candidate,
                baseline_context,
            )
            alternatives.append(
                AlternativeUse(
                    identifier=candidate_identifier,
                    kind=AlternativeKind.QUALIFIED_CANDIDATE,
                    expected_return=assessment.evidence_adjusted_return,
                    implementation_cost_return=0.0,
                    evidence_quality=1.0,
                    liquidity_score=1.0,
                    current_weight=0.0,
                )
            )
        opportunity_context = OpportunitySetContext(
            identifier=publication.opportunity_context_identifier,
            as_of=decision_time,
            alternatives=tuple(alternatives),
        )
'''
    replacement = '''        expected_baseline = (
            AlternativeUse(
                identifier="cash",
                kind=AlternativeKind.CASH,
                expected_return=evidence.cash_expected_return,
                implementation_cost_return=0.0,
                evidence_quality=evidence.cash_evidence_quality,
                liquidity_score=evidence.cash_liquidity_score,
                current_weight=cash_weight,
            ),
            *tuple(
                AlternativeUse(
                    identifier=f"holding:{position.symbol}",
                    kind=AlternativeKind.CURRENT_HOLDING,
                    expected_return=holding_context[position.symbol].expected_return,
                    implementation_cost_return=(
                        holding_context[position.symbol].implementation_cost_return
                    ),
                    evidence_quality=holding_context[
                        position.symbol
                    ].evidence_quality,
                    liquidity_score=holding_context[position.symbol].liquidity_score,
                    current_weight=round(
                        position.market_value / portfolio_snapshot.nav,
                        8,
                    ),
                )
                for position in portfolio_snapshot.positions
            ),
        )
        raw_snapshot = publication.opportunity_queue_payload.get(
            "opportunity_context_snapshot"
        )
        if not isinstance(raw_snapshot, dict):
            raise ProductionContextError(
                "screening publication lacks an exact immutable opportunity snapshot"
            )
        try:
            publication_snapshot = load_opportunity_snapshot(
                raw_snapshot,
                candidates=candidate_map,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProductionContextError(
                f"immutable opportunity snapshot is invalid: {error}"
            ) from error
        if publication_snapshot.snapshot_kind != PUBLICATION_SNAPSHOT_KIND:
            raise ProductionContextError(
                "screening publication contains the wrong opportunity snapshot kind"
            )
        if (
            publication_snapshot.screening_publication_identifier
            != publication.identifier
        ):
            raise ProductionContextError(
                "opportunity snapshot does not belong to the screening publication"
            )
        if (
            publication_snapshot.context.identifier
            != publication.opportunity_context_identifier
            or publication_snapshot.context.as_of != decision_time
        ):
            raise ProductionContextError(
                "opportunity snapshot does not match the production cycle boundary"
            )
        snapshot_baseline = tuple(
            item
            for item in publication_snapshot.context.alternatives
            if item.kind is not AlternativeKind.QUALIFIED_CANDIDATE
        )
        if snapshot_baseline != expected_baseline:
            raise ProductionContextError(
                "opportunity snapshot baseline differs from exact portfolio evidence"
            )
        snapshot_qualified = tuple(
            item.candidate.identifier
            for item in publication_snapshot.queue.ranked
        )
        if snapshot_qualified != qualified_ids:
            raise ProductionContextError(
                "opportunity snapshot queue differs from the published qualified order"
            )
        opportunity_context = publication_snapshot.context
'''
    replace_once(path, start, replacement, label="exact runtime snapshot loading")
    replace_once(
        path,
        '            code_version=self.code_version,\n            manifest=manifest,\n',
        '            code_version=self.code_version,\n'
        '            manifest=manifest,\n'
        '            opportunity_snapshot_hash=(\n'
        '                publication_snapshot.content_hash\n'
        '            ),\n'
        '            publication_code_version=(\n'
        '                publication_snapshot.code_version\n'
        '            ),\n',
        label="runtime snapshot lineage fields",
    )


def patch_production_executor() -> None:
    path = ROOT / "application/production_cio.py"
    replace_once(
        path,
        'from dataclasses import dataclass\n',
        'from dataclasses import dataclass, replace\n',
        label="production dataclass replace import",
    )
    replace_once(
        path,
        'from opportunity import OpportunitySetContext\n',
        'from cio.persistence import CIOJournalEventType\n'
        'from opportunity import OpportunityQueue, OpportunitySetContext\n'
        'from opportunity.snapshot import (\n'
        '    DECISION_SNAPSHOT_KIND,\n'
        '    build_opportunity_snapshot,\n'
        '    load_opportunity_snapshot,\n'
        ')\n',
        label="production snapshot imports",
    )
    replace_once(
        path,
        '    code_version: str = "unknown"\n    manifest: ProductionContextManifest | None = None\n',
        '    code_version: str = "unknown"\n'
        '    manifest: ProductionContextManifest | None = None\n'
        '    opportunity_snapshot_hash: str | None = None\n'
        '    publication_code_version: str | None = None\n',
        label="production snapshot context fields",
    )
    replace_once(
        path,
        '        if self.manifest is not None:\n',
        '        for field_name in (\n'
        '            "opportunity_snapshot_hash",\n'
        '            "publication_code_version",\n'
        '        ):\n'
        '            value = getattr(self, field_name)\n'
        '            if value is not None:\n'
        '                object.__setattr__(\n'
        '                    self,\n'
        '                    field_name,\n'
        '                    _required_text(value, field_name=field_name),\n'
        '                )\n'
        '        if self.manifest is not None:\n',
        label="production snapshot field validation",
    )
    old = '''        ranked = tuple(
            dict(item)
            for item in publication.opportunity_queue_payload.get("ranked", ())
        )
        qualified_identifiers = tuple(
            _required_text(
                item.get("candidate_identifier"),
                field_name="qualified candidate identifier",
            )
            for item in ranked
        )
'''
    new = '''        candidate_map = {item.identifier: item for item in candidates}
        publication_ranked = tuple(
            dict(item)
            for item in publication.opportunity_queue_payload.get("ranked", ())
        )
        publication_qualified_identifiers = tuple(
            _required_text(
                item.get("candidate_identifier"),
                field_name="qualified candidate identifier",
            )
            for item in publication_ranked
        )
        decision_context = context.opportunity_context
        authoritative_queue: OpportunityQueue | None = None
        if context.opportunity_snapshot_hash is not None:
            if self.cycle.journal is None:
                raise RuntimeError(
                    "exact opportunity authority requires the append-only CIO journal"
                )
            snapshot_event = self.cycle.journal.latest(
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
                ranking_inputs = self.cycle.prepare_ranking_inputs(
                    candidates,
                    context.portfolio,
                    minimum_cash_weight=(
                        self.cycle.construction_engine.policy.minimum_cash_weight
                    ),
                )
                decision_context = replace(
                    context.opportunity_context,
                    ranking_inputs=ranking_inputs,
                )
                authoritative_queue = self.cycle.opportunity_engine.build_queue(
                    candidates,
                    decision_context,
                )
                snapshot_payload = build_opportunity_snapshot(
                    snapshot_kind=DECISION_SNAPSHOT_KIND,
                    context=decision_context,
                    queue=authoritative_queue,
                    engine=self.cycle.opportunity_engine,
                    created_at=decision_time,
                    code_version=context.code_version,
                    parent_snapshot_hash=context.opportunity_snapshot_hash,
                    screening_publication_identifier=publication.identifier,
                )
                self.cycle.journal.append(
                    event_type=CIOJournalEventType.OPPORTUNITY_DECISION_SNAPSHOT,
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
                    raise RuntimeError("persisted decision snapshot kind is invalid")
                if loaded.parent_snapshot_hash != context.opportunity_snapshot_hash:
                    raise RuntimeError(
                        "persisted decision snapshot does not descend from the publication"
                    )
                if loaded.screening_publication_identifier != publication.identifier:
                    raise RuntimeError(
                        "persisted decision snapshot belongs to another publication"
                    )
                decision_context = loaded.context
                authoritative_queue = loaded.queue
        if authoritative_queue is None:
            qualified_identifiers = publication_qualified_identifiers
        else:
            qualified_identifiers = tuple(
                item.candidate.identifier for item in authoritative_queue.ranked
            )
'''
    replace_once(path, old, new, label="authoritative decision snapshot")
    replace_once(
        path,
        '                context.manifest.candidate_identifiers\n                != qualified_identifiers\n',
        '                context.manifest.candidate_identifiers\n'
        '                != publication_qualified_identifiers\n',
        label="manifest preserves publication ordering",
    )
    replace_once(
        path,
        '            opportunity_context=context.opportunity_context,\n',
        '            opportunity_context=decision_context,\n',
        label="decision context handoff",
    )
    replace_once(
        path,
        '            active_theses=active_theses,\n            code_version=context.code_version,\n',
        '            active_theses=active_theses,\n'
        '            authoritative_opportunity_queue=authoritative_queue,\n'
        '            code_version=context.code_version,\n',
        label="authoritative queue handoff",
    )


def main() -> None:
    patch_cio_service()
    patch_persistence_event()
    patch_cycle()
    patch_production_publisher()
    patch_runtime_provider()
    patch_production_executor()
    subprocess.run(
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "tests/test_opportunity_snapshot_authority.py",
            "tests/test_production_opportunity_snapshot_authority.py",
            "tests/test_cio_runtime_continuity_blockers.py",
            "tests/test_production_governed_candidate_reachability.py",
            "tests/test_production_invested_candidate_reachability.py",
            "tests/test_production_context_publication_runtime.py",
            "tests/test_canonical_cio_cycle.py",
        ],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
