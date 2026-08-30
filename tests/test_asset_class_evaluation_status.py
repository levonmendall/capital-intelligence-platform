from __future__ import annotations

import hashlib
import json
from pathlib import Path

from operations.asset_class_evaluation_status import load_asset_class_evaluation_status


_GOVERNED_CLASS_COUNT = 13


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _values(tmp_path: Path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "RENDER_GIT_COMMIT": "release-test",
    }


def _write_dag_attempt(tmp_path: Path) -> str:
    epoch = "2026-08-19T20:15:00+00:00"
    body = {
        "schema_version": "persistent-certification-manifest.v1",
        "release_sha": "release-test",
        "decision_epoch": epoch,
        "policy_version": "test-policy",
        "required_nodes": [
            "deep-market-evidence:us_equity",
            "deep-market-evidence:fixed_income",
        ],
        "completed_nodes": ["deep-market-evidence:us_equity"],
        "reused_nodes": [],
        "failed_nodes": ["deep-market-evidence:fixed_income"],
        "node_results": {
            "deep-market-evidence:us_equity": {
                "status": "qualified",
                "reused": False,
                "evidence_complete_count": 40,
                "failure_type": None,
                "retry_after": None,
            },
            "deep-market-evidence:fixed_income": {
                "status": "failed",
                "reused": False,
                "evidence_complete_count": 0,
                "failure_type": "ProviderEvidenceError",
                "retry_after": None,
            },
        },
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    _write(
        tmp_path
        / "certification-dag"
        / "persistent-certification-dag.v1"
        / "release-test"
        / "20260819T201500000000Z"
        / "latest.json",
        {"body": body, "sha256": _digest(body)},
    )
    return epoch


def _write_lane_artifact(
    root: Path,
    *,
    certification_id: str,
    epoch: str,
    lane: str,
    catalog_count: int,
    deep_analyzed_count: int,
    selected_count: int,
) -> str:
    excluded_count = catalog_count - selected_count
    body = {
        "schema_version": "all-market-lane-certification.v1",
        "certification_id": certification_id,
        "release_sha": "release-test",
        "lane": lane,
        "decision_epoch": epoch,
        "evidence_effective_at": epoch,
        "policy_version": "test-policy",
        "catalog_count": catalog_count,
        "deep_analyzed_count": deep_analyzed_count,
        "selected_count": selected_count,
        "excluded_count": excluded_count,
        "terminal_count": catalog_count,
        "terminal_accounting_complete": True,
        "point_in_time_valid": True,
        "freshness_valid": True,
        "universe_fingerprint": f"universe-{lane}",
        "provider_evidence_fingerprint": f"evidence-{lane}",
        "discovery_manifest_fingerprint": "fingerprint",
        "candidate_count_limit_applied": False,
        "completion_status": "complete",
        "paper_only": True,
        "investment_authority": False,
        "real_money_authorized": False,
        "completed_at": "2026-08-19T20:16:00+00:00",
    }
    artifact_sha = _digest(body)
    lane_dir = root / "certifications" / certification_id / "lanes" / lane
    _write(lane_dir / f"{artifact_sha}.json", {**body, "artifact_sha256": artifact_sha})
    _write(
        lane_dir / "current.json",
        {
            "artifact_sha256": artifact_sha,
            "artifact_path": f"{artifact_sha}.json",
            "decision_epoch": epoch,
            "release_sha": "release-test",
        },
    )
    return artifact_sha


def _write_aggregate(
    tmp_path: Path,
    *,
    epoch: str,
    lane_hashes: dict[str, str],
    certified: bool,
    blocking_reasons: list[str],
) -> None:
    certification_id = "certification-test"
    aggregate_body = {
        "schema_version": "all-market-lane-certification.v1",
        "certification_id": certification_id,
        "release_sha": "release-test",
        "decision_epoch": epoch,
        "required_lanes": ["us_equity", "fixed_income"],
        "lane_artifact_sha256": lane_hashes,
        "discovery_manifest_fingerprint": "fingerprint",
        "all_market_runtime_certified": certified,
        "blocking_reasons": blocking_reasons,
        "candidate_count_limit_applied": False,
        "paper_only": True,
        "investment_authority": False,
        "real_money_authorized": False,
    }
    aggregate_sha = _digest(aggregate_body)
    root = tmp_path / "all-market-certification"
    _write(
        root / "latest.json",
        {
            "certification_id": certification_id,
            "release_sha": "release-test",
            "decision_epoch": epoch,
            "all_market_runtime_certified": certified,
            "aggregate_sha256": aggregate_sha,
        },
    )
    _write(
        root / "certifications" / certification_id / "aggregate.json",
        {**aggregate_body, "sha256": aggregate_sha},
    )


def _rows_by_key(status: dict[str, object]) -> dict[str, dict[str, object]]:
    rows = status["rows"]
    assert isinstance(rows, list)
    return {str(row["key"]): row for row in rows}


def test_current_attempt_reports_full_governed_scope_without_overstating_completion(tmp_path: Path) -> None:
    _write_dag_attempt(tmp_path)

    status = load_asset_class_evaluation_status(values=_values(tmp_path))

    assert status["attempted"] == _GOVERNED_CLASS_COUNT
    assert status["total"] == _GOVERNED_CLASS_COUNT
    assert status["reached"] == 2
    assert status["successful"] == 0
    assert status["source"] == "Current comprehensive evaluation attempt"
    rows = _rows_by_key(status)
    assert len(rows) == _GOVERNED_CLASS_COUNT
    assert "other" not in rows
    assert rows["us_equity"]["status"] == "In progress"
    assert "terminal evaluation pending" in rows["us_equity"]["detail"]
    assert rows["fixed_income"]["status"] == "Failed"
    assert "ProviderEvidenceError" in rows["fixed_income"]["detail"]
    assert rows["crypto"]["status"] == "Awaiting evaluation"
    assert "No current-cycle terminal evaluation" in rows["crypto"]["detail"]


def test_partial_terminal_evaluation_reports_successful_over_full_governed_scope(tmp_path: Path) -> None:
    epoch = _write_dag_attempt(tmp_path)
    root = tmp_path / "all-market-certification"
    us_hash = _write_lane_artifact(
        root,
        certification_id="certification-test",
        epoch=epoch,
        lane="us_equity",
        catalog_count=500,
        deep_analyzed_count=80,
        selected_count=12,
    )
    _write_aggregate(
        tmp_path,
        epoch=epoch,
        lane_hashes={"us_equity": us_hash},
        certified=False,
        blocking_reasons=["fixed_income:missing"],
    )

    status = load_asset_class_evaluation_status(values=_values(tmp_path))

    assert status["attempted"] == _GOVERNED_CLASS_COUNT
    assert status["total"] == _GOVERNED_CLASS_COUNT
    assert status["reached"] == 2
    assert status["successful"] == 1
    assert status["source"] == "Current all-market evaluation"
    rows = _rows_by_key(status)
    assert rows["us_equity"]["status"] == "Evaluated"
    assert rows["fixed_income"]["status"] == "Failed"
    assert rows["fixed_income"]["detail"] == "missing"
    assert rows["crypto"]["status"] == "Awaiting evaluation"


def test_partial_certified_terminal_aggregate_remains_evaluation(tmp_path: Path) -> None:
    epoch = _write_dag_attempt(tmp_path)
    root = tmp_path / "all-market-certification"
    us_hash = _write_lane_artifact(
        root,
        certification_id="certification-test",
        epoch=epoch,
        lane="us_equity",
        catalog_count=500,
        deep_analyzed_count=80,
        selected_count=12,
    )
    fixed_hash = _write_lane_artifact(
        root,
        certification_id="certification-test",
        epoch=epoch,
        lane="fixed_income",
        catalog_count=220,
        deep_analyzed_count=40,
        selected_count=8,
    )
    _write_aggregate(
        tmp_path,
        epoch=epoch,
        lane_hashes={"us_equity": us_hash, "fixed_income": fixed_hash},
        certified=True,
        blocking_reasons=[],
    )

    status = load_asset_class_evaluation_status(values=_values(tmp_path))

    assert status["attempted"] == _GOVERNED_CLASS_COUNT
    assert status["total"] == _GOVERNED_CLASS_COUNT
    assert status["reached"] == 2
    assert status["successful"] == 2
    assert status["source"] == "Current all-market evaluation"
    rows = _rows_by_key(status)
    assert len(rows) == _GOVERNED_CLASS_COUNT
    assert sum(row["status"] == "Evaluated" for row in rows.values()) == 2
    assert sum(row["status"] == "Awaiting evaluation" for row in rows.values()) == 11


def test_no_runtime_evaluation_still_lists_entire_governed_universe(tmp_path: Path) -> None:
    status = load_asset_class_evaluation_status(values=_values(tmp_path))

    assert status["attempted"] == _GOVERNED_CLASS_COUNT
    assert status["total"] == _GOVERNED_CLASS_COUNT
    assert status["reached"] == 0
    assert status["successful"] == 0
    rows = _rows_by_key(status)
    assert len(rows) == _GOVERNED_CLASS_COUNT
    assert {row["status"] for row in rows.values()} == {"Awaiting evaluation"}
