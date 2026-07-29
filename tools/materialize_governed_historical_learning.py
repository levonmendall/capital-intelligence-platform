from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    source = target.read_text(encoding="utf-8")
    if old not in source:
        raise RuntimeError(f"expected materialization anchor missing in {path}: {old[:160]!r}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")


replace_once(
    "committee/specialists.py",
    "from dataclasses import dataclass\n",
    "from dataclasses import dataclass, replace\n",
)
replace_once(
    "committee/specialists.py",
    "        analyses = (\n"
    "            self._macro(candidate, context),\n"
    "            self._market(candidate, context),\n"
    "            self._forecast(candidate, context),\n"
    "            self._fundamental(candidate, context),\n"
    "            self._portfolio(candidate, context),\n"
    "            self._evidence(candidate, context),\n"
    "        )\n"
    "        return IndependentSpecialistPacket(\n",
    "        analyses = (\n"
    "            self._macro(candidate, context),\n"
    "            self._market(candidate, context),\n"
    "            self._forecast(candidate, context),\n"
    "            self._fundamental(candidate, context),\n"
    "            self._portfolio(candidate, context),\n"
    "            self._evidence(candidate, context),\n"
    "        )\n"
    "        if context.historical_learning is not None:\n"
    "            analyses = tuple(\n"
    "                self._historically_calibrate(item, context.historical_learning)\n"
    "                for item in analyses\n"
    "            )\n"
    "        return IndependentSpecialistPacket(\n",
)
replace_once(
    "committee/specialists.py",
    "    @staticmethod\n"
    "    def _completed(\n"
    "        context: CandidateSpecialistContext,\n"
    "        offset: int,\n"
    "    ) -> datetime:\n"
    "        return context.analysis_completed_at + timedelta(microseconds=offset)\n\n"
    "    def _macro(\n",
    "    @staticmethod\n"
    "    def _completed(\n"
    "        context: CandidateSpecialistContext,\n"
    "        offset: int,\n"
    "    ) -> datetime:\n"
    "        return context.analysis_completed_at + timedelta(microseconds=offset)\n\n"
    "    @staticmethod\n"
    "    def _historically_calibrate(\n"
    "        analysis: SpecialistAnalysis,\n"
    "        learning: HistoricalLearningContext,\n"
    "    ) -> SpecialistAnalysis:\n"
    "        supporting = analysis.supporting_evidence\n"
    "        if learning.status.value in {\"available\", \"limited\"}:\n"
    "            supporting = tuple(\n"
    "                dict.fromkeys(supporting + (learning.summary,))\n"
    "            )\n"
    "        contradictory = analysis.contradictory_evidence\n"
    "        if (\n"
    "            learning.realized_sample_size > 0\n"
    "            and learning.historical_hit_rate < 0.50\n"
    "        ):\n"
    "            contradictory = tuple(\n"
    "                dict.fromkeys(\n"
    "                    contradictory\n"
    "                    + (\n"
    "                        \"Comparable historical outcomes were positive in fewer \"\n"
    "                        \"than half of measured next-cutoff periods.\",\n"
    "                    )\n"
    "                )\n"
    "            )\n"
    "        return replace(\n"
    "            analysis,\n"
    "            confidence=min(analysis.confidence, learning.confidence_ceiling),\n"
    "            supporting_evidence=supporting,\n"
    "            contradictory_evidence=contradictory,\n"
    "            limitations=tuple(\n"
    "                dict.fromkeys(analysis.limitations + learning.limitations)\n"
    "            ),\n"
    "            evidence_origin_identifiers=tuple(\n"
    "                dict.fromkeys(\n"
    "                    analysis.evidence_origin_identifiers\n"
    "                    + learning.evidence_identifiers\n"
    "                )\n"
    "            ),\n"
    "        )\n\n"
    "    def _macro(\n",
)

