from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import operations.all_market_certification_readonly as readonly


def _v2_flags(certification_id: str) -> dict[str, object]:
    return {
        "all_market_certification_v2_available": True,
        "all_market_certification_v2_input_integrity_valid": True,
        "all_market_certification_v2_state_integrity_valid": True,
        "all_market_certification_v2_release_matches": True,
        "all_market_certification_v2_id": certification_id,
        "all_market_global_discovery_snapshot_id": "global-1",
        "all_market_evidence_certified": True,
        "all_market_screening_certified": True,
    }


def _write_input(
    tmp_path: Path,
    *,
    release: str,
    evidence_as_of: datetime,
    point_in_time_valid: bool = True,
) -> str:
    lane = {
        "asset_class": "us_equity",
        "scheduled": True,
        "catalog_count": 2,
        "deep_analyzed_count": 2,
        "selected_count": 1,
        "excluded_count": 1,
        "terminal_count": 2,
        "terminal_accounting_complete": True,
        "point_in_time_valid": point_in_time_valid,
        "freshness_valid": point_in_time_valid,
    }
    body: dict[str, object] = {
        "schema_version": "all-market-certification-input.v2",
        "release": release,
        "evidence_as_of": evidence_as_of.isoformat(),
        "scheduled_lanes": ["us_equity"],
        "global_discovery_snapshot_id": "global-1",
        "global_discovery_lane_summary": [lane],
    }
    certification_id = readonly._digest(body)
    path = (
        tmp_path
        / "all-market-certification-v2"
        / "inputs"
        / release
        / f"{certification_id}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({**body, "record_id": certification_id}),
        encoding="utf-8",
    )
    return certification_id


def test_v2_lane_projection_reconstructs_terminal_all_market_proof(tmp_path: Path) -> None:
    release = "release-1"
    evidence_as_of = datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc)
    certification_id = _write_input(
        tmp_path,
        release=release,
        evidence_as_of=evidence_as_of,
    )

    result = readonly._v2_lane_audit(
        {
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
            "CAPITAL_INTELLIGENCE_RELEASE": release,
        },
        _v2_flags(certification_id),
    )

    assert result["all_market_runtime_certified"] is True
    assert result["all_market_certification_integrity_valid"] is True
    assert result["all_market_comprehensive_discovery_complete"] is True
    assert result["all_market_scheduled_market_coverage_complete"] is True
    assert result["all_market_terminal_screening_complete"] is True
    assert result["all_market_certification_epoch"] == evidence_as_of.isoformat()
    assert result["all_market_lane_certification_source"] == "certification_v2_input_summary"
    lane = result["all_market_certified_lanes"][0]
    assert lane["catalog_count"] == 2
    assert lane["terminal_count"] == 2
    assert lane["terminal_accounting_complete"] is True
    assert lane["point_in_time_valid"] is True


def test_v2_lane_projection_fails_closed_on_invalid_point_in_time_proof(
    tmp_path: Path,
) -> None:
    release = "release-1"
    evidence_as_of = datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc)
    certification_id = _write_input(
        tmp_path,
        release=release,
        evidence_as_of=evidence_as_of,
        point_in_time_valid=False,
    )

    result = readonly._v2_lane_audit(
        {
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
            "CAPITAL_INTELLIGENCE_RELEASE": release,
        },
        _v2_flags(certification_id),
    )

    assert result["all_market_runtime_certified"] is False
    assert result["all_market_comprehensive_discovery_complete"] is False
    assert result["all_market_scheduled_market_coverage_complete"] is False
    assert result["all_market_terminal_screening_complete"] is False


def test_current_release_v2_ledger_never_falls_back_to_stale_legacy_proof(
    tmp_path: Path, monkeypatch
) -> None:
    release = "release-1"
    ledger = (
        tmp_path
        / "all-market-certification-v2"
        / "ledger"
        / release
        / "latest-input.json"
    )
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("corrupt\n", encoding="utf-8")

    monkeypatch.setattr(
        readonly,
        "public_all_market_certification",
        lambda values: {
            "all_market_runtime_certified": True,
            "all_market_certification_integrity_valid": True,
        },
    )
    monkeypatch.setattr(
        readonly,
        "_readonly_v2",
        lambda values: {"all_market_certification_v2_available": False},
    )
    monkeypatch.setattr(
        readonly,
        "_v2_lane_audit",
        lambda values, v2: readonly._unavailable_v2_lane_audit(),
    )

    def legacy_must_not_run(values):
        raise AssertionError("authoritative v2 lineage must not fall back to legacy")

    monkeypatch.setattr(readonly, "_legacy_lane_audit", legacy_must_not_run)
    result = readonly.public_all_market_certification_readonly(
        {
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
            "CAPITAL_INTELLIGENCE_RELEASE": release,
        }
    )

    assert result["all_market_runtime_certified"] is False
    assert result["all_market_certification_integrity_valid"] is False
    assert result["all_market_comprehensive_discovery_complete"] is False


def test_legacy_lane_proof_remains_fallback_before_v2_ledger_exists(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(readonly, "public_all_market_certification", lambda values: {})
    monkeypatch.setattr(readonly, "_readonly_v2", lambda values: {})
    monkeypatch.setattr(
        readonly,
        "_legacy_lane_audit",
        lambda values: {
            "all_market_comprehensive_discovery_complete": True,
            "all_market_lane_certification_source": "legacy_compositional_certificate",
        },
    )

    result = readonly.public_all_market_certification_readonly(
        {
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
            "CAPITAL_INTELLIGENCE_RELEASE": "release-1",
        }
    )

    assert result["all_market_comprehensive_discovery_complete"] is True
    assert result["all_market_lane_certification_source"] == "legacy_compositional_certificate"
