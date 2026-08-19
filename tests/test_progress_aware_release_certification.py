from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import time

import pytest

from operations import component_qualified_evidence_maintenance as maintenance
from operations import dag_native_comprehensive_supervision as dag_native
from operations import manual_cio_diagnostic as diagnostic
from operations import persistent_certification_scheduler as scheduler
from operations import progress_aware_release_certification as progress_aware
from operations import release_evidence_prequalification as release_state


@dataclass(frozen=True, slots=True)
class _ProgressingRunner:
    timestamp: datetime
    pauses: int = 4
    pause_seconds: float = 0.04

    def __call__(self, _node: scheduler.CertificationNode) -> int:
        for index in range(self.pauses):
            time.sleep(self.pause_seconds)
            diagnostic.record_manual_cio_diagnostic_progress(
                "deep_market_evidence:international_equity",
                metrics={"processed_records": index + 1},
            )
        return self.pauses


@dataclass(frozen=True, slots=True)
class _SilentRunner:
    timestamp: datetime
    delay_seconds: float = 0.3

    def __call__(self, _node: scheduler.CertificationNode) -> int:
        time.sleep(self.delay_seconds)
        return 1


def _node(epoch: datetime) -> scheduler.CertificationNode:
    return scheduler.CertificationNode(
        node_id="deep-market-evidence:international_equity",
        asset_class="international_equity",
        provider_groups=("alpaca", "eodhd"),
        input_fingerprint="fingerprint-international-equity",
        deadline=epoch + timedelta(minutes=15),
        decision_eligible_count=4,
    )


def _values(tmp_path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING": "true",
        "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS": "1",
        "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_NODE_TIMEOUT_SECONDS": "0.08",
    }


def _install_supervision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        scheduler.PersistentCertificationScheduler,
        "run",
        scheduler.PersistentCertificationScheduler.run,
    )
    monkeypatch.setattr(
        maintenance,
        "_supervised_discovery_runner",
        maintenance._supervised_discovery_runner,
    )
    monkeypatch.setattr(dag_native, "_node_worker", dag_native._node_worker)
    monkeypatch.setattr(dag_native, "_poll_running", dag_native._poll_running)
    monkeypatch.setattr(dag_native, "_close_running", dag_native._close_running)
    dag_native.install_dag_native_comprehensive_supervision()
    progress_aware.install_progress_aware_dag_node_supervision()


def _runtime_path(tmp_path, epoch: datetime):
    return (
        tmp_path
        / "certification-dag"
        / scheduler._SCHEMA_VERSION
        / "release-test"
        / scheduler._epoch_key(epoch)
        / "runtime-latest.json"
    )


def _write_runtime(
    tmp_path,
    *,
    epoch: datetime,
    updated_at: datetime,
    state: str = "running",
    failure_type: str | None = None,
) -> None:
    node = _node(epoch)
    payload = {
        "schema_version": "persistent-certification-runtime.v1",
        "release_sha": "release-test",
        "decision_epoch": epoch.isoformat(),
        "policy_version": "policy-v1",
        "updated_at": updated_at.isoformat(),
        "required_nodes": [node.node_id],
        "counts": {
            "completed_nodes": 0,
            "reused_nodes": 0,
            "failed_nodes": 1 if state == "failed" else 0,
            "running_nodes": 1 if state == "running" else 0,
            "pending_nodes": 0,
        },
        "node_states": {
            node.node_id: {
                "state": state,
                "asset_class": node.asset_class,
                "provider_groups": list(node.provider_groups),
                "decision_eligible_count": node.decision_eligible_count,
                "reused": False,
                "failure_type": failure_type,
            }
        },
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    path = _runtime_path(tmp_path, epoch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_progress_resets_node_stall_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    epoch = datetime(2026, 8, 19, 2, 0, tzinfo=timezone.utc)
    values = _values(tmp_path)
    _install_supervision(monkeypatch)

    instance = scheduler.PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )
    started = time.monotonic()
    result = instance.run((_node(epoch),), _ProgressingRunner(timestamp=epoch))

    assert time.monotonic() - started > 0.08
    assert result.failed_nodes == ()
    assert result.completed_nodes == (_node(epoch).node_id,)


def test_silent_node_still_fails_closed_after_stall_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    epoch = datetime(2026, 8, 19, 2, 1, tzinfo=timezone.utc)
    values = _values(tmp_path)
    _install_supervision(monkeypatch)

    instance = scheduler.PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )
    with pytest.raises(
        scheduler.CertificationSchedulerError,
        match="deep-market-evidence:international_equity:SupervisedComponentTimeout",
    ):
        instance.run((_node(epoch),), _SilentRunner(timestamp=epoch))

    runtime = json.loads(_runtime_path(tmp_path, epoch).read_text(encoding="utf-8"))
    state = runtime["node_states"][_node(epoch).node_id]
    assert state["state"] == "failed"
    assert state["failure_type"] == "SupervisedComponentTimeout"


