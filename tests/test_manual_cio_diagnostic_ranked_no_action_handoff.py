from __future__ import annotations

import run_manual_cio_diagnostic as diagnostic


AS_OF = "2026-08-30T16:57:44.753850+00:00"


def _ranked_non_transaction_briefing() -> dict[str, object]:
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


def test_ranked_current_non_transaction_decision_is_terminal_no_action() -> None:
    assert diagnostic._governed_no_action(_ranked_non_transaction_briefing()) is True


def test_missing_exact_construction_for_actionable_decision_stays_fail_closed() -> None:
    briefing = {
        **_ranked_non_transaction_briefing(),
        "decision_identifier": "decision:btc-buy",
        "construction_status": "feasible",
        "portfolio_decision": (
            "CIO decision: buy. Proposed implementation: buy BTC from 0.00% to 5.00%."
        ),
    }

    assert diagnostic._governed_no_action(briefing) is False


def test_incomplete_ranked_current_briefing_stays_fail_closed() -> None:
    briefing = {
        **_ranked_non_transaction_briefing(),
        "decision_identifier": "",
    }

    assert diagnostic._governed_no_action(briefing) is False


def test_existing_empty_queue_no_action_remains_terminal() -> None:
    briefing = {
        "identifier": f"daily-cio:{AS_OF}",
        "as_of": AS_OF,
        "status": "no_superior_opportunity",
        "portfolio_decision": "No qualified opportunity exceeded the cash hurdle.",
    }

    assert diagnostic._governed_no_action(briefing) is True
