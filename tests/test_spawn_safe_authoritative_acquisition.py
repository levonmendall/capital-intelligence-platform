from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pickle

import pytest

from operations.persistent_certification_scheduler import CertificationNode
from operations import spawn_safe_authoritative_acquisition as _spawn
from operations.spawn_safe_authoritative_acquisition import SpawnSafeLaneRunner


def _node(name: str, epoch: datetime) -> CertificationNode:
    provider_groups = ("alpaca", "coinbase", "kraken") if name == "crypto" else ("generic",)
    return CertificationNode(
        node_id=f"deep-market-evidence:{name}",
        asset_class=name,
        provider_groups=provider_groups,
        input_fingerprint=f"fingerprint-{name}",
        deadline=epoch + timedelta(minutes=5),
        decision_eligible_count=8 if name == "crypto" else 2,
    )


def test_spawn_payload_contains_only_compact_spool_locator() -> None:
    epoch = datetime(2026, 8, 18, 18, 30, tzinfo=timezone.utc)
    crypto = _node("crypto", epoch)
    runner = SpawnSafeLaneRunner(
        manifest_path="/tmp/governed-comprehensive-spool/manifest.json",
        timestamp=epoch,
        policy_version="policy-v1",
    )

    child = runner.for_node(crypto)
    assert child.manifest_path.endswith("manifest.json")
    assert child.node_id == crypto.node_id
    assert not hasattr(child, "records")
    assert not hasattr(runner, "deep_records")

    restored = pickle.loads(pickle.dumps(child))
    assert restored.node_id == crypto.node_id
    assert restored.manifest_path == child.manifest_path
    assert not hasattr(restored, "records")


def test_spawn_payload_requires_exact_node_identity_before_loading_spool() -> None:
    epoch = datetime(2026, 8, 18, 18, 31, tzinfo=timezone.utc)
    known = _node("equity", epoch)
    unknown = _node("crypto", epoch)
    runner = SpawnSafeLaneRunner(
        manifest_path="/tmp/governed-comprehensive-spool/manifest.json",
        timestamp=epoch,
        policy_version="policy-v1",
    )
    child = runner.for_node(known)

    with pytest.raises(RuntimeError, match="node identity changed"):
        child(unknown)


def test_lane_failure_sidecar_preserves_safe_type_detail_cause_and_retry(tmp_path) -> None:
    epoch = datetime(2026, 8, 29, 5, 20, tzinfo=timezone.utc)
    node = _node("crypto", epoch)
    manifest_path = tmp_path / "manifest.json"

    class AlpacaDiscoveryError(RuntimeError):
        pass

    try:
        raise ValueError("provider checkpoint rejected response")
    except ValueError as cause:
        error = AlpacaDiscoveryError("alpaca quote acquisition failed API_KEY=secret-value")
        error.__cause__ = cause
    error.retry_after_seconds = 17.0

    _spawn._write_lane_failure(
        manifest_path,
        node=node,
        timestamp=epoch,
        policy_version="policy-v1",
        error=error,
    )
    restored = _spawn._load_lane_failure(
        manifest_path,
        node=node,
        timestamp=epoch,
        policy_version="policy-v1",
        return_code=2,
        pid=220,
    )

    assert type(restored).__name__ == "AlpacaDiscoveryError"
    assert "alpaca quote acquisition failed" in str(restored)
    assert "secret-value" not in str(restored)
    assert "subprocess_return_code=2" in str(restored)
    assert "subprocess_pid=220" in str(restored)
    assert restored.retry_after_seconds == pytest.approx(17.0)
    assert restored.__cause__ is not None
    assert type(restored.__cause__).__name__ == "ValueError"
    assert "provider checkpoint rejected response" in str(restored.__cause__)


def test_nonzero_lane_subprocess_rethrows_durable_crypto_failure(monkeypatch, tmp_path) -> None:
    epoch = datetime(2026, 8, 29, 5, 20, tzinfo=timezone.utc)
    node = _node("crypto", epoch)
    manifest_path = tmp_path / "manifest.json"
    runner = SpawnSafeLaneRunner(
        manifest_path=str(manifest_path),
        timestamp=epoch,
        policy_version="policy-v1",
    ).for_node(node)

    class FakeProcess:
        pid = 220

        def wait(self) -> int:
            return 2

    def fake_popen(*args, **kwargs):
        error = RuntimeError("alpaca provider returned malformed crypto evidence")
        _spawn._write_lane_failure(
            manifest_path,
            node=node,
            timestamp=epoch,
            policy_version="policy-v1",
            error=error,
        )
        return FakeProcess()

    monkeypatch.setattr(_spawn.subprocess, "Popen", fake_popen)

    with pytest.raises(RuntimeError) as failure:
        runner(node)

    assert type(failure.value).__name__ == "RuntimeError"
    assert "alpaca provider returned malformed crypto evidence" in str(failure.value)
    assert "subprocess_return_code=2" in str(failure.value)


def test_nonzero_lane_subprocess_without_failure_sidecar_fails_closed(monkeypatch, tmp_path) -> None:
    epoch = datetime(2026, 8, 29, 5, 20, tzinfo=timezone.utc)
    node = _node("crypto", epoch)
    runner = SpawnSafeLaneRunner(
        manifest_path=str(tmp_path / "manifest.json"),
        timestamp=epoch,
        policy_version="policy-v1",
    ).for_node(node)

    class FakeProcess:
        pid = 221

        def wait(self) -> int:
            return 2

    monkeypatch.setattr(_spawn.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    with pytest.raises(RuntimeError, match="without durable failure attribution"):
        runner(node)
