from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from operations import dag_native_comprehensive_supervision as dag_native
from operations import dag_node_failure_transport as transport
from operations import persistent_certification_scheduler as scheduler


class _NestedFailureRunner:
    def __call__(self, _node: scheduler.CertificationNode) -> int:
        try:
            raise RuntimeError("coinbase checkpoint integrity failed")
        except RuntimeError as cause:
            raise scheduler.CertificationSchedulerError(
                "crypto market evidence qualification failed"
            ) from cause


class _ResourceBusyRunner:
    def __call__(self, _node: scheduler.CertificationNode) -> int:
        raise RuntimeError(
            "comprehensive discovery spool unavailable (resource_busy) for provider alpaca"
        )


def _node(epoch: datetime) -> scheduler.CertificationNode:
    return scheduler.CertificationNode(
        node_id="deep-market-evidence:crypto",
        asset_class="crypto",
        provider_groups=("alpaca", "coinbase", "kraken"),
        input_fingerprint="crypto-fingerprint",
        deadline=epoch + timedelta(minutes=5),
        decision_eligible_count=8,
    )


def _instance(monkeypatch, tmp_path, epoch: datetime) -> scheduler.PersistentCertificationScheduler:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING": "true",
        "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS": "1",
    }

    monkeypatch.setattr(
        scheduler.PersistentCertificationScheduler,
        "run",
        scheduler.PersistentCertificationScheduler.run,
    )
    monkeypatch.setattr(dag_native, "_node_worker", dag_native._node_worker)
    monkeypatch.setattr(dag_native, "_remote_error", dag_native._remote_error)
    dag_native._install_scheduler_supervision()
    transport.install_dag_node_failure_transport()

    return scheduler.PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )


def test_remote_error_preserves_safe_direct_cause_and_retry() -> None:
    detail = {
        "message": "crypto qualification failed",
        "cause_type": "RuntimeError",
        "cause_message": "coinbase checkpoint integrity failed",
    }
    error = transport._remote_error(
        "CertificationSchedulerError",
        detail,
        12.5,
    )

    assert type(error).__name__ == "CertificationSchedulerError"
    assert str(error) == "crypto qualification failed"
    assert error.retry_after_seconds == pytest.approx(12.5)
    assert error.__cause__ is not None
    assert type(error.__cause__).__name__ == "RuntimeError"
    assert str(error.__cause__) == "coinbase checkpoint integrity failed"


def test_dag_spawn_preserves_nested_crypto_terminal_cause(monkeypatch, tmp_path) -> None:
    epoch = datetime(2026, 8, 29, 5, 20, tzinfo=timezone.utc)
    node = _node(epoch)
    instance = _instance(monkeypatch, tmp_path, epoch)

    with pytest.raises(scheduler.CertificationSchedulerError) as raised:
        instance.run((node,), _NestedFailureRunner())

    message = str(raised.value)
    assert "crypto market evidence qualification failed" in message
    assert "cause=RuntimeError: coinbase checkpoint integrity failed" in message
    assert "retryable=false" in message


def test_dag_spawn_marks_resource_busy_retryable(monkeypatch, tmp_path) -> None:
    epoch = datetime(2026, 8, 29, 9, 7, 50, tzinfo=timezone.utc)
    node = _node(epoch)
    instance = _instance(monkeypatch, tmp_path, epoch)

    with pytest.raises(scheduler.CertificationSchedulerError) as raised:
        instance.run((node,), _ResourceBusyRunner())

    message = str(raised.value)
    assert "resource_busy" in message
    assert "retryable=true" in message
    assert "retry_after=" in message
