from __future__ import annotations

from datetime import datetime, timezone

from cio_pending_transactions import build_pending_transaction_report


AS_OF = "2026-08-30T16:57:44.753850+00:00"
GENERATED_AT = datetime(2026, 8, 30, 17, 0, tzinfo=timezone.utc)


def _current_non_transaction_briefing() -> dict[str, object]:
    return {
        "identifier": f"daily-cio:{AS_OF}",
        "decision_identifier": "decision:btc-hold",
        "candidate_identifier": "candidate:btc",
        "cio_decision_count": 1,
        "as_of": AS_OF,
        "status": "current",
        "construction_status": None,
        "portfolio_decision": (
            "CIO decision: hold. No executable portfolio change is proposed."
        ),
    }


def test_current_non_transaction_cio_decision_is_governed_no_action() -> None:
    report = build_pending_transaction_report(
        construction=None,
        briefing=_current_non_transaction_briefing(),
        generated_at=GENERATED_AT,
        execution_state="idle",
    )

    assert report["report_state"] == "no_transaction_recommended"
    assert report["safe_abstention_recorded"] is True
    assert report["comparative_cio_decision_complete"] is False
    assert report["decision_identifier"] == "decision:btc-hold"
    assert report["decision_as_of"] == AS_OF
    assert report["transaction_count"] == 0
    assert report["execution_state"] == "idle"
    assert report["paper_only"] is True
    assert report["real_money_authorized"] is False


def test_missing_exact_construction_is_not_reclassified_as_no_action() -> None:
    briefing = {
        **_current_non_transaction_briefing(),
        "decision_identifier": "decision:btc-buy",
        "construction_status": "feasible",
        "portfolio_decision": (
            "CIO decision: buy. Proposed implementation: buy BTC from 0.00% to 5.00%."
        ),
    }

    report = build_pending_transaction_report(
        construction=None,
        briefing=briefing,
        generated_at=GENERATED_AT,
        execution_state="idle",
    )

    assert report["report_state"] == "awaiting_cio_construction"
    assert report["safe_abstention_recorded"] is False
    assert report["transaction_count"] == 0
    assert report["execution_state"] == "idle"


def test_incomplete_current_briefing_stays_fail_closed() -> None:
    briefing = {
        **_current_non_transaction_briefing(),
        "decision_identifier": "",
    }

    report = build_pending_transaction_report(
        construction=None,
        briefing=briefing,
        generated_at=GENERATED_AT,
        execution_state="idle",
    )

    assert report["report_state"] == "awaiting_cio_construction"
    assert report["safe_abstention_recorded"] is False
