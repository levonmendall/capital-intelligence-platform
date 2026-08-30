from __future__ import annotations

import run_manual_cio_diagnostic as diagnostic


AS_OF = "2026-08-30T19:06:36.031815+00:00"


def test_ranked_current_no_transaction_stays_non_terminal_for_release_diagnostic() -> None:
    briefing = {
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

    assert diagnostic._governed_no_action(briefing) is False


def test_explicit_empty_queue_no_action_remains_terminal() -> None:
    briefing = {
        "identifier": f"daily-cio:{AS_OF}",
        "as_of": AS_OF,
        "status": "no_superior_opportunity",
        "portfolio_decision": "No qualified opportunity exceeded the cash hurdle.",
    }

    assert diagnostic._governed_no_action(briefing) is True
