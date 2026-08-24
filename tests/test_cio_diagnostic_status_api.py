from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from api.routes import cio_diagnostic
from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    finish_manual_cio_diagnostic,
    request_manual_cio_diagnostic,
)


_DECISION_AS_OF = datetime(2026, 8, 15, 5, 0, tzinfo=timezone.utc)


def _completed_diagnostic(
    tmp_path: Path,
    *,
    release: str,
    cycle_key: str,
) -> tuple[dict[str, str], SimpleNamespace]:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": release,
    }
    request, created = request_manual_cio_diagnostic(
        requested_by=f"render-release:{release}",
        values=values,
    )
    assert created
    claimed = claim_manual_cio_diagnostic(values=values)
    assert claimed is not None
    finished = finish_manual_cio_diagnostic(
        claimed,
        succeeded=True,
        cycle_key=cycle_key,
        snapshot_identifier="snapshot:test",
        detail="CIO diagnostic completed; analytical_certification=complete; paper_execution=no_action.",
        values=values,
    )
    assert finished.request_id == request.request_id
    settings = SimpleNamespace(portfolio_database=tmp_path / "portfolio.db")
    return values, settings


def _write_context(
    tmp_path: Path,
    *,
    cycle_key: str,
    scope_state: str = "capability_scoped",
) -> None:
    payload = {
        "cycle_key": cycle_key,
        "decision_as_of": _DECISION_AS_OF.isoformat(),
        "comprehensive_discovery_required": True,
        "comprehensive_discovery_scope_state": scope_state,
        "comprehensive_discovery_limitations": [],
        "instrument_count": 24,
        "candidate_count": 9,
        "exclusion_count": 15,
        "qualified_candidate_count": 4,
        "paper_only": True,
        "real_money_authorized": False,
    }
    (tmp_path / "production-context-publication-state.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _analytical_certificate() -> dict[str, object]:
    return {
        "all_market_runtime_certified": True,
        "all_market_certification_integrity_valid": True,
        "all_market_certification_release_matches": True,
        "all_market_certification_id": "legacy-cert",
        "all_market_certification_epoch": "2026-08-15T04:55:00+00:00",
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
                "asset_class": asset_class,
                "scheduled": True,
                "schedule_reason": None,
                "catalog_count": catalog,
                "deep_analyzed_count": deep,
                "selected_count": selected,
                "represented": True,
                "terminal_accounting_complete": True,
            }
            for asset_class, catalog, deep, selected in (
                ("commodity", 6, 6, 3),
                ("crypto", 5, 5, 2),
                ("fixed_income", 7, 7, 3),
                ("fx", 6, 6, 2),
            )
        ],
        "certification_v2_cutoff": _DECISION_AS_OF.isoformat(),
    }


def test_completed_current_release_reports_all_market_evaluation_complete(
    tmp_path: Path,
    monkeypatch,
) -> None:
    values, settings = _completed_diagnostic(
        tmp_path,
        release="release-123",
        cycle_key="cycle:complete",
    )
    _write_context(tmp_path, cycle_key="cycle:complete")
    monkeypatch.setattr(
        cio_diagnostic,
        "public_all_market_certification_readonly",
        lambda _values: _analytical_certificate(),
    )
    monkeypatch.setattr(
        cio_diagnostic,
        "_certification_context_matches",
        lambda *_args, **_kwargs: (True, True),
    )

    payload = cio_diagnostic.build_cio_diagnostic_audit(settings=settings, values=values)

    assert payload["schema_version"] == "public-cio-diagnostic-audit.v3-independent-certification"
    assert payload["ready"] is True
    assert payload["all_market_evaluation_complete"] is True
    assert payload["all_market_construction_certified"] is True
    assert payload["all_market_no_action_certified"] is True
    assert payload["all_market_operational_certified"] is True
    assert payload["context_cycle_matches"] is True
    assert payload["terminal_screening_complete"] is True
    assert payload["scheduled_market_coverage_complete"] is True
    assert payload["production_context_discovery_scope_state"] == "capability_scoped"
    assert payload["comprehensive_discovery_scope_state"] == "complete"
    assert payload["instrument_count"] == 24
    assert payload["candidate_count"] == 9
    assert payload["exclusion_count"] == 15
    assert payload["qualified_candidate_count"] == 4
    assert {item["asset_class"] for item in payload["market_lanes"]} == {
        "commodity", "crypto", "fixed_income", "fx"
    }
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False
    assert "holdings" not in payload
    assert "target_weights" not in payload
    assert "candidate_symbols" not in payload


def test_mismatched_context_cycle_fails_closed(tmp_path: Path) -> None:
    values, settings = _completed_diagnostic(
        tmp_path,
        release="release-123",
        cycle_key="cycle:diagnostic",
    )
    _write_context(tmp_path, cycle_key="cycle:other")

    payload = cio_diagnostic.build_cio_diagnostic_audit(settings=settings, values=values)

    assert payload["ready"] is False
    assert payload["context_cycle_matches"] is False
    assert payload["all_market_evaluation_complete"] is False


def test_incomplete_comprehensive_scope_fails_closed(tmp_path: Path) -> None:
    values, settings = _completed_diagnostic(
        tmp_path,
        release="release-123",
        cycle_key="cycle:degraded",
    )
    _write_context(
        tmp_path,
        cycle_key="cycle:degraded",
        scope_state="optional_unavailable",
    )

    payload = cio_diagnostic.build_cio_diagnostic_audit(settings=settings, values=values)

    assert payload["ready"] is False
    assert payload["comprehensive_discovery_complete"] is False
    assert payload["all_market_evaluation_complete"] is False


def test_missing_diagnostic_is_truthfully_not_recorded(tmp_path: Path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-123",
    }
    settings = SimpleNamespace(portfolio_database=tmp_path / "portfolio.db")

    payload = cio_diagnostic.build_cio_diagnostic_audit(settings=settings, values=values)

    assert payload["schema_version"] == "public-cio-diagnostic-audit.v3-independent-certification"
    assert payload["credential_safe"] is True
    assert payload["ready"] is False
    assert payload["state"] == "not_recorded"
    assert payload["detail"] == "no release-triggered CIO diagnostic has been recorded"
    assert payload["active_release"] == "release-123"
    assert payload["release_matches"] is False
    assert payload["all_market_evaluation_complete"] is False
    assert payload["all_market_certification_context_matches"] is False
    assert payload["all_market_certification_v2_context_matches"] is False
    assert payload["market_lanes"] == []
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False
