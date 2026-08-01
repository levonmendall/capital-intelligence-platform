from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cio import CIOAction, CIODecision
from cio.cycle_disposition import CIOCycleDispositionAuthority
from cio.decision_integrity import normalize_final_decision
from opportunity import OpportunityQueue
from operations.active_paper_universe import (
    load_active_paper_universe_for_publication,
)
from operations.free_paper_pilot import (
    free_paper_pilot_universe_payload,
    load_free_paper_pilot_universe,
)
from portfolio.production_scenarios import build_governed_portfolio_scenario_set
from reporting.daily_cio import DailyCIOBriefingBuilder, DailyCIOStatus
import run_autonomous_paper_operator as operator


NOW = datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc)


def test_active_universe_loader_requires_exact_publication(tmp_path):
    universe = load_free_paper_pilot_universe()
    path = tmp_path / "active-paper-universe.json"
    path.write_text(
        json.dumps(
            {
                "eligible_universe_publication_identifier": "eligible:current",
                "universe": free_paper_pilot_universe_payload(universe),
            }
        ),
        encoding="utf-8",
    )

    loaded = load_active_paper_universe_for_publication(
        "eligible:current",
        path=path,
    )
    assert loaded.identifier == universe.identifier

    with pytest.raises(ValueError, match="does not match"):
        load_active_paper_universe_for_publication(
            "eligible:old",
            path=path,
        )


def _scenario_candidate(symbol: str, base: float):
    return SimpleNamespace(
        instrument=SimpleNamespace(symbol=symbol),
        decision_horizon_days=365,
        bear_case_return=base - 0.20,
        base_case_return=base,
        bull_case_return=base + 0.20,
        bear_case_probability=0.25,
        base_case_probability=0.50,
        bull_case_probability=0.25,
        evidence_identifiers=(f"evidence:{symbol}",),
        model_versions=(("candidate", "v1"),),
    )


def test_common_portfolio_scenarios_cover_every_candidate():
    scenario_set = build_governed_portfolio_scenario_set(
        identifier="scenario-set:test",
        source_identifier="publication:test",
        as_of=NOW,
        knowledge_cutoff=NOW,
        candidates=(
            _scenario_candidate("BTCUSD", 0.10),
            _scenario_candidate("VTI", 0.08),
        ),
        cash_expected_return=0.04,
    )

    assert scenario_set.symbols == {"BTCUSD", "VTI"}
    assert len(scenario_set.scenarios) == 3
    assert sum(item.probability for item in scenario_set.scenarios) == pytest.approx(1.0)
    scenario_set.validate_coverage({"BTCUSD", "VTI"})


def test_scenario_lineage_never_exceeds_the_decision_time():
    scenario_set = build_governed_portfolio_scenario_set(
        identifier="scenario-set:later-publication",
        source_identifier="publication:later",
        as_of=NOW,
        knowledge_cutoff=NOW + timedelta(hours=1),
        candidates=(_scenario_candidate("VTI", 0.08),),
        cash_expected_return=0.04,
    )

    assert scenario_set.as_of == NOW
    assert scenario_set.knowledge_cutoff == NOW


def test_empty_queue_receives_explicit_cio_disposition():
    queue = OpportunityQueue(
        context_identifier="opportunity:test",
        policy_version="policy:test",
        ranked=(),
        rejected=(),
    )

    disposition = CIOCycleDispositionAuthority().decide(queue, as_of=NOW)

    assert disposition is not None
    assert disposition.action is CIOAction.INSUFFICIENT_EVIDENCE
    assert disposition.authority == "CHIEF_INVESTMENT_OFFICER"
    assert disposition.classification == "evidence_or_authority_block"


def _reduce_to_zero_decision() -> CIODecision:
    return CIODecision(
        identifier="decision:test",
        candidate_identifier="candidate:test",
        as_of=NOW,
        schema_version="cio-decision.v3",
        action=CIOAction.REDUCE,
        final_confidence=0.60,
        expected_return=-0.01,
        decision_horizon_days=365,
        recommended_position_weight=0.0,
        funding_source=None,
        thesis="Reduce TEST: evidence changed.",
        rationale="The robust supported weight is zero.",
        supporting_evidence=("evidence",),
        contradictory_evidence=(),
        key_assumptions=("assumption",),
        catalysts=("catalyst",),
        risks=("risk",),
        invalidation_conditions=("condition",),
        portfolio_impact="Reduce toward a 0.00% portfolio weight.",
        opportunity_cost="cash",
        dissent=None,
        evidence_vetoes=(),
        implementation_blocks=(),
        monitoring_indicators=("indicator",),
        review_at=NOW + timedelta(days=1),
        explanation="CIO decision: reduce. The target is zero.",
        policy_version="policy:test",
    )


def test_zero_weight_reduction_is_normalized_to_exit():
    normalized = normalize_final_decision(_reduce_to_zero_decision())

    assert normalized.action is CIOAction.EXIT
    assert normalized.recommended_position_weight == 0.0
    assert normalized.thesis.startswith("Exit ")
    assert "complete exit" in normalized.rationale


def test_daily_briefing_reports_cycle_disposition_identifier():
    queue = OpportunityQueue(
        context_identifier="opportunity:test",
        policy_version="policy:test",
        ranked=(),
        rejected=(),
    )
    disposition = CIOCycleDispositionAuthority().decide(queue, as_of=NOW)
    assert disposition is not None

    briefing = DailyCIOBriefingBuilder().build(
        as_of=NOW,
        queue=queue,
        decisions=(),
        construction=None,
        theses=(),
        cycle_disposition=disposition,
    )

    assert briefing.status is DailyCIOStatus.INSUFFICIENT_EVIDENCE
    assert briefing.decision_identifier == disposition.identifier
    assert "CIO decision" in briefing.portfolio_decision


def test_operator_rejects_prior_cycle_journal_artifacts(monkeypatch):
    old = NOW - timedelta(days=1)

    class FakeJournal:
        def __init__(self, *_args, **_kwargs):
            pass

        def latest_payload(self, event_type):
            if event_type == "portfolio_construction":
                return {"as_of": old.isoformat(), "trades": []}
            return {
                "as_of": old.isoformat(),
                "decision_identifier": "decision:old",
            }

    monkeypatch.setattr(operator, "JournalRepository", FakeJournal)
    settings = SimpleNamespace(journal_database="unused")

    construction, briefing = operator._payloads(
        settings,
        expected_as_of=NOW,
    )

    assert construction is None
    assert briefing is None


def test_operator_accepts_exact_current_cycle_artifacts(monkeypatch):
    class FakeJournal:
        def __init__(self, *_args, **_kwargs):
            pass

        def latest_payload(self, event_type):
            if event_type == "portfolio_construction":
                return {"as_of": NOW.isoformat(), "trades": []}
            return {
                "as_of": NOW.isoformat(),
                "decision_identifier": "decision:current",
            }

    monkeypatch.setattr(operator, "JournalRepository", FakeJournal)
    settings = SimpleNamespace(journal_database="unused")

    construction, briefing = operator._payloads(
        settings,
        expected_as_of=NOW,
    )

    assert construction is not None
    assert briefing is not None
