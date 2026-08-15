from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import api.routes.cio_diagnostic as audit


def _certificate(
    *,
    cutoff: datetime,
    evidence_as_of: datetime,
    complete: bool = True,
) -> dict[str, object]:
    return {
        "all_market_runtime_certified": True,
        "all_market_certification_integrity_valid": True,
        "all_market_certification_release_matches": True,
        "all_market_certification_id": "legacy-cert",
        "all_market_certification_epoch": evidence_as_of.isoformat(),
        "all_market_certification_aggregate_sha256": "a" * 64,
        "all_market_certification_discovery_manifest_fingerprint": "legacy-discovery",
        "all_market_certification_v2_available": True,
        "all_market_certification_v2_input_integrity_valid": True,
        "all_market_certification_v2_state_integrity_valid": True,
        "all_market_certification_v2_release_matches": True,
        "all_market_certification_v2_id": "v2-cert",
        "all_market_evidence_generation_id": "generation",
        "all_market_point_in_time_snapshot_id": "pit",
        "all_market_global_discovery_snapshot_id": "global",
        "all_market_us_equity_discovery_snapshot_id": "equity",
        "all_market_paper_evidence_snapshot_id": "paper",
        "all_market_policy_compatibility_hash": "b" * 64,
        "all_market_certification_v2_state": (
            "CONSTRUCTION_COMPLETE" if complete else "COMMITTEE_COMPLETE"
        ),
        "all_market_evidence_certified": True,
        "all_market_screening_certified": True,
        "all_market_committee_certified": True,
        "all_market_cio_certified": complete,
        "all_market_construction_certified": complete,
        "all_market_paper_implementation_certified": False,
        "all_market_no_action_certified": False,
        "all_market_operational_certified": False,
        "certification_v2_enabled": True,
        "certification_v2_id": "v2-cert",
        "certification_v2_state": (
            "CONSTRUCTION_COMPLETE" if complete else "COMMITTEE_COMPLETE"
        ),
        "certification_v2_cutoff": cutoff.isoformat(),
        "certification_v2_evidence_generation_id": "generation",
        "certification_v2_snapshot_id": "pit",
        "certification_v2_global_discovery_snapshot_id": "global",
        "certification_v2_us_equity_discovery_snapshot_id": "equity",
        "certification_v2_paper_evidence_snapshot_id": "paper",
        "certification_v2_policy_compatibility_hash": "b" * 64,
        "certification_v2_blocker": "state:CONSTRUCTION_COMPLETE",
    }


