from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, *, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_models() -> None:
    path = ROOT / "cio/models.py"
    replace_once(
        path,
        "    persistence_cycles: int = 1\n"
        "    hysteresis_applied: bool = False\n"
        "    resolved_policy_profile: str | None = None\n",
        "    persistence_cycles: int = 1\n"
        "    hysteresis_applied: bool = False\n"
        "    deferred_action: CIOAction | None = None\n"
        "    resolved_policy_profile: str | None = None\n",
        label="decision deferred-action field",
    )
    replace_once(
        path,
        "        if not isinstance(self.hysteresis_applied, bool):\n"
        "            raise TypeError(\"hysteresis_applied must be a bool\")\n"
        "        if self.resolved_policy_profile is not None:\n",
        "        if not isinstance(self.hysteresis_applied, bool):\n"
        "            raise TypeError(\"hysteresis_applied must be a bool\")\n"
        "        if self.deferred_action is not None and not isinstance(\n"
        "            self.deferred_action, CIOAction\n"
        "        ):\n"
        "            raise TypeError(\"deferred_action must be a CIOAction or None\")\n"
        "        if self.resolved_policy_profile is not None:\n",
        label="decision deferred-action validation",
    )


def patch_service() -> None:
    path = ROOT / "cio/service.py"
    replace_once(
        path,
        "        action, position_weight, reason = self._select_action(\n",
        "        action, position_weight, reason = self._select_action(\n",
        label="select action anchor",
    )
    text = path.read_text(encoding="utf-8")
    anchor = "        action, position_weight, reason, hysteresis_applied, persistence_cycles = (\n"
    if text.count(anchor) != 1:
        raise RuntimeError("selected action continuity anchor mismatch")
    text = text.replace(
        anchor,
        "        selected_action = action\n" + anchor,
        1,
    )
    field_anchor = (
        "            persistence_cycles=persistence_cycles,\n"
        "            hysteresis_applied=hysteresis_applied,\n"
        "            resolved_policy_profile=profile.identifier,\n"
    )
    if text.count(field_anchor) != 1:
        raise RuntimeError("decision continuity field anchor mismatch")
    text = text.replace(
        field_anchor,
        "            persistence_cycles=persistence_cycles,\n"
        "            hysteresis_applied=hysteresis_applied,\n"
        "            deferred_action=(\n"
        "                selected_action if hysteresis_applied else None\n"
        "            ),\n"
        "            resolved_policy_profile=profile.identifier,\n",
        1,
    )
    path.write_text(text, encoding="utf-8")


def patch_persistence() -> None:
    path = ROOT / "cio/persistence.py"
    replace_once(
        path,
        "        \"persistence_cycles\": decision.persistence_cycles,\n"
        "        \"hysteresis_applied\": decision.hysteresis_applied,\n"
        "        \"resolved_policy_profile\": decision.resolved_policy_profile,\n",
        "        \"persistence_cycles\": decision.persistence_cycles,\n"
        "        \"hysteresis_applied\": decision.hysteresis_applied,\n"
        "        \"deferred_action\": (\n"
        "            None\n"
        "            if decision.deferred_action is None\n"
        "            else decision.deferred_action.value\n"
        "        ),\n"
        "        \"resolved_policy_profile\": decision.resolved_policy_profile,\n",
        label="serialize deferred action",
    )
    replace_once(
        path,
        "        material = {CIOAction.BUY, CIOAction.INCREASE, CIOAction.REDUCE, CIOAction.EXIT}\n"
        "        for candidate in candidates:\n",
        "        material = {CIOAction.BUY, CIOAction.INCREASE, CIOAction.REDUCE, CIOAction.EXIT}\n"
        "\n"
        "        def continuity_action(event: CIOJournalEvent) -> CIOAction:\n"
        "            payload = event.payload\n"
        "            deferred = payload.get(\"deferred_action\")\n"
        "            if payload.get(\"hysteresis_applied\") is True and deferred:\n"
        "                try:\n"
        "                    return CIOAction(str(deferred))\n"
        "                except ValueError:\n"
        "                    pass\n"
        "            return CIOAction(payload[\"action\"])\n"
        "\n"
        "        for candidate in candidates:\n",
        label="continuity action resolver",
    )
    replace_once(
        path,
        "                item_action = CIOAction(event.payload[\"action\"])\n",
        "                item_action = continuity_action(event)\n",
        label="continuity action use",
    )


