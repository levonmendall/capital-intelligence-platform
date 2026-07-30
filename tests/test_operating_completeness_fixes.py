from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cio_pending_transactions import build_pending_transaction_report
from historical_replay_ui import historical_macro_certification_detail


def _briefing(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "briefing:canonical-cio:2026-07-30",
        "cycle_identifier": "canonical-cio:America/Los_Angeles:2026-07-30",
        "as_of": "2026-07-30T12:01:00+00:00",
        "status": "no_superior_opportunity",
        "portfolio_decision": "No portfolio action is required.",
    }
    payload.update(overrides)
    return payload


def test_no_action_report_retains_canonical_briefing_identifier() -> None:
    report = build_pending_transaction_report(
        construction=None,
        briefing=_briefing(),
        generated_at=datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc),
        execution_state="idle",
    )

    assert report["decision_identifier"] == "briefing:canonical-cio:2026-07-30"
    assert report["report_state"] == "no_transaction_recommended"
    assert report["summary"] == "No portfolio action is required."


def test_explicit_decision_identifier_remains_authoritative() -> None:
    report = build_pending_transaction_report(
        construction=None,
        briefing=_briefing(decision_identifier="decision:explicit"),
        generated_at=datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc),
        execution_state="idle",
    )

    assert report["decision_identifier"] == "decision:explicit"


def test_historical_macro_message_distinguishes_series_presence_from_cutoff_coverage() -> None:
    detail = historical_macro_certification_detail(
        {
            "certification_ready": False,
            "present_macro_dataset_count": 3,
            "required_macro_dataset_count": 3,
            "macro_incomplete_cutoffs": 117,
            "total_cutoffs": 120,
            "missing_macro_datasets": [],
        }
    )

    assert "All 3 required macro series are present" in detail
    assert "117 of 120 decision cutoffs" in detail
    assert "excluded from live calibration" in detail


def test_operating_surface_source_uses_live_environment_fallback_and_wrapping() -> None:
    app_source = Path("app_impl.py").read_text(encoding="utf-8")
    style_source = Path("premium_ui.py").read_text(encoding="utf-8")

    assert "Live environment evidence is available" in app_source
    assert "Not separately classified" in app_source
    assert '"Decision ID": _briefing_identifier(item)' in app_source
    assert "white-space:normal;overflow-wrap:anywhere" in style_source
    assert '[data-testid="stMetricValue"]' in style_source
