from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from operations.release_evidence_prequalification import (
    load_release_certification_dag_progress,
    load_release_evidence_prequalification,
    write_release_evidence_prequalification,
)
from publish_cio_diagnostic_audit import _with_release_prequalification


_RELEASE = "a3b9c460cbe62b229e9da6e764203abc3409adc3"


def _values(tmp_path: Path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": _RELEASE,
    }


def _write_runtime_journal(
    tmp_path: Path,
    *,
    release: str = _RELEASE,
    epoch: datetime,
    updated_at: datetime,
    option_state: str = "running",
    option_failure_type: str | None = None,
    crypto_state: str = "pending",
    crypto_failure_type: str | None = None,
) -> Path:
    path = (
        tmp_path
        / "certification-dag"
        / "persistent-certification-dag.v1"
        / _RELEASE
        / epoch.strftime("%Y%m%dT%H%M%S%fZ")
        / "runtime-latest.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    states = {
        "deep-market-evidence:option": {
            "state": option_state,
            "asset_class": "option",
            "provider_groups": ["alpaca", "massive", "tradier"],
            "decision_eligible_count": 41,
            "reused": False,
            "failure_type": option_failure_type,
        },
        "deep-market-evidence:crypto": {
            "state": crypto_state,
            "asset_class": "crypto",
            "provider_groups": ["alpaca", "coinbase", "kraken"],
            "decision_eligible_count": 19,
            "reused": False,
            "failure_type": crypto_failure_type,
        },
    }
    completed = sum(1 for item in states.values() if item["state"] == "qualified")
    failed = sum(1 for item in states.values() if item["state"] == "failed")
    running = sum(1 for item in states.values() if item["state"] == "running")
    pending = sum(1 for item in states.values() if item["state"] == "pending")
    payload = {
        "schema_version": "persistent-certification-runtime.v1",
        "release_sha": release,
        "decision_epoch": epoch.isoformat(),
        "policy_version": "policy-v1",
        "updated_at": updated_at.isoformat(),
        "required_nodes": list(states),
        "counts": {
            "completed_nodes": completed,
            "reused_nodes": 0,
            "failed_nodes": failed,
            "running_nodes": running,
            "pending_nodes": pending,
        },
        "node_states": states,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_live_prequalification_projects_exact_lane_without_manual_cio_request(tmp_path: Path) -> None:
    values = _values(tmp_path)
    started_at = datetime(2026, 8, 18, 20, 0, tzinfo=timezone.utc)
    write_release_evidence_prequalification(
        values,
        state="in_progress",
        stage="evidence_refresh",
        started_at=started_at,
        detail="release evidence refresh active",
        metrics={"attempt": 1, "maximum_attempts": 6},
    )
    _write_runtime_journal(
        tmp_path,
        epoch=started_at + timedelta(seconds=5),
        updated_at=started_at + timedelta(seconds=30),
    )

    loaded = load_release_evidence_prequalification(values)
    assert loaded is not None
    assert loaded["runtime_projection"] is True
    assert loaded["stage"] == "certification_dag:option"
    assert loaded["metrics"]["required_nodes"] == 2
    assert loaded["metrics"]["running_nodes"] == 1
    assert loaded["dag_progress"]["active_node"] == "deep-market-evidence:option"

    public = _with_release_prequalification(
        {"state": "pending", "active_release": "", "release_matches": False},
        values=values,
    )
    assert public["request_kind"] == "evidence_prequalification"
    assert public["state"] == "prequalifying"
    assert public["stage"] == "certification_dag:option"
    assert public["progress_metrics"]["required_nodes"] == 2
    assert public["progress_metrics"]["running_nodes"] == 1


def test_runtime_loader_rejects_stale_cross_release_and_authoritative_journals(tmp_path: Path) -> None:
    values = _values(tmp_path)
    started_at = datetime(2026, 8, 18, 20, 0, tzinfo=timezone.utc)
    path = _write_runtime_journal(
        tmp_path,
        epoch=started_at - timedelta(minutes=2),
        updated_at=started_at - timedelta(minutes=1),
    )
    assert load_release_certification_dag_progress(values, started_at=started_at) is None

    _write_runtime_journal(
        tmp_path,
        release="different-release",
        epoch=started_at + timedelta(seconds=1),
        updated_at=started_at + timedelta(seconds=2),
    )
    assert load_release_certification_dag_progress(values, started_at=started_at) is None

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["release_sha"] = _RELEASE
    payload["decision_epoch"] = (started_at + timedelta(seconds=3)).isoformat()
    payload["updated_at"] = (started_at + timedelta(seconds=4)).isoformat()
    payload["decision_authority"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_release_certification_dag_progress(values, started_at=started_at) is None


def test_terminal_failure_snapshots_exact_timeout_blocker_immutably(tmp_path: Path) -> None:
    values = _values(tmp_path)
    started_at = datetime(2026, 8, 18, 20, 0, tzinfo=timezone.utc)
    path = _write_runtime_journal(
        tmp_path,
        epoch=started_at + timedelta(seconds=5),
        updated_at=started_at + timedelta(minutes=9),
        option_state="failed",
        option_failure_type="ProcessTimeout",
        crypto_state="qualified",
    )

    written = write_release_evidence_prequalification(
        values,
        state="failed",
        stage="evidence_prequalification_failed",
        started_at=started_at,
        detail=(
            "bounded evidence qualification returned code 2; "
            "child_stage=component_qualified_evidence_maintenance; "
            "child_error_type=ContinuousEvidencePlaneError; child_detail=internal_error"
        ),
        metrics={"attempt": 6, "maximum_attempts": 6, "qualifier_return_code": 2},
    )
    assert written["dag_progress"]["blocking_node"] == "deep-market-evidence:option"
    assert "node=deep-market-evidence:option" in written["detail"]
    context = written["failure_context"]
    assert context["reason"] == "deadline_exceeded"
    assert context["capability"] == "comprehensive_discovery"
    assert context["failure_stage"] == "certification_dag:option"
    assert context["error_type"] == "ProcessTimeout"
    assert context["blocking_node"] == "deep-market-evidence:option"
    assert context["provider_groups"] == ["alpaca", "massive", "tradier"]

    replacement = json.loads(path.read_text(encoding="utf-8"))
    replacement["updated_at"] = (started_at + timedelta(minutes=10)).isoformat()
    replacement["node_states"]["deep-market-evidence:option"].update(
        {"state": "qualified", "failure_type": None}
    )
    replacement["node_states"]["deep-market-evidence:crypto"].update(
        {"state": "failed", "failure_type": "ProviderError"}
    )
    replacement["counts"].update(
        {"completed_nodes": 1, "failed_nodes": 1, "running_nodes": 0, "pending_nodes": 0}
    )
    path.write_text(json.dumps(replacement), encoding="utf-8")

    loaded = load_release_evidence_prequalification(values)
    assert loaded is not None
    assert loaded["state"] == "failed"
    assert loaded["stage"] == "evidence_prequalification_failed"
    assert loaded.get("runtime_projection") is None
    assert loaded["dag_progress"]["blocking_node"] == "deep-market-evidence:option"
    assert loaded["failure_context"]["failure_type"] == "ProcessTimeout"

    public = _with_release_prequalification(
        {"state": "pending", "active_release": "", "release_matches": False},
        values=values,
    )
    assert public["state"] == "failed"
    assert public["stage"] == "evidence_prequalification_failed"
    assert public["prequalification_failure_reason"] == "deadline_exceeded"
    assert public["prequalification_failure_capability"] == "comprehensive_discovery"
    assert public["prequalification_failure_stage"] == "certification_dag:option"
    assert public["prequalification_failure_error_type"] == "ProcessTimeout"
    assert (
        public["prequalification_failure_context"]["blocking_node"]
        == "deep-market-evidence:option"
    )
    assert "node=deep-market-evidence:option" in public["detail"]
