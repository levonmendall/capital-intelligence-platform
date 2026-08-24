from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from api.routes import cio_diagnostic
from operations.manual_cio_diagnostic import ManualCIODiagnosticRequest


UTC = timezone.utc
_DECISION_AS_OF = datetime(2026, 8, 5, 20, 2, tzinfo=UTC)


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
        completed_at=_DECISION_AS_OF,
        cycle_key=cycle_key,
        snapshot_identifier=None if cycle_key is None else "snapshot-123",
        detail=detail,
    )


def _stale_context() -> dict[str, object]:
    return {
        "cycle_key": "older-cycle",
        "decision_as_of": _DECISION_AS_OF.isoformat(),
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


def _certified_analytical_lineage() -> dict[str, object]:
    return {
        "all_market_runtime_certified": True,
        "all_market_certification_integrity_valid": True,
        "all_market_certification_release_matches": True,
        "all_market_certification_id": "legacy-cert",
        "all_market_certification_epoch": "2026-08-05T19:58:00+00:00",
        "all_market_certification_aggregate_sha256": "a" * 64,
        "all_market_certification_discovery_manifest_fingerprint": "global-manifest",
        "all_market_certification_v2_available": True,
        "all_market_certification_v2_input_integrity_valid": True,
        "all_market_certification_v2_state_integrity_valid": True,
        "all_market_certification_v2_release_matches": True,
        "all_market_certification_v2_id": "v2-cert",
        "all_market_evidence_generation_id": "generation-1",
        "all_market_point_in_time_snapshot_id": "pit-1",
        "all_market_global_discovery_snapshot_id": "global-1",
        "all_market_us_equity_discovery_snapshot_id": "equity-1",
        "all_market_paper_evidence_snapshot_id": "paper-1",
        "all_market_policy_compatibility_hash": "b" * 64,
        "all_market_certification_v2_state": "CERTIFIED",
        "all_market_evidence_certified": True,
        "all_market_screening_certified": True,
        "all_market_committee_certified": True,
        "all_market_cio_certified": True,
        "all_market_construction_certified": True,
        "all_market_paper_implementation_certified": False,
        "all_market_no_action_certified": True,
        "all_market_operational_certified": True,
        "all_market_comprehensive_discovery_complete": True,
        "all_market_scheduled_market_coverage_complete": True,
        "all_market_terminal_screening_complete": True,
        "all_market_certified_lanes": [
            {
                "asset_class": "global_equity",
                "scheduled": True,
                "schedule_reason": None,
                "catalog_count": 3,
                "deep_analyzed_count": 2,
                "selected_count": 1,
                "represented": True,
                "terminal_accounting_complete": True,
            }
        ],
        "certification_v2_cutoff": _DECISION_AS_OF.isoformat(),
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


def test_matching_diagnostic_cycle_requires_certified_analytical_lineage(
    monkeypatch,
) -> None:
    diagnostic = _diagnostic(
        state="completed",
        cycle_key="current-cycle",
        detail="The governed paper-only CIO diagnostic completed.",
    )
    context = {
        "cycle_key": "current-cycle",
        "decision_as_of": _DECISION_AS_OF.isoformat(),
        "comprehensive_discovery_required": True,
        "comprehensive_discovery_scope_state": "capability_scoped",
        "comprehensive_discovery_limitations": ["Current-cycle limitation."],
        "instrument_count": 3,
        "candidate_count": 1,
        "exclusion_count": 2,
        "qualified_candidate_count": 1,
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
    monkeypatch.setattr(
        cio_diagnostic,
        "public_all_market_certification_readonly",
        lambda _values: _certified_analytical_lineage(),
    )
    # Exact two-clock behavior is separately covered by the certification integration
    # tests. This cycle-lineage test supplies an already-proven certification binding.
    monkeypatch.setattr(
        cio_diagnostic,
        "_certification_context_matches",
        lambda *_args, **_kwargs: (True, True),
    )

    audit = cio_diagnostic.build_cio_diagnostic_audit(
        settings=SimpleNamespace(),
        values={"CAPITAL_INTELLIGENCE_RELEASE": "release-123"},
    )

    assert audit["ready"] is True
    assert audit["context_cycle_matches"] is True
    assert audit["all_market_construction_certified"] is True
    assert audit["all_market_no_action_certified"] is True
    assert audit["all_market_operational_certified"] is True
    assert audit["production_context_discovery_scope_state"] == "capability_scoped"
    assert audit["comprehensive_discovery_scope_state"] == "complete"
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
            "terminal_accounting_complete": True,
        }
    ]
