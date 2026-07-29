from __future__ import annotations

from datetime import datetime, timezone

from cio_pending_transactions import build_pending_transaction_report


def _completed_no_action_briefing() -> dict[str, object]:
    return {
        "identifier": "daily-cio:2026-07-29T20:44:00+00:00",
        "as_of": "2026-07-29T20:44:00+00:00",
        "status": "no_superior_opportunity",
        "portfolio_decision": "No portfolio action is required.",
        "decision_identifier": None,
    }


def test_completed_governed_no_action_does_not_await_construction() -> None:
    report = build_pending_transaction_report(
        construction=None,
        briefing=_completed_no_action_briefing(),
        generated_at=datetime(2026, 7, 29, 21, 49, tzinfo=timezone.utc),
        execution_state="idle",
    )

    assert report["report_state"] == "no_transaction_recommended"
    assert report["summary"] == "No portfolio action is required."
    assert report["transaction_count"] == 0
    assert report["execution_state"] == "idle"
    assert report["paper_only"] is True
    assert report["real_money_authorized"] is False


def test_missing_briefing_still_awaits_cio_construction() -> None:
    report = build_pending_transaction_report(
        construction=None,
        briefing=None,
        generated_at=datetime(2026, 7, 29, 21, 49, tzinfo=timezone.utc),
    )

    assert report["report_state"] == "awaiting_cio_construction"
    assert report["transaction_count"] == 0


def test_unavailable_briefing_does_not_claim_a_governed_outcome() -> None:
    briefing = {
        **_completed_no_action_briefing(),
        "status": "unavailable",
        "portfolio_decision": "No portfolio action is permitted.",
    }
    report = build_pending_transaction_report(
        construction=None,
        briefing=briefing,
        generated_at=datetime(2026, 7, 29, 21, 49, tzinfo=timezone.utc),
    )

    assert report["report_state"] == "awaiting_cio_construction"
