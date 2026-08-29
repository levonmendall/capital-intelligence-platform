from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from operations import spawn_safe_authoritative_acquisition as spawn_safe
from operations import spawn_safe_lane_terminal_transport as transport
from operations.persistent_certification_scheduler import CertificationNode


def _node(epoch: datetime) -> CertificationNode:
    return CertificationNode(
        node_id="deep-market-evidence:crypto",
        asset_class="crypto",
        provider_groups=("alpaca", "coinbase", "kraken"),
        input_fingerprint="crypto-fingerprint",
        deadline=epoch + timedelta(minutes=5),
        decision_eligible_count=8,
    )


def test_child_failure_record_preserves_exact_safe_terminal_truth(tmp_path) -> None:
    epoch = datetime(2026, 8, 29, 5, 20, tzinfo=timezone.utc)
    node = _node(epoch)
    manifest_path = tmp_path / "manifest.json"

    try:
        raise RuntimeError("alpaca historical bars response failed")
    except RuntimeError as cause:
        error = ValueError("crypto market evidence qualification failed")
        error.__cause__ = cause

    path = transport._write_failure(
        manifest_path,
        node_id=node.node_id,
        input_fingerprint=node.input_fingerprint,
        error=error,
    )
    assert path.exists()
    body = transport._load_failure(manifest_path, node=node)
    assert body["failure_type"] == "ValueError"
    assert body["failure_message"] == "crypto market evidence qualification failed"
    assert body["failure_cause_type"] == "RuntimeError"
    assert body["failure_cause_message"] == "alpaca historical bars response failed"
    assert body["retry_after_seconds"] is None
    assert body["paper_only"] is True
    assert body["real_money_authorized"] is False


def test_parent_raises_from_child_terminal_truth_instead_of_return_code(tmp_path, monkeypatch) -> None:
    epoch = datetime(2026, 8, 29, 5, 20, tzinfo=timezone.utc)
    node = _node(epoch)
    manifest_path = tmp_path / "manifest.json"

    class FailedProcess:
        pid = 220

        def wait(self):
            child = RuntimeError("alpaca provider request failed deterministically")
            transport._write_failure(
                manifest_path,
                node_id=node.node_id,
                input_fingerprint=node.input_fingerprint,
                error=child,
            )
            return 2

    monkeypatch.setattr(transport.subprocess, "Popen", lambda *args, **kwargs: FailedProcess())
    runner = spawn_safe.SpawnSafeSingleLaneRunner(
        manifest_path=str(manifest_path),
        node_id=node.node_id,
        timestamp=epoch,
        policy_version="policy-v1",
    )

    with pytest.raises(RuntimeError) as captured:
        transport._call_with_terminal_truth(runner, node)

    message = str(captured.value)
    assert "child_failure_type=RuntimeError" in message
    assert "alpaca provider request failed deterministically" in message
    assert "return_code=2" in message
    assert captured.value.__cause__ is not None
    assert type(captured.value.__cause__).__name__ == "RuntimeError"
    assert str(captured.value.__cause__) == "alpaca provider request failed deterministically"


def test_nonzero_exit_without_terminal_record_is_classified_as_transport_failure(
    tmp_path, monkeypatch
) -> None:
    epoch = datetime(2026, 8, 29, 5, 20, tzinfo=timezone.utc)
    node = _node(epoch)

    class FailedProcess:
        pid = 221

        def wait(self):
            return 2

    monkeypatch.setattr(transport.subprocess, "Popen", lambda *args, **kwargs: FailedProcess())
    runner = spawn_safe.SpawnSafeSingleLaneRunner(
        manifest_path=str(tmp_path / "manifest.json"),
        node_id=node.node_id,
        timestamp=epoch,
        policy_version="policy-v1",
    )

    with pytest.raises(RuntimeError, match="without durable terminal truth"):
        transport._call_with_terminal_truth(runner, node)


def test_runtime_installer_replaces_only_spawn_safe_lane_call_boundary() -> None:
    original = spawn_safe.SpawnSafeSingleLaneRunner.__call__
    try:
        transport.install_spawn_safe_lane_terminal_transport()
        installed = spawn_safe.SpawnSafeSingleLaneRunner.__call__
        assert installed is transport._call_with_terminal_truth
        assert getattr(installed, "_durable_lane_terminal_truth", False) is True
    finally:
        spawn_safe.SpawnSafeSingleLaneRunner.__call__ = original
