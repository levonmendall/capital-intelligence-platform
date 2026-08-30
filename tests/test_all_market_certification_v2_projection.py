from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

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
    scheduled_lanes: list[str],
) -> str:
    body: dict[str, object] = {
        "schema_version": "all-market-certification-input.v2",
        "release": release,
        "evidence_as_of": evidence_as_of.isoformat(),
        "scheduled_lanes": scheduled_lanes,
        "global_discovery_snapshot_id": "global-1",
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


def _snapshot(evidence_as_of: datetime, *, observed_at: datetime | None = None):
    features = SimpleNamespace(observed_at=observed_at or evidence_as_of)
    selected = (SimpleNamespace(features=features),)
    lane = SimpleNamespace(
        asset_class=SimpleNamespace(value="us_equity"),
        scheduled=True,
        catalog_count=2,
        deep_analyzed_count=2,
        selected=selected,
        exclusions=(("EXCLUDED", "screening_rejection"),),
    )
    result = SimpleNamespace(
        lanes=(lane,),
        manifest_fingerprint="manifest-1",
    )
    return SimpleNamespace(
        snapshot_id="global-1",
        evidence_as_of=evidence_as_of,
        result=result,
    )


def test_v2_lane_projection_reconstructs_terminal_all_market_proof(
    tmp_path: Path, monkeypatch
) -> None:
    release = "release-1"
    evidence_as_of = datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc)
    certification_id = _write_input(
        tmp_path,
        release=release,
        evidence_as_of=evidence_as_of,
        scheduled_lanes=["us_equity"],
    )
    monkeypatch.setattr(
        readonly,
        "load_qualified_comprehensive_discovery_snapshot",
        lambda *, evidence_as_of, values: _snapshot(evidence_as_of),
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
    assert result["all_market_lane_certification_source"] == "certification_v2_global_snapshot"
    lane = result["all_market_certified_lanes"][0]
    assert lane["catalog_count"] == 2
    assert lane["terminal_count"] == 2
    assert lane["terminal_accounting_complete"] is True
    assert lane["point_in_time_valid"] is True


def test_v2_lane_projection_fails_closed_on_future_lane_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    release = "release-1"
    evidence_as_of = datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc)
    certification_id = _write_input(
        tmp_path,
        release=release,
        evidence_as_of=evidence_as_of,
        scheduled_lanes=["us_equity"],
    )
    monkeypatch.setattr(
        readonly,
        "load_qualified_comprehensive_discovery_snapshot",
        lambda *, evidence_as_of, values: _snapshot(
            evidence_as_of,
            observed_at=evidence_as_of + timedelta(seconds=1),
        ),
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
