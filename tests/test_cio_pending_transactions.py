from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from cio_pending_transactions import (
    DEFAULT_PAPER_TRADING_START_AT,
    build_pending_transaction_report,
    load_pending_transaction_report,
    paper_trading_launch_open,
    paper_trading_start_at,
    pending_transaction_report_history,
    pending_transaction_report_markdown,
    resolve_pending_transaction_report,
    write_pending_transaction_report,
)


def _construction() -> dict:
    return {
        "request_identifier": "construction:launch-vti",
        "as_of": "2026-07-29T11:00:00+00:00",
        "status": "feasible",
        "target_cash_weight": 0.90,
        "target_weights": [{"symbol": "VTI", "weight": 0.10}],
        "trades": [
            {
                "symbol": "VTI",
                "side": "buy",
                "from_weight": 0.0,
                "to_weight": 0.10,
                "trade_weight": 0.10,
                "estimated_cost_return": 0.0001,
                "reason": "Highest governed risk-adjusted opportunity after costs",
                "funding_for": [],
            }
        ],
        "turnover": 0.10,
        "estimated_cost_return": 0.0001,
        "expected_return_improvement": 0.012,
        "blocks": [],
    }


def _briefing() -> dict:
    return {
        "decision_identifier": "decision:launch-vti",
        "as_of": "2026-07-29T11:00:00+00:00",
    }


def test_default_launch_is_july_29_at_market_open(monkeypatch) -> None:
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_PAPER_TRADING_START_AT", raising=False)

    assert paper_trading_start_at() == DEFAULT_PAPER_TRADING_START_AT
    assert not paper_trading_launch_open(
        DEFAULT_PAPER_TRADING_START_AT - timedelta(seconds=1)
    )
    assert paper_trading_launch_open(DEFAULT_PAPER_TRADING_START_AT)


def test_launch_timestamp_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_PAPER_TRADING_START_AT",
        "2026-07-29T14:00:00+00:00",
    )

    assert paper_trading_start_at() == datetime(
        2026,
        7,
        29,
        14,
        0,
        tzinfo=timezone.utc,
    )


def test_report_contains_exact_pending_cio_transaction(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_PAPER_TRADING_START_AT", raising=False)
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    report = build_pending_transaction_report(
        construction=_construction(),
        briefing=_briefing(),
        generated_at=datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc),
    )

    assert report["report_state"] == "pending_transactions"
    assert report["launch_state"] == "scheduled"
    assert report["execution_state"] == "scheduled"
    assert report["paper_trading_start_at"] == "2026-07-29T13:30:00+00:00"
    assert "6:30 AM PDT" in report["paper_trading_start_label"]
    assert report["transaction_count"] == 1
    assert isinstance(report["report_fingerprint"], str)
    assert len(report["report_fingerprint"]) == 64
    assert report["transactions"] == [
        {
            "sequence": 1,
            "symbol": "VTI",
            "side": "buy",
            "from_weight": 0.0,
            "to_weight": 0.10,
            "trade_weight": 0.10,
            "estimated_cost_return": 0.0001,
            "reason": "Highest governed risk-adjusted opportunity after costs",
            "funding_for": [],
            "status": "pending_execution",
        }
    ]
    assert report["real_money_authorized"] is False

    json_path, markdown_path = write_pending_transaction_report(report)
    persisted = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert persisted["decision_identifier"] == "decision:launch-vti"
    assert load_pending_transaction_report() == persisted
    assert "CIO Pending Transaction Recommendations" in markdown
    assert "| 1 | VTI | BUY |" in markdown
    assert pending_transaction_report_markdown(report) == markdown
    history = pending_transaction_report_history()
    assert len(history) == 1
    assert history[0]["report_fingerprint"] == report["report_fingerprint"]


def test_report_history_deduplicates_same_state_and_records_state_change(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    first = build_pending_transaction_report(
        construction=_construction(),
        briefing=_briefing(),
        generated_at=datetime(2026, 7, 29, 13, 31, tzinfo=timezone.utc),
        execution_state="held",
    )
    same_state_later = build_pending_transaction_report(
        construction=_construction(),
        briefing=_briefing(),
        generated_at=datetime(2026, 7, 29, 13, 32, tzinfo=timezone.utc),
        execution_state="held",
    )
    completed = build_pending_transaction_report(
        construction=_construction(),
        briefing=_briefing(),
        generated_at=datetime(2026, 7, 29, 13, 33, tzinfo=timezone.utc),
        execution_state="completed",
    )

    write_pending_transaction_report(first)
    write_pending_transaction_report(same_state_later)
    assert len(pending_transaction_report_history()) == 1
    write_pending_transaction_report(completed)
    history = pending_transaction_report_history()
    assert len(history) == 2
    assert history[0]["execution_state"] == "completed"
    assert history[0]["transactions"][0]["status"] == "executed"


def test_resolver_preserves_operator_execution_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    completed = build_pending_transaction_report(
        construction=_construction(),
        briefing=_briefing(),
        generated_at=datetime(2026, 7, 29, 13, 33, tzinfo=timezone.utc),
        execution_state="completed",
    )
    write_pending_transaction_report(completed)

    resolved = resolve_pending_transaction_report(
        construction=_construction(),
        briefing=_briefing(),
        generated_at=datetime(2026, 7, 29, 13, 34, tzinfo=timezone.utc),
    )

    assert resolved["execution_state"] == "completed"
    assert resolved["transactions"][0]["status"] == "executed"
    assert resolved["report_fingerprint"] == completed["report_fingerprint"]


def test_report_truthfully_records_no_transaction() -> None:
    construction = {
        **_construction(),
        "trades": [],
        "target_weights": [],
        "target_cash_weight": 1.0,
        "turnover": 0.0,
    }
    report = build_pending_transaction_report(
        construction=construction,
        briefing=_briefing(),
        generated_at=datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc),
    )

    assert report["report_state"] == "no_transaction_recommended"
    assert report["transaction_count"] == 0
    assert report["transactions"] == []
