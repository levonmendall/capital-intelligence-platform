from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from operations import persistent_certification_scheduler as scheduler
from operations.retryable_certification_node_requeue import (
    install_retryable_certification_node_requeue,
)


def _record_call(path: str) -> int:
    marker = Path(path)
    calls = int(marker.read_text(encoding="utf-8")) if marker.exists() else 0
    calls += 1
    marker.write_text(str(calls), encoding="utf-8")
    return calls


class _RetryOnceRunner:
    def __init__(self, marker_path: str) -> None:
        self.marker_path = marker_path

    def __call__(self, _node: scheduler.CertificationNode) -> int:
        calls = _record_call(self.marker_path)
        if calls == 1:
            error = RuntimeError("resource_busy")
            error.retry_after_seconds = 0.01
            raise error
        return 2


class _AlwaysRetryableRunner:
    def __init__(self, marker_path: str, retry_after_seconds: float) -> None:
        self.marker_path = marker_path
        self.retry_after_seconds = retry_after_seconds

    def __call__(self, _node: scheduler.CertificationNode) -> int:
        _record_call(self.marker_path)
        error = RuntimeError("resource_busy")
        error.retry_after_seconds = self.retry_after_seconds
        raise error


class _TerminalRunner:
    def __init__(self, marker_path: str) -> None:
        self.marker_path = marker_path

    def __call__(self, _node: scheduler.CertificationNode) -> int:
        _record_call(self.marker_path)
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


def _calls(marker: Path) -> int:
    return int(marker.read_text(encoding="utf-8"))


def test_retryable_node_is_requeued_and_can_qualify(monkeypatch, tmp_path) -> None:
    _install(monkeypatch)
    epoch = datetime.now(timezone.utc)
    node = _node(epoch)
    marker = tmp_path / "retry-once-calls.txt"
    runner = _RetryOnceRunner(str(marker))

    result = _instance(tmp_path, epoch).run((node,), runner)

    assert _calls(marker) == 2
    assert result.failed_nodes == ()
    assert result.completed_nodes == (node.node_id,)


def test_non_retryable_failure_remains_terminal(monkeypatch, tmp_path) -> None:
    _install(monkeypatch)
    epoch = datetime.now(timezone.utc)
    node = _node(epoch)
    marker = tmp_path / "terminal-calls.txt"
    runner = _TerminalRunner(str(marker))

    with pytest.raises(scheduler.CertificationSchedulerError, match="retryable=false"):
        _instance(tmp_path, epoch).run((node,), runner)

    assert _calls(marker) == 1


def test_retry_hint_beyond_existing_deadline_remains_terminal(monkeypatch, tmp_path) -> None:
    _install(monkeypatch)
    epoch = datetime.now(timezone.utc)
    node = _node(epoch, deadline_seconds=0.1)
    marker = tmp_path / "deadline-calls.txt"
    runner = _AlwaysRetryableRunner(str(marker), retry_after_seconds=3.0)

    with pytest.raises(scheduler.CertificationSchedulerError, match="retryable=true"):
        _instance(tmp_path, epoch).run((node,), runner)

    assert _calls(marker) == 1
