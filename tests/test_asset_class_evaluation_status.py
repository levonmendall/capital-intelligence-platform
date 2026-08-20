from __future__ import annotations

import hashlib
import json
from pathlib import Path

from operations.asset_class_evaluation_status import load_asset_class_evaluation_status


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


def test_current_attempt_reports_attempted_classes_without_overstating_completion(tmp_path: Path) -> None:
    _write_dag_attempt(tmp_path)

    status = load_asset_class_evaluation_status(values=_values(tmp_path))

    assert status["attempted"] == 2
    assert status["successful"] == 0
    assert status["source"] == "Current comprehensive evaluation attempt"
    rows = {row["key"]: row for row in status["rows"]}
    assert rows["us_equity"]["status"] == "In progress"
    assert "terminal evaluation pending" in rows["us_equity"]["detail"]
    assert rows["fixed_income"]["status"] == "Failed"
    assert "ProviderEvidenceError" in rows["fixed_income"]["detail"]


def test_matching_terminal_certification_upgrades_attempted_classes_to_evaluated(tmp_path: Path) -> None:
    epoch = _write_dag_attempt(tmp_path)
    certification_id = "certification-test"
    aggregate_body = {
        "schema_version": "all-market-lane-certification.v1",
        "certification_id": certification_id,
        "release_sha": "release-test",
        "decision_epoch": epoch,
        "required_lanes": ["us_equity", "fixed_income"],
        "lane_artifact_sha256": {},
        "discovery_manifest_fingerprint": "fingerprint",
        "all_market_runtime_certified": True,
        "blocking_reasons": [],
        "candidate_count_limit_applied": False,
        "paper_only": True,
        "investment_authority": False,
        "real_money_authorized": False,
    }
    root = tmp_path / "all-market-certification"
    _write(
        root / "latest.json",
        {
            "certification_id": certification_id,
            "release_sha": "release-test",
            "decision_epoch": epoch,
            "all_market_runtime_certified": True,
            "aggregate_sha256": _digest(aggregate_body),
        },
    )
    _write(
        root / "certifications" / certification_id / "aggregate.json",
        {**aggregate_body, "sha256": _digest(aggregate_body)},
    )

    status = load_asset_class_evaluation_status(values=_values(tmp_path))

    assert status["attempted"] == 2
    assert status["successful"] == 2
    assert status["source"] == "Current all-market certification"
    assert {row["status"] for row in status["rows"]} == {"Evaluated"}