def _write_v2_input(
    tmp_path: Path,
    *,
    cutoff: datetime,
    evidence_as_of: datetime,
) -> None:
    path = (
        tmp_path
        / "all-market-certification-v2"
        / "inputs"
        / "release-test"
        / "v2-cert.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "all-market-certification-input.v2",
                "record_id": "v2-cert",
                "release": "release-test",
                "evidence_generation_id": "generation",
                "evidence_as_of": evidence_as_of.isoformat(),
                "snapshot_id": "pit",
                "snapshot_cutoff": cutoff.isoformat(),
                "global_discovery_snapshot_id": "global",
                "us_equity_discovery_snapshot_id": "equity",
                "paper_evidence_snapshot_id": "paper",
                "policy_compatibility_hash": "b" * 64,
                "consumer_provider_refresh_permitted": False,
                "paper_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _diagnostic(*, cutoff: datetime):
    return SimpleNamespace(
        requested_by="render-release:release-test",
        state="completed",
        request_id="request-test",
        requested_at=cutoff,
        started_at=cutoff,
        completed_at=cutoff,
        progress_stage="paper_implementation_boundary",
        progress_metrics=(),
        progress_recorded_at=cutoff,
        cycle_key="canonical-cio:America/Los_Angeles:2026-08-14",
        snapshot_identifier="cio-snapshot-test",
        detail="analytical certification complete; paper implementation pending",
    )


def _context(*, cutoff: datetime) -> dict[str, object]:
    return {
        "cycle_key": "canonical-cio:America/Los_Angeles:2026-08-14",
        "decision_as_of": cutoff.isoformat(),
        "comprehensive_discovery_required": True,
        "comprehensive_discovery_scope_state": "complete",
        "comprehensive_discovery_limitations": [],
        "instrument_count": 10,
        "candidate_count": 3,
        "exclusion_count": 7,
        "qualified_candidate_count": 2,
        "comprehensive_discovery_lane_counts": {
            "crypto": {
                "scheduled": True,
                "catalog": 5,
                "deep": 5,
                "selected": 2,
            },
            "fixed_income": {
                "scheduled": True,
                "catalog": 5,
                "deep": 5,
                "selected": 1,
            },
        },
    }


def test_public_diagnostic_accepts_fresh_reused_evidence_at_later_cio_cutoff(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cutoff = datetime(2026, 8, 15, 4, 30, tzinfo=timezone.utc)
    evidence_as_of = cutoff - timedelta(minutes=5)
    _write_v2_input(tmp_path, cutoff=cutoff, evidence_as_of=evidence_as_of)
    settings = SimpleNamespace(portfolio_database=tmp_path / "portfolio.db")
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "RENDER_GIT_COMMIT": "release-test",
        "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true",
    }
    monkeypatch.setattr(
        audit,
        "latest_manual_cio_diagnostic",
        lambda **_: _diagnostic(cutoff=cutoff),
    )
    monkeypatch.setattr(audit, "_load_json", lambda _path: _context(cutoff=cutoff))
    monkeypatch.setattr(audit, "_latest_context_attempt", lambda _settings: {})
    monkeypatch.setattr(
        audit,
        "public_all_market_certification",
        lambda _values: _certificate(
            cutoff=cutoff,
            evidence_as_of=evidence_as_of,
        ),
    )

    payload = audit.build_cio_diagnostic_audit(settings=settings, values=values)

    assert payload["schema_version"] == "public-cio-diagnostic-audit.v2-end-to-end"
    assert payload["credential_safe"] is True
    assert payload["all_market_certification_context_matches"] is True
    assert payload["all_market_certification_v2_context_matches"] is True
    assert payload["all_market_construction_certified"] is True
    assert payload["all_market_operational_certified"] is False
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False
    assert payload["ready"] is True
    assert payload["all_market_evaluation_complete"] is True


def test_public_diagnostic_fails_closed_when_v2_stops_before_cio_construction(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cutoff = datetime(2026, 8, 15, 4, 45, tzinfo=timezone.utc)
    evidence_as_of = cutoff - timedelta(minutes=5)
    _write_v2_input(tmp_path, cutoff=cutoff, evidence_as_of=evidence_as_of)
    settings = SimpleNamespace(portfolio_database=tmp_path / "portfolio.db")
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "RENDER_GIT_COMMIT": "release-test",
        "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true",
    }
    monkeypatch.setattr(
        audit,
        "latest_manual_cio_diagnostic",
        lambda **_: _diagnostic(cutoff=cutoff),
    )
    monkeypatch.setattr(audit, "_load_json", lambda _path: _context(cutoff=cutoff))
    monkeypatch.setattr(audit, "_latest_context_attempt", lambda _settings: {})
    monkeypatch.setattr(
        audit,
        "public_all_market_certification",
        lambda _values: _certificate(
            cutoff=cutoff,
            evidence_as_of=evidence_as_of,
            complete=False,
        ),
    )

    payload = audit.build_cio_diagnostic_audit(settings=settings, values=values)

    assert payload["all_market_committee_certified"] is True
    assert payload["all_market_cio_certified"] is False
    assert payload["all_market_construction_certified"] is False
    assert payload["ready"] is False
    assert payload["all_market_evaluation_complete"] is False