replace_once(
    "cio/service.py",
    "        feasible_cap = min(\n"
    "            portfolio.recommended_position_weight,\n"
    "            candidate.maximum_position_weight,\n"
    "            profile.maximum_position_weight,\n"
    "        )\n"
    "        if feasible_cap <= 0.0:\n",
    "        feasible_cap = min(\n"
    "            portfolio.recommended_position_weight,\n"
    "            candidate.maximum_position_weight,\n"
    "            profile.maximum_position_weight,\n"
    "        )\n"
    "        feasible_cap = round(\n"
    "            feasible_cap\n"
    "            * specialists.historical_learning.position_size_multiplier,\n"
    "            8,\n"
    "        )\n"
    "        if feasible_cap <= 0.0:\n",
)

replace_once(
    "historical_replay/canonical.py",
    "    @staticmethod\n"
    "    def _decision_payload(decision: object) -> dict[str, Any]:\n"
    "        return {\n"
    "            \"identifier\": getattr(decision, \"identifier\"),\n"
    "            \"candidate_identifier\": getattr(decision, \"candidate_identifier\"),\n"
    "            \"action\": getattr(getattr(decision, \"action\"), \"value\"),\n"
    "            \"final_confidence\": getattr(decision, \"final_confidence\"),\n"
    "            \"expected_return\": getattr(decision, \"expected_return\"),\n"
    "            \"recommended_position_weight\": getattr(\n"
    "                decision, \"recommended_position_weight\"\n"
    "            ),\n"
    "            \"funding_source\": getattr(decision, \"funding_source\"),\n"
    "            \"evidence_vetoes\": list(getattr(decision, \"evidence_vetoes\")),\n"
    "            \"implementation_blocks\": list(\n"
    "                getattr(decision, \"implementation_blocks\")\n"
    "            ),\n"
    "            \"explanation\": getattr(decision, \"explanation\"),\n"
    "        }\n\n"
    "    def run(\n",
    "    @staticmethod\n"
    "    def _decision_payload(\n"
    "        decision: object,\n"
    "        *,\n"
    "        candidate: CandidateDecisionRecord | None = None,\n"
    "        context: CandidateCycleContext | None = None,\n"
    "    ) -> dict[str, Any]:\n"
    "        payload = {\n"
    "            \"identifier\": getattr(decision, \"identifier\"),\n"
    "            \"candidate_identifier\": getattr(decision, \"candidate_identifier\"),\n"
    "            \"action\": getattr(getattr(decision, \"action\"), \"value\"),\n"
    "            \"final_confidence\": getattr(decision, \"final_confidence\"),\n"
    "            \"expected_return\": getattr(decision, \"expected_return\"),\n"
    "            \"decision_horizon_days\": getattr(\n"
    "                decision, \"decision_horizon_days\"\n"
    "            ),\n"
    "            \"recommended_position_weight\": getattr(\n"
    "                decision, \"recommended_position_weight\"\n"
    "            ),\n"
    "            \"funding_source\": getattr(decision, \"funding_source\"),\n"
    "            \"evidence_vetoes\": list(getattr(decision, \"evidence_vetoes\")),\n"
    "            \"implementation_blocks\": list(\n"
    "                getattr(decision, \"implementation_blocks\")\n"
    "            ),\n"
    "            \"explanation\": getattr(decision, \"explanation\"),\n"
    "        }\n"
    "        if candidate is not None:\n"
    "            payload.update(\n"
    "                {\n"
    "                    \"symbol\": candidate.instrument.symbol,\n"
    "                    \"asset_class\": candidate.instrument.asset_class.value,\n"
    "                    \"model_versions\": list(candidate.model_versions),\n"
    "                }\n"
    "            )\n"
    "        if context is not None:\n"
    "            payload.update(\n"
    "                {\n"
    "                    \"macro_regime\": context.macro.regime,\n"
    "                    \"market_regime\": context.market.market_regime,\n"
    "                }\n"
    "            )\n"
    "        return payload\n\n"
    "    @staticmethod\n"
    "    def _attach_realized_outcomes(\n"
    "        cutoffs: list[dict[str, Any]],\n"
    "    ) -> None:\n"
    "        for index, current in enumerate(cutoffs[:-1]):\n"
    "            if current.get(\"state\") != \"completed\":\n"
    "                continue\n"
    "            next_completed = next(\n"
    "                (\n"
    "                    item\n"
    "                    for item in cutoffs[index + 1 :]\n"
    "                    if item.get(\"state\") == \"completed\"\n"
    "                ),\n"
    "                None,\n"
    "            )\n"
    "            if next_completed is None:\n"
    "                continue\n"
    "            current_prices = dict(current.get(\"prices\") or {})\n"
    "            next_prices = dict(next_completed.get(\"prices\") or {})\n"
    "            current_at = datetime.fromisoformat(\n"
    "                str(current[\"cutoff\"]).replace(\"Z\", \"+00:00\")\n"
    "            )\n"
    "            next_at = datetime.fromisoformat(\n"
    "                str(next_completed[\"cutoff\"]).replace(\"Z\", \"+00:00\")\n"
    "            )\n"
    "            horizon_days = max(1, (next_at - current_at).days)\n"
    "            for decision in current.get(\"decisions\", []):\n"
    "                if not isinstance(decision, dict):\n"
    "                    continue\n"
    "                symbol = str(decision.get(\"symbol\") or \"\").upper()\n"
    "                current_price = current_prices.get(symbol)\n"
    "                next_price = next_prices.get(symbol)\n"
    "                if not isinstance(current_price, (int, float)) or not isinstance(\n"
    "                    next_price, (int, float)\n"
    "                ):\n"
    "                    continue\n"
    "                if float(current_price) <= 0.0:\n"
    "                    continue\n"
    "                decision[\"realized_return_to_next_cutoff\"] = round(\n"
    "                    float(next_price) / float(current_price) - 1.0,\n"
    "                    8,\n"
    "                )\n"
    "                decision[\"realized_horizon_days\"] = horizon_days\n\n"
    "    def run(\n",
)
replace_once(
    "historical_replay/canonical.py",
    "                result = self.cycle.run(\n"
    "                    identifier=f\"historical-canonical-cycle:{cutoff_date}\",\n"
    "                    candidates=candidates,\n"
    "                    opportunity_context=opportunity,\n"
    "                    specialist_contexts=contexts,\n"
    "                    portfolio=portfolio,\n"
    "                    code_version=\"historical-canonical-replay.v1\",\n"
    "                )\n"
    "                state.apply_construction(result.construction)\n",
    "                result = self.cycle.run(\n"
    "                    identifier=f\"historical-canonical-cycle:{cutoff_date}\",\n"
    "                    candidates=candidates,\n"
    "                    opportunity_context=opportunity,\n"
    "                    specialist_contexts=contexts,\n"
    "                    portfolio=portfolio,\n"
    "                    code_version=\"historical-canonical-replay.v2\",\n"
    "                )\n"
    "                candidate_map = {item.identifier: item for item in candidates}\n"
    "                context_map = {\n"
    "                    item.candidate_identifier: item for item in contexts\n"
    "                }\n"
    "                decision_payloads = [\n"
    "                    self._decision_payload(\n"
    "                        item,\n"
    "                        candidate=candidate_map.get(item.candidate_identifier),\n"
    "                        context=context_map.get(item.candidate_identifier),\n"
    "                    )\n"
    "                    for item in result.decisions\n"
    "                ]\n"
    "                state.apply_construction(result.construction)\n",
)
replace_once(
    "historical_replay/canonical.py",
    "                    \"decisions\": [\n"
    "                        self._decision_payload(item) for item in result.decisions\n"
    "                    ],\n"
    "                    \"construction\": (\n",
    "                    \"decisions\": decision_payloads,\n"
    "                    \"prices\": dict(prices),\n"
    "                    \"macro_regime\": (\n"
    "                        contexts[0].macro.regime if contexts else \"unavailable\"\n"
    "                    ),\n"
    "                    \"construction\": (\n",
)
replace_once(
    "historical_replay/canonical.py",
    "            decisions.append(payload)\n"
    "        report = {\n"
    "            \"schema_version\": \"canonical-historical-replay.v1\",\n",
    "            decisions.append(payload)\n"
    "        self._attach_realized_outcomes(decisions)\n"
    "        report = {\n"
    "            \"schema_version\": \"canonical-historical-replay.v2\",\n",
)