def patch_cycle() -> None:
    path = ROOT / "application/cio_cycle.py"
    replace_once(
        path,
        "            portfolio_context = self._preview_portfolio(\n"
        "                candidate=candidate,\n"
        "                rank=ranked.rank,\n"
        "                portfolio=portfolio,\n"
        "            )\n",
        "            portfolio_context = self._preview_portfolio(\n"
        "                candidate=candidate,\n"
        "                rank=ranked.rank,\n"
        "                portfolio=portfolio,\n"
        "                effective_opportunity_cost=(\n"
        "                    ranked.qualification.effective_opportunity_cost\n"
        "                ),\n"
        "            )\n",
        label="preview effective alternative handoff",
    )
    replace_once(
        path,
        "    def _preview_portfolio(\n"
        "        self,\n"
        "        *,\n"
        "        candidate: CandidateDecisionRecord,\n"
        "        rank: int,\n"
        "        portfolio: CyclePortfolioState,\n"
        "    ) -> PortfolioSpecialistContext:\n",
        "    def _preview_portfolio(\n"
        "        self,\n"
        "        *,\n"
        "        candidate: CandidateDecisionRecord,\n"
        "        rank: int,\n"
        "        portfolio: CyclePortfolioState,\n"
        "        effective_opportunity_cost: float,\n"
        "    ) -> PortfolioSpecialistContext:\n",
        label="preview effective alternative parameter",
    )
    replace_once(
        path,
        "            opportunity_edge=round(\n"
        "                annualized_return - candidate.opportunity_cost_return,\n"
        "                8,\n"
        "            ),\n",
        "            opportunity_edge=round(\n"
        "                annualized_return - effective_opportunity_cost,\n"
        "                8,\n"
        "            ),\n",
        label="preview intent effective edge",
    )
    replace_once(
        path,
        "            opportunity_cost_return=(\n"
        "                candidate.opportunity_cost_return\n"
        "            ),\n",
        "            opportunity_cost_return=effective_opportunity_cost,\n",
        label="portfolio specialist effective alternative",
    )


def patch_publisher() -> None:
    path = ROOT / "production_context_publication_governed.py"
    replace_once(
        path,
        "    screening_publication = FullUniverseScreeningPublication(\n",
        "    opportunity_queue_payload = {\n"
        "        **serialize_opportunity_queue(\n"
        "            queue,\n"
        "            occurred_at=decision_as_of,\n"
        "        ),\n"
        "        \"candidate_alternative_identifiers\": list(\n"
        "            competitive.candidate_alternative_identifiers\n"
        "        ),\n"
        "    }\n"
        "    screening_publication = FullUniverseScreeningPublication(\n",
        label="persist candidate alternative membership",
    )
    replace_once(
        path,
        "        opportunity_queue_payload=serialize_opportunity_queue(\n"
        "            queue,\n"
        "            occurred_at=decision_as_of,\n"
        "        ),\n",
        "        opportunity_queue_payload=opportunity_queue_payload,\n",
        label="use augmented opportunity payload",
    )


def patch_runtime_provider() -> None:
    path = ROOT / "application/production_context_runtime.py"
    replace_once(
        path,
        "from opportunity import AlternativeKind, AlternativeUse, OpportunitySetContext\n",
        "from opportunity import (\n"
        "    AlternativeKind,\n"
        "    AlternativeUse,\n"
        "    OpportunityEngine,\n"
        "    OpportunitySetContext,\n"
        ")\n",
        label="runtime opportunity engine import",
    )
    old = '''        alternatives.extend(
            AlternativeUse(
                identifier=candidate_identifier,
                kind=AlternativeKind.QUALIFIED_CANDIDATE,
                expected_return=(
                    candidate_map[
                        candidate_identifier
                    ].probability_weighted_expected_return
                ),
                implementation_cost_return=(
                    candidate_map[candidate_identifier].implementation_cost_return
                ),
                evidence_quality=(
                    candidate_map[candidate_identifier].evidence_quality.score
                ),
                liquidity_score=(
                    candidate_map[candidate_identifier].liquidity_score
                ),
                current_weight=0.0,
            )
            for candidate_identifier in qualified_ids
        )
        opportunity_context = OpportunitySetContext(
            identifier=publication.opportunity_context_identifier,
            as_of=decision_time,
            alternatives=tuple(alternatives),
        )
'''
    new = '''        raw_candidate_alternatives = publication.opportunity_queue_payload.get(
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
    replace_once(
        path,
        old,
        new,
        label="runtime competitive context reconstruction",
    )


def main() -> None:
    patch_models()
    patch_service()
    patch_persistence()
    patch_cycle()
    patch_publisher()
    patch_runtime_provider()
    subprocess.run(
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "tests/test_cio_runtime_continuity_blockers.py",
            "tests/test_decision_continuity_governance.py",
            "tests/test_canonical_cio_cycle.py",
            "tests/test_production_context_publication_runtime.py",
            "tests/test_production_invested_candidate_reachability.py",
            "tests/test_competitive_opportunity_context.py",
            "tests/test_competitive_peer_probability.py",
        ],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
