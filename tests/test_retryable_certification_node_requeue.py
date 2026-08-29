from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from operations import persistent_certification_scheduler as scheduler
from operations.retryable_certification_node_requeue import (
    install_retryable_certification_node_requeue,
)


class _RetryOnceRunner:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _node: scheduler.CertificationNode) -> int:
        self.calls += 1
        if self.calls == 1:
            error = RuntimeError("resource_busy")
            error.retry_after_seconds = 0.01
            raise error
        return 2


class _AlwaysRetryableRunner:
    def __init__(self, retry_after_seconds: float) -> None:
        self.calls = 0
        self.retry_after_seconds = retry_after_seconds

    def __call__(self, _node: scheduler.CertificationNode) -> int:
        self.calls += 1
        error = RuntimeError("resource_busy")
        error.retry_after_seconds = self.retry_after_seconds
        raise error


class _TerminalRunner:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _node: scheduler.CertificationNode) -> int:
        self.calls += 1
        raise RuntimeError("malformed evidence")


def _values(tmp_path):
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING": "true",
        "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS": "1",
    }


def _node(epoch: datetime, *, deadline_seconds: float = 30.0) -> scheduler.CertificationNode:
    return scheduler.CertificationNode(
        node_id="deep-market-evidence:crypto",
        asset_class="crypto",
        provider_groups=("alpaca", "coinbase", "kraken"),
        input_fingerprint="crypto-fingerprint",
        deadline=epoch + timedelta(seconds=deadline_seconds),
        decision_eligible_count=8,
    )


def _instance(tmp_path, epoch: datetime) -> scheduler.PersistentCertificationScheduler:
    return scheduler.PersistentCertificationScheduler(
        values=_values(tmp_path),
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )


def _install(monkeypatch) -> None:
    original = scheduler.PersistentCertificationScheduler.run
    monkeypatch.setattr(scheduler.PersistentCertificationScheduler, "run", original)
    install_retryable_certification_node_requeue()


def test_retryable_node_is_requeued_and_can_qualify(monkeypatch, tmp_path) -> None:
    _install(monkeypatch)
    epoch = datetime.now(timezone.utc)
    node = _node(epoch)
    runner = _RetryOnceRunner()

    result = _instance(tmp_path, epoch).run((node,), runner)

    assert runner.calls == 2
    assert result.failed_nodes == ()
    assert result.completed_nodes == (node.node_id,)


def test_non_retryable_failure_remains_terminal(monkeypatch, tmp_path) -> None:
    _install(monkeypatch)
    epoch = datetime.now(timezone.utc)
    node = _node(epoch)
    runner = _TerminalRunner()

    with pytest.raises(scheduler.CertificationSchedulerError, match="retryable=false"):
        _instance(tmp_path, epoch).run((node,), runner)

    assert runner.calls == 1


def test_retry_hint_beyond_existing_deadline_remains_terminal(monkeypatch, tmp_path) -> None:
    _install(monkeypatch)
    epoch = datetime.now(timezone.utc)
    node = _node(epoch, deadline_seconds=0.1)
    runner = _AlwaysRetryableRunner(retry_after_seconds=3.0)

    with pytest.raises(scheduler.CertificationSchedulerError, match="retryable=true"):
        _instance(tmp_path, epoch).run((node,), runner)

    assert runner.calls == 1
