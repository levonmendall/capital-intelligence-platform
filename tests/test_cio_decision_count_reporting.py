from datetime import datetime, timezone
from types import SimpleNamespace

from reporting.daily_cio import DailyCIOBriefing, DailyCIOStatus
from run_autonomous_paper_operator import _funnel


def test_daily_cio_briefing_serializes_actual_decision_count() -> None:
    briefing = DailyCIOBriefing(
        identifier="daily-cio:test",
        as_of=datetime(2026, 8, 9, tzinfo=timezone.utc),
        status=DailyCIOStatus.CURRENT,
        what_changed="A material catalyst changed the opportunity set.",
        why_it_matters="The expected portfolio return changed materially.",
        opportunity_or_risk="The candidate remains attractive after costs.",
        portfolio_decision="No executable portfolio change is proposed.",
        confidence=0.75,
        evidence_that_changes_conclusion=("Material new evidence",),
        material_developments=("Opportunity set changed",),
        decision_identifier="decision:1",
        cio_decision_count=3,
    )

    assert briefing.to_dict()["cio_decision_count"] == 3


def test_funnel_reports_all_cio_decision_records() -> None:
    publication = SimpleNamespace(
        instrument_count=12,
        candidate_count=5,
        qualified_candidate_count=3,
    )

    funnel = _funnel(
        context_publication=publication,
        briefing={
            "decision_identifier": "decision:1",
            "cio_decision_count": 3,
        },
        construction=None,
        execution_state="idle",
    )

    assert funnel["cio_decision_records"] == 3


def test_funnel_preserves_legacy_single_decision_fallback() -> None:
    funnel = _funnel(
        context_publication=None,
        briefing={"decision_identifier": "decision:legacy"},
        construction=None,
        execution_state="idle",
    )

    assert funnel["cio_decision_records"] == 1


def test_funnel_reports_zero_without_decision() -> None:
    funnel = _funnel(
        context_publication=None,
        briefing=None,
        construction=None,
        execution_state="idle",
    )

    assert funnel["cio_decision_records"] == 0