replace_once(
    "docs/HISTORICAL_REPLAY.md",
    "Historical learning is deliberately one-way and subordinate to current\n"
    "evidence:\n",
    "Historical learning is matched by exact symbol when possible, then by asset\n"
    "class, with current macro regime, market regime, and decision horizon used as\n"
    "additional comparability gates. Updated replay manifests also carry\n"
    "next-cutoff realized returns so support frequency is not confused with actual\n"
    "outcome quality. Historical learning is deliberately one-way and subordinate\n"
    "to current evidence:\n",
)

Path("tests/test_governed_historical_learning.py").write_text(
    '''from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
    HistoricalLearningContext,
    HistoricalLearningResolver,
    HistoricalLearningStatus,
)

UTC = timezone.utc


def _candidate(as_of: datetime) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        identifier="candidate:spy",
        as_of=as_of,
        schema_version="candidate.v1",
        instrument=CandidateInstrument(
            instrument_id="instrument:spy",
            symbol="SPY",
            name="SPDR S&P 500 ETF",
            asset_class=CandidateAssetClass.US_ETF,
            venue="ARCX",
            country_code="US",
            average_daily_dollar_volume=1_000_000_000.0,
            data_age_hours=0.1,
            analytical_coverage=1.0,
            security_master_snapshot_identifier="security-master:now",
            security_master_record_identifiers=("security-master:spy",),
            instrument_type="etf",
        ),
        current_price=500.0,
        decision_horizon_days=365,
        base_case_return=0.10,
        bull_case_return=0.20,
        bear_case_return=-0.15,
        base_case_probability=0.50,
        bull_case_probability=0.25,
        bear_case_probability=0.25,
        estimated_fair_value=550.0,
        expected_upside=0.20,
        expected_downside=-0.15,
        probability_of_success=0.65,
        primary_catalysts=("earnings growth",),
        key_risks=("recession",),
        critical_assumptions=("growth persists",),
        invalidation_conditions=("trend breaks",),
        supporting_evidence=("current evidence",),
        contradictory_evidence=(),
        evidence_quality=EvidenceQuality(0.9, 0.9, 0.9, 0.8, 0.8, 0.9),
        liquidity_score=1.0,
        transaction_cost_bps=1.0,
        slippage_bps=1.0,
        opportunity_cost_return=0.04,
        expected_portfolio_contribution=0.01,
        current_portfolio_weight=0.0,
        maximum_position_weight=0.10,
        monitoring_indicators=("trend",),
        review_at=as_of + timedelta(days=30),
        evidence_identifiers=("evidence:current",),
        model_versions=("model:v1",),
    )


def _manifest(generated_at: datetime) -> dict[str, object]:
    decisions = []
    realized = (0.03, 0.02, -0.01, 0.04, -0.02, 0.01)
    for month, outcome in enumerate(realized, start=1):
        decisions.append(
            {
                "cutoff": f"2026-{month:02d}-28T23:59:59+00:00",
                "state": "completed",
                "canonical_cio_invoked": True,
                "macro_regime": "mixed",
                "decisions": [
                    {
                        "candidate_identifier": f"historical:2026-{month:02d}-28:SPY",
                        "symbol": "SPY",
                        "asset_class": "us_etf",
                        "macro_regime": "mixed",
                        "market_regime": "positive_trend",
                        "decision_horizon_days": 365,
                        "action": "buy" if month < 5 else "watch",
                        "final_confidence": 0.80,
                        "recommended_position_weight": 0.10,
                        "realized_return_to_next_cutoff": outcome,
                    }
                ],
            }
        )
    return {
        "schema_version": "canonical-historical-replay.v2",
        "generated_at": generated_at.isoformat(),
        "strict_only": False,
        "decisions": decisions,
    }


def test_resolver_attaches_restrictive_outcome_and_regime_context(tmp_path) -> None:
    as_of = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)
    manifest = tmp_path / "latest-canonical-replay.json"
    manifest.write_text(
        json.dumps(_manifest(as_of - timedelta(hours=1))),
        encoding="utf-8",
    )
    context = HistoricalLearningResolver(manifest).resolve(
        _candidate(as_of),
        as_of=as_of,
        macro_regime="mixed",
        market_regime="positive_trend",
    )

    assert context.status is HistoricalLearningStatus.AVAILABLE
    assert context.sample_size == 6
    assert context.exact_symbol_sample_size == 6
    assert context.regime_matched_sample_size == 6
    assert context.horizon_matched_sample_size == 6
    assert context.realized_sample_size == 6
    assert context.historical_hit_rate == pytest.approx(4 / 6)
    assert context.median_realized_return > 0.0
    assert context.worst_realized_return == -0.02
    assert 0.0 < context.position_size_multiplier <= 1.0
    assert 0.0 < context.confidence_ceiling <= 1.0
    assert context.subordinate_to_current_evidence is True
    assert context.may_increase_expected_return is False
    assert context.may_increase_confidence is False
    assert context.may_increase_position_size is False
    assert context.execution_authorized is False
    assert context.policy_promotion_authorized is False


def test_future_manifest_is_rejected(tmp_path) -> None:
    as_of = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)
    manifest = tmp_path / "latest-canonical-replay.json"
    manifest.write_text(
        json.dumps(_manifest(as_of + timedelta(seconds=1))),
        encoding="utf-8",
    )
    context = HistoricalLearningResolver(manifest).resolve(
        _candidate(as_of),
        as_of=as_of,
        macro_regime="mixed",
        market_regime="positive_trend",
    )

    assert context.status is HistoricalLearningStatus.UNAVAILABLE
    assert context.position_size_multiplier == 0.50
    assert "after the decision timestamp" in context.summary


def test_historical_learning_cannot_grant_positive_authority() -> None:
    as_of = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="cannot strengthen"):
        HistoricalLearningContext(
            candidate_identifier="candidate:spy",
            as_of=as_of,
            status=HistoricalLearningStatus.AVAILABLE,
            source_manifest_identifier="manifest:1",
            sample_size=12,
            exact_symbol_sample_size=12,
            regime_matched_sample_size=12,
            horizon_matched_sample_size=12,
            realized_sample_size=12,
            strict_replay=True,
            support_rate=1.0,
            abstention_rate=0.0,
            historical_hit_rate=1.0,
            median_historical_confidence=0.9,
            median_historical_position_weight=0.1,
            median_realized_return=0.02,
            worst_realized_return=-0.05,
            position_size_multiplier=1.0,
            confidence_ceiling=1.0,
            summary="invalid authority test",
            limitations=(),
            evidence_identifiers=("manifest:1",),
            may_increase_position_size=True,
        )


def test_live_cycle_committee_and_cio_apply_historical_controls() -> None:
    cycle_source = open("application/cio_cycle.py", encoding="utf-8").read()
    specialist_source = open("committee/specialists.py", encoding="utf-8").read()
    cio_source = open("cio/service.py", encoding="utf-8").read()
    persistence_source = open("cio/persistence.py", encoding="utf-8").read()
    replay_source = open("historical_replay/canonical.py", encoding="utf-8").read()

    assert "historical_learning_resolver.resolve" in cycle_source
    assert "historical_learning=historical_learning" in cycle_source
    assert "self._historically_calibrate" in specialist_source
    assert "learning.confidence_ceiling" in specialist_source
    assert "assessment_cap * historical_learning.position_size_multiplier" in cio_source
    assert "specialists.historical_learning.position_size_multiplier" in cio_source
    assert "historical_learning.confidence_ceiling" in cio_source
    assert '"historical_learning": packet.historical_learning.as_dict()' in persistence_source
    assert "realized_return_to_next_cutoff" in replay_source
    assert '"market_regime": context.market.market_regime' in replay_source
''',
    encoding="utf-8",
)
