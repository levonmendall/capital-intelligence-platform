from __future__ import annotations

import re
from pathlib import Path


def replace_one(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact match, found {count}")
    file.write_text(text.replace(old, new))


def regex_one(path: str, pattern: str, replacement: str) -> None:
    file = Path(path)
    text = file.read_text()
    updated, count = re.subn(pattern, replacement, text, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex match, found {count}")
    file.write_text(updated)


# Stable ownership-episode lineage and append-only continuation.
replace_one(
    "thesis/models.py",
    "    next_review_at: datetime\n    review_count: int = 0\n",
    "    next_review_at: datetime\n    review_count: int = 0\n    ownership_episode_identifier: str = \"\"\n",
)
replace_one(
    "thesis/models.py",
    "        _aware(self.created_at, field_name=\"created_at\")\n",
    "        episode = self.ownership_episode_identifier or self.identifier\n        object.__setattr__(\n            self,\n            \"ownership_episode_identifier\",\n            _required_text(episode, field_name=\"ownership_episode_identifier\"),\n        )\n        _aware(self.created_at, field_name=\"created_at\")\n",
)
replace_one(
    "thesis/models.py",
    "        return cls(\n            identifier=f\"thesis:{decision.identifier}\",\n",
    "        episode = (\n            f\"ownership:{candidate.instrument.instrument_id}:\"\n            f\"{decision.as_of.isoformat()}\"\n        )\n        return cls(\n            identifier=f\"thesis:{episode}\",\n",
)
replace_one(
    "thesis/models.py",
    "            next_review_at=decision.review_at,\n        )\n\n    def apply(self, review: \"ThesisReview\") -> \"LivingThesis\":\n",
    "            next_review_at=decision.review_at,\n            ownership_episode_identifier=episode,\n        )\n\n    def continue_from_decision(\n        self,\n        candidate: CandidateDecisionRecord,\n        decision: CIODecision,\n    ) -> \"LivingThesis\":\n        if decision.candidate_identifier != candidate.identifier:\n            raise ValueError(\"decision and candidate identifiers do not match\")\n        if decision.as_of <= self.updated_at:\n            raise ValueError(\"continued thesis decision must follow the current snapshot\")\n        if decision.action is CIOAction.EXIT:\n            state = ThesisState.EXITED\n        elif decision.action is CIOAction.REDUCE:\n            state = ThesisState.REDUCED\n        elif decision.action in {CIOAction.HOLD, CIOAction.NO_MATERIAL_CHANGE}:\n            state = ThesisState.STABLE\n        elif decision.action in {CIOAction.BUY, CIOAction.INCREASE}:\n            state = ThesisState.ACTIVE\n        else:\n            state = self.state\n        return replace(\n            self,\n            decision_identifier=decision.identifier,\n            candidate_identifier=candidate.identifier,\n            updated_at=decision.as_of,\n            state=state,\n            expected_return=decision.expected_return,\n            expected_downside=(\n                candidate.expected_downside\n                if decision.return_reconciliation is None\n                else decision.return_reconciliation.expected_downside\n            ),\n            horizon_days=decision.decision_horizon_days,\n            assumptions=decision.key_assumptions,\n            catalysts=decision.catalysts,\n            invalidation_conditions=decision.invalidation_conditions,\n            monitoring_indicators=decision.monitoring_indicators,\n            current_confidence=decision.final_confidence,\n            evidence_identifiers=candidate.evidence_identifiers,\n            next_review_at=decision.review_at,\n            review_count=self.review_count + 1,\n        )\n\n    def apply(self, review: \"ThesisReview\") -> \"LivingThesis\":\n",
)

replace_one(
    "thesis/__init__.py",
    "from thesis.service import ThesisMonitor, ThesisMonitoringPolicy\n",
    "from thesis.conditions import (\n    MissingDataBehavior,\n    StructuredThesisConditionScorer,\n    StructuredThesisQuality,\n    ThesisCondition,\n    ThesisConditionConsequence,\n    ThesisConditionOperator,\n)\nfrom thesis.service import ThesisMonitor, ThesisMonitoringPolicy\n",
)
replace_one(
    "thesis/__init__.py",
    "__all__ = [\n    \"LivingThesis\",\n",
    "__all__ = [\n    \"LivingThesis\",\n    \"MissingDataBehavior\",\n    \"StructuredThesisConditionScorer\",\n    \"StructuredThesisQuality\",\n    \"ThesisCondition\",\n    \"ThesisConditionConsequence\",\n    \"ThesisConditionOperator\",\n",
)

# Journal serialization and state reconstruction.
replace_one(
    "cio/persistence.py",
    "from cio.models import CIODecision, CandidateDecisionRecord\n",
    "from cio.models import (\n    CIOAction,\n    CIODecision,\n    CandidateDecisionRecord,\n    PriorDecisionContext,\n    ThesisState,\n)\n",
)
replace_one(
    "cio/persistence.py",
    "        \"review_count\": thesis.review_count,\n",
    "        \"review_count\": thesis.review_count,\n        \"ownership_episode_identifier\": thesis.ownership_episode_identifier,\n",
)
replace_one(
    "cio/persistence.py",
    "            schema_version=\"living-thesis.v1\",\n",
    "            schema_version=\"living-thesis.v2\",\n",
)
continuity_methods = '''\n    def prior_decision_contexts(\n        self,\n        candidates: tuple[CandidateDecisionRecord, ...],\n        *,\n        as_of: datetime,\n    ) -> tuple[PriorDecisionContext, ...]:\n        \"\"\"Reconstruct state by instrument, not timestamp-specific candidate ID.\"\"\"\n\n        decision_time = _aware(as_of, field_name=\"as_of\")\n        if not self.verify_integrity():\n            raise CIOJournalIntegrityError(\"CIO journal integrity is unavailable\")\n        limit = max(1, self.count())\n        candidate_events = self.events(\n            event_type=CIOJournalEventType.CANDIDATE_DECISION,\n            limit=limit,\n        )\n        decision_events = self.events(\n            event_type=CIOJournalEventType.CIO_DECISION,\n            limit=limit,\n        )\n        thesis_events = self.events(\n            event_type=CIOJournalEventType.THESIS_SNAPSHOT,\n            limit=limit,\n        )\n        results: list[PriorDecisionContext] = []\n        supportive = {\n            CIOAction.BUY,\n            CIOAction.INCREASE,\n            CIOAction.HOLD,\n            CIOAction.NO_MATERIAL_CHANGE,\n        }\n        opposing = {CIOAction.REDUCE, CIOAction.EXIT}\n        material = {CIOAction.BUY, CIOAction.INCREASE, CIOAction.REDUCE, CIOAction.EXIT}\n        for candidate in candidates:\n            historical_ids = {\n                event.aggregate_identifier\n                for event in candidate_events\n                if event.occurred_at < decision_time\n                and event.payload.get(\"instrument\", {}).get(\"instrument_id\")\n                == candidate.instrument.instrument_id\n            }\n            history = [\n                event\n                for event in decision_events\n                if event.occurred_at < decision_time\n                and event.aggregate_identifier in historical_ids\n            ]\n            if not history:\n                continue\n            history.sort(key=lambda item: item.sequence)\n            latest = history[-1]\n            payload = latest.payload\n            action = CIOAction(payload[\"action\"])\n            supportive_cycles = 0\n            opposing_cycles = 0\n            for event in reversed(history):\n                item_action = CIOAction(event.payload[\"action\"])\n                if item_action in supportive:\n                    if opposing_cycles:\n                        break\n                    supportive_cycles += 1\n                elif item_action in opposing:\n                    if supportive_cycles:\n                        break\n                    opposing_cycles += 1\n                else:\n                    break\n            last_change = next(\n                (\n                    event.occurred_at\n                    for event in reversed(history)\n                    if CIOAction(event.payload[\"action\"]) in material\n                ),\n                None,\n            )\n            latest_thesis = next(\n                (\n                    event\n                    for event in reversed(thesis_events)\n                    if event.occurred_at < decision_time\n                    and event.payload.get(\"asset\") == candidate.instrument.symbol\n                ),\n                None,\n            )\n            thesis_state = (\n                ThesisState.CANDIDATE\n                if latest_thesis is None\n                else ThesisState(latest_thesis.payload[\"state\"])\n            )\n            results.append(\n                PriorDecisionContext(\n                    candidate_identifier=candidate.identifier,\n                    prior_decision_identifier=payload[\"identifier\"],\n                    prior_action=action,\n                    prior_target_weight=payload.get(\"recommended_position_weight\"),\n                    decided_at=latest.occurred_at,\n                    thesis_state=thesis_state,\n                    consecutive_supportive_cycles=supportive_cycles,\n                    consecutive_opposing_cycles=opposing_cycles,\n                    last_material_change_at=last_change,\n                    emergency_override=False,\n                )\n            )\n        return tuple(results)\n\n    def active_theses(\n        self,\n        candidates: tuple[CandidateDecisionRecord, ...],\n        *,\n        as_of: datetime,\n    ) -> tuple[LivingThesis, ...]:\n        decision_time = _aware(as_of, field_name=\"as_of\")\n        symbols = {item.instrument.symbol for item in candidates}\n        limit = max(1, self.count())\n        events = self.events(\n            event_type=CIOJournalEventType.THESIS_SNAPSHOT,\n            limit=limit,\n        )\n        latest: dict[str, CIOJournalEvent] = {}\n        for event in events:\n            if event.occurred_at >= decision_time or event.payload.get(\"asset\") not in symbols:\n                continue\n            episode = event.payload.get(\"ownership_episode_identifier\") or event.payload[\"identifier\"]\n            latest[episode] = event\n        active_states = {\n            ThesisState.ACTIVE,\n            ThesisState.STRENGTHENING,\n            ThesisState.STABLE,\n            ThesisState.WEAKENING,\n            ThesisState.REDUCED,\n        }\n        values: list[LivingThesis] = []\n        for event in latest.values():\n            payload = event.payload\n            state = ThesisState(payload[\"state\"])\n            if state not in active_states:\n                continue\n            values.append(\n                LivingThesis(\n                    identifier=payload[\"identifier\"],\n                    decision_identifier=payload[\"decision_identifier\"],\n                    candidate_identifier=payload[\"candidate_identifier\"],\n                    asset=payload[\"asset\"],\n                    created_at=datetime.fromisoformat(payload[\"created_at\"]),\n                    updated_at=datetime.fromisoformat(payload[\"updated_at\"]),\n                    state=state,\n                    original_rationale=payload[\"original_rationale\"],\n                    assumptions=tuple(payload[\"assumptions\"]),\n                    expected_return=payload[\"expected_return\"],\n                    expected_downside=payload[\"expected_downside\"],\n                    horizon_days=payload[\"horizon_days\"],\n                    catalysts=tuple(payload[\"catalysts\"]),\n                    invalidation_conditions=tuple(payload[\"invalidation_conditions\"]),\n                    monitoring_indicators=tuple(payload[\"monitoring_indicators\"]),\n                    initial_confidence=payload[\"initial_confidence\"],\n                    current_confidence=payload[\"current_confidence\"],\n                    evidence_identifiers=tuple(payload[\"evidence_identifiers\"]),\n                    performance_since_approval=payload[\"performance_since_approval\"],\n                    next_review_at=datetime.fromisoformat(payload[\"next_review_at\"]),\n                    review_count=payload.get(\"review_count\", 0),\n                    ownership_episode_identifier=(\n                        payload.get(\"ownership_episode_identifier\")\n                        or payload[\"identifier\"]\n                    ),\n                )\n            )\n        return tuple(sorted(values, key=lambda item: item.asset))\n'''
replace_one(
    "cio/persistence.py",
    "    def count(self) -> int:\n",
    continuity_methods + "\n    def count(self) -> int:\n",
)

# Cycle accepts prior thesis snapshots and continues ownership episodes.
replace_one(
    "application/cio_cycle.py",
    "        prior_decision_contexts: tuple[PriorDecisionContext, ...] = (),\n        code_version: str | None = None,\n",
    "        prior_decision_contexts: tuple[PriorDecisionContext, ...] = (),\n        active_theses: tuple[LivingThesis, ...] = (),\n        code_version: str | None = None,\n",
)
replace_one(
    "application/cio_cycle.py",
    "        prior_map = {item.candidate_identifier: item for item in prior_decision_contexts}\n",
    "        prior_map = {item.candidate_identifier: item for item in prior_decision_contexts}\n        if not isinstance(active_theses, tuple) or not all(\n            isinstance(item, LivingThesis) for item in active_theses\n        ):\n            raise TypeError(\"active_theses must contain LivingThesis values\")\n",
)
replace_one(
    "application/cio_cycle.py",
    "            portfolio=portfolio,\n            code_version=code_version,\n        )\n",
    "            portfolio=portfolio,\n            active_theses=active_theses,\n            code_version=code_version,\n        )\n",
)
new_create_theses = '''    def _create_theses(\n        self,\n        *,\n        decisions: tuple[CIODecision, ...],\n        ranked_by_candidate: dict[str, object],\n        construction: PortfolioConstructionResult | None,\n        portfolio: CyclePortfolioState,\n        active_theses: tuple[LivingThesis, ...],\n        code_version: str | None,\n    ) -> tuple[LivingThesis, ...]:\n        target_weights = {} if construction is None else dict(construction.target_weights)\n        existing_by_asset = {item.asset: item for item in active_theses}\n        theses: list[LivingThesis] = []\n        for decision in decisions:\n            ranked = ranked_by_candidate[decision.candidate_identifier]\n            candidate = ranked.candidate\n            symbol = candidate.instrument.symbol\n            current = portfolio.current_weight(symbol)\n            implemented = target_weights.get(symbol, current)\n            existing = existing_by_asset.get(symbol)\n            thesis: LivingThesis | None = None\n            if existing is None:\n                if decision.action in {CIOAction.BUY, CIOAction.INCREASE} and implemented > current + 0.000001:\n                    thesis = LivingThesis.from_decision(candidate, decision)\n            else:\n                if decision.action is CIOAction.EXIT and implemented > 0.000001:\n                    continue\n                if decision.action is CIOAction.REDUCE and implemented >= current - 0.000001:\n                    continue\n                if decision.action in {\n                    CIOAction.BUY,\n                    CIOAction.INCREASE,\n                    CIOAction.HOLD,\n                    CIOAction.REDUCE,\n                    CIOAction.EXIT,\n                    CIOAction.NO_MATERIAL_CHANGE,\n                }:\n                    thesis = existing.continue_from_decision(candidate, decision)\n            if thesis is None:\n                continue\n            theses.append(thesis)\n            if self.journal is not None:\n                self.journal.append_thesis_snapshot(thesis, code_version=code_version)\n        return tuple(theses)\n\n'''
regex_one(
    "application/cio_cycle.py",
    r"    def _create_theses\(.*?\n    def _journal_candidates_and_queue\(",
    new_create_theses + "    def _journal_candidates_and_queue(",
)

# Scheduled production path activates journal-derived state continuity.
for path in ("application/production_cio.py", "application/production_context.py"):
    replace_one(
        path,
        "        return self.cycle.run(\n",
        "        prior_contexts = ()\n        active_theses = ()\n        if self.cycle.journal is not None:\n            prior_contexts = self.cycle.journal.prior_decision_contexts(\n                candidates, as_of=decision_time\n            )\n            active_theses = self.cycle.journal.active_theses(\n                candidates, as_of=decision_time\n            )\n        return self.cycle.run(\n",
    )
    replace_one(
        path,
        "            portfolio=portfolio,\n            code_version=context.code_version,\n",
        "            portfolio=portfolio,\n            prior_decision_contexts=prior_contexts,\n            active_theses=active_theses,\n            code_version=context.code_version,\n",
    ) if path.endswith("production_context.py") else replace_one(
        path,
        "            portfolio=context.portfolio,\n            code_version=context.code_version,\n",
        "            portfolio=context.portfolio,\n            prior_decision_contexts=prior_contexts,\n            active_theses=active_theses,\n            code_version=context.code_version,\n",
    )