def test_current_attempt_can_resume_older_decision_epoch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    epoch = datetime(2026, 8, 19, 1, 30, tzinfo=timezone.utc)
    attempt_started = datetime(2026, 8, 19, 2, 0, tzinfo=timezone.utc)
    journal_updated = attempt_started + timedelta(seconds=5)
    values = _values(tmp_path)
    _write_runtime(tmp_path, epoch=epoch, updated_at=journal_updated)

    monkeypatch.setattr(
        release_state,
        "load_release_certification_dag_progress",
        release_state.load_release_certification_dag_progress,
    )
    progress_aware.install_resume_aware_release_dag_projection()

    projected = release_state.load_release_certification_dag_progress(
        values,
        started_at=attempt_started,
    )

    assert projected is not None
    assert projected["decision_epoch"] == epoch.isoformat()
    assert projected["updated_at"] == journal_updated.isoformat()
    assert projected["active_node"] == _node(epoch).node_id


def test_stale_resumed_journal_remains_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    epoch = datetime(2026, 8, 19, 1, 30, tzinfo=timezone.utc)
    attempt_started = datetime(2026, 8, 19, 2, 0, tzinfo=timezone.utc)
    values = _values(tmp_path)
    _write_runtime(
        tmp_path,
        epoch=epoch,
        updated_at=attempt_started - timedelta(seconds=1),
    )

    monkeypatch.setattr(
        release_state,
        "load_release_certification_dag_progress",
        release_state.load_release_certification_dag_progress,
    )
    progress_aware.install_resume_aware_release_dag_projection()

    assert (
        release_state.load_release_certification_dag_progress(
            values,
            started_at=attempt_started,
        )
        is None
    )


def test_durable_node_sidecar_advances_running_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    epoch = datetime(2026, 8, 19, 1, 30, tzinfo=timezone.utc)
    attempt_started = datetime(2026, 8, 19, 2, 0, tzinfo=timezone.utc)
    journal_updated = attempt_started + timedelta(seconds=1)
    sidecar_updated = attempt_started + timedelta(seconds=6)
    values = _values(tmp_path)
    node = _node(epoch)
    _write_runtime(tmp_path, epoch=epoch, updated_at=journal_updated)

    sidecar_path = progress_aware._node_progress_path(
        values,
        release_sha="release-test",
        epoch=epoch,
        node_id=node.node_id,
    )
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(
        json.dumps(
            {
                "schema_version": "persistent-certification-node-progress.v1",
                "release_sha": "release-test",
                "decision_epoch": epoch.isoformat(),
                "node_id": node.node_id,
                "asset_class": node.asset_class,
                "updated_at": sidecar_updated.isoformat(),
                "stage": "provider_io_progress",
                "metrics": {"provider_calls_completed": 3},
                "decision_authority": False,
                "candidate_authority": False,
                "sizing_authority": False,
                "execution_authority": False,
                "paper_only": True,
                "real_money_authorized": False,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        release_state,
        "load_release_certification_dag_progress",
        release_state.load_release_certification_dag_progress,
    )
    progress_aware.install_resume_aware_release_dag_projection()

    projected = release_state.load_release_certification_dag_progress(
        values,
        started_at=attempt_started,
    )

    assert projected is not None
    assert projected["updated_at"] == sidecar_updated.isoformat()
    assert projected["active_node"] == node.node_id
    assert projected["node_progress"]["stage"] == "provider_io_progress"
    assert projected["node_progress"]["metrics"] == {"provider_calls_completed": 3}
