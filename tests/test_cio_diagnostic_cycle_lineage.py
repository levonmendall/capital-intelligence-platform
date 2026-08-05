from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from api.routes import cio_diagnostic
from operations.manual_cio_diagnostic import ManualCIODiagnosticRequest


UTC = timezone.utc


def _diagnostic(
    *,
    state: str,
    cycle_key: str | None,
    detail: str,
) -> ManualCIODiagnosticRequest:
    return ManualCIODiagnosticRequest(
        request_id="request-123",
        requested_at=datetime(2026, 8, 5, 20, 0, tzinfo=UTC),
        requested_by="render-release:release-123",
        state=state,
        started_at=datetime(2026, 8, 5, 20, 1, tzinfo=UTC),
        completed_at=datetime(2026, 8, 5, 20, 2, tzinfo=UTC),
        cycle_key=cycle_key,
        snapshot_identifier=None if cycle_key is None else "snapshot-123",
        detail=detail,
    )


def _stale_context() -> dict[str, object]:
    return {
        "cycle_key": "older-cycle",
        "comprehensive_discovery_required": True,
        "comprehensive_discovery_scope_state": "complete",
        "comprehensive_discovery_limitations": [
            "EODHD directory BOND returned HTTP 404 in an older cycle."
        ],
        "instrument_count": 100,
        "candidate_count": 20,
        "exclusion_count": 80,
        "qualified_candidate_count": 10,
        "comprehensive_discovery_lane_counts": {
            "fixed_income": {
                "scheduled": True,
                "catalog": 100,
                "deep": 20,
                "selected": 10,
            }
        },
    }


def test_failed_diagnostic_does_not_reuse_context_from_an_older_cycle(
    monkeypatch,
) -> None:
    diagnostic = _diagnostic(
        state="failed",
        cycle_key=None,
        detail=(
            "EODHD active symbol directory SA returned HTTP 402; "
            "Twelve Data stock catalog returned HTTP 429."
        ),
    )
    monkeypatch.setattr(
        cio_diagnostic,
        "latest_manual_cio_diagnostic",
        lambda **_: diagnostic,
    )
    monkeypatch.setattr(
        cio_diagnostic,
        "_state_path",
        lambda _: Path("unused-context.json"),
    )
    monkeypatch.setattr(
        cio_diagnostic,
        "_load_json",
        lambda _: _stale_context(),
    )

    audit = cio_diagnostic.build_cio_diagnostic_audit(
        settings=SimpleNamespace(),
        values={"CAPITAL_INTELLIGENCE_RELEASE": "release-123"},
    )

    assert audit["ready"] is False
    assert audit["state"] == "failed"
    assert audit["context_cycle_matches"] is False
    assert audit["detail"] == diagnostic.detail
    assert "SA" in str(audit["detail"])
    assert "429" in str(audit["detail"])
    assert "BOND" not in str(audit)
    assert audit["comprehensive_discovery_required"] is False
    assert audit["comprehensive_discovery_scope_state"] == "missing"
    assert audit["comprehensive_discovery_complete"] is False
    assert audit["comprehensive_discovery_limitations"] == []
    assert audit["instrument_count"] == 0
    assert audit["candidate_count"] == 0
    assert audit["exclusion_count"] == 0
    assert audit["qualified_candidate_count"] == 0
    assert audit["terminal_screening_complete"] is False
    assert audit["scheduled_market_coverage_complete"] is False
    assert audit["all_market_evaluation_complete"] is False
    assert audit["market_lanes"] == []
    assert audit["paper_only"] is True
    assert audit["real_money_authorized"] is False


def test_matching_diagnostic_cycle_can_publish_its_own_aggregate_evidence(
    monkeypatch,
) -> None:
    diagnostic = _diagnostic(
        state="completed",
        cycle_key="current-cycle",
        detail="The governed paper-only CIO diagnostic completed.",
    )
    context = {
        "cycle_key": "current-cycle",
        "comprehensive_discovery_required": True,
        "comprehensive_discovery_scope_state": "complete",
        "comprehensive_discovery_limitations": ["Current-cycle limitation."],
        "instrument_count": 3,
        "candidate_count": 1,
        "exclusion_count": 2,
        "qualified_candidate_count": 1,
        "comprehensive_discovery_lane_counts": {
            "global_equity": {
                "scheduled": True,
                "catalog": 3,
                "deep": 2,
                "selected": 1,
            }
        },
    }
    monkeypatch.setattr(
        cio_diagnostic,
        "latest_manual_cio_diagnostic",
        lambda **_: diagnostic,
    )
    monkeypatch.setattr(
        cio_diagnostic,
        "_state_path",
        lambda _: Path("unused-context.json"),
    )
    monkeypatch.setattr(cio_diagnostic, "_load_json", lambda _: context)

    audit = cio_diagnostic.build_cio_diagnostic_audit(
        settings=SimpleNamespace(),
        values={"CAPITAL_INTELLIGENCE_RELEASE": "release-123"},
    )

    assert audit["ready"] is True
    assert audit["context_cycle_matches"] is True
    assert audit["comprehensive_discovery_limitations"] == [
        "Current-cycle limitation."
    ]
    assert audit["instrument_count"] == 3
    assert audit["terminal_screening_complete"] is True
    assert audit["scheduled_market_coverage_complete"] is True
    assert audit["all_market_evaluation_complete"] is True
    assert audit["market_lanes"] == [
        {
            "asset_class": "global_equity",
            "scheduled": True,
            "schedule_reason": None,
            "catalog_count": 3,
            "deep_analyzed_count": 2,
            "selected_count": 1,
            "represented": True,
        }
    ]
