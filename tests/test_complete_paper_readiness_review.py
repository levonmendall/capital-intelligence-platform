from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cio_pending_transactions import build_pending_transaction_report
from opportunity import OpportunityQueue
from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    load_free_paper_pilot_universe,
)
from reporting.daily_cio import DailyCIOBriefingBuilder, DailyCIOStatus
from run_scheduler import _paper_pilot_construction_policy


NOW = datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc)


def test_empty_review_queue_reports_insufficient_evidence() -> None:
    briefing = DailyCIOBriefingBuilder().build(
        as_of=NOW,
        queue=OpportunityQueue(
            context_identifier="opportunity:test",
            policy_version="opportunity-test.v1",
            ranked=(),
            rejected=(),
        ),
        decisions=(),
        construction=None,
        theses=(),
    )

    assert briefing.status is DailyCIOStatus.INSUFFICIENT_EVIDENCE
    assert "The comparative opportunity set is incomplete" in briefing.material_developments
    assert briefing.portfolio_decision == "No portfolio action is permitted."


def test_safe_abstention_is_not_a_completed_comparative_decision() -> None:
    report = build_pending_transaction_report(
        construction=None,
        briefing={
            "identifier": "daily-cio:test",
            "as_of": NOW.isoformat(),
            "status": "insufficient_evidence",
            "portfolio_decision": "No portfolio action is permitted.",
            "decision_identifier": None,
        },
        generated_at=NOW,
        execution_state="idle",
    )

    assert report["report_state"] == "no_transaction_recommended"
    assert report["safe_abstention_recorded"] is True
    assert report["comparative_cio_decision_complete"] is False


def test_no_superior_opportunity_is_a_completed_comparative_decision() -> None:
    report = build_pending_transaction_report(
        construction=None,
        briefing={
            "identifier": "daily-cio:test",
            "as_of": NOW.isoformat(),
            "status": "no_superior_opportunity",
            "portfolio_decision": "No portfolio action is required.",
            "decision_identifier": None,
        },
        generated_at=NOW,
        execution_state="idle",
    )

    assert report["comparative_cio_decision_complete"] is True


def test_scheduler_construction_policy_matches_paper_pilot() -> None:
    universe = load_free_paper_pilot_universe(DEFAULT_UNIVERSE_PATH)
    policy = _paper_pilot_construction_policy()

    assert policy.minimum_cash_weight == universe.minimum_cash_weight
    assert policy.maximum_turnover == universe.maximum_batch_turnover
    assert policy.maximum_position_weight <= universe.maximum_single_instrument_weight
    assert universe.identifier in policy.version


def test_zero_supported_weight_does_not_fall_back_to_assessment_cap() -> None:
    source = Path("cio/service.py").read_text(encoding="utf-8")

    assert "supported_weight or assessment_cap" not in source
    assert "self.robust_assessor.policy.minimum_reference_weight" in source


def test_smoke_test_requires_complete_provider_and_comparative_outcome() -> None:
    source = Path("production_smoke_test.py").read_text(encoding="utf-8")

    assert 'alpaca.get("expected_quote_count"' in source
    assert 'public_state.get("required_sources_ready") is True' in source
    assert 'cio_report.get("comparative_cio_decision_complete") is True' in source
