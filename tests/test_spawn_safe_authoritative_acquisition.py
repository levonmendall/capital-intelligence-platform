from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pickle

import pytest

from operations.persistent_certification_scheduler import CertificationNode
from operations.spawn_safe_authoritative_acquisition import SpawnSafeLaneRunner


def _node(name: str, epoch: datetime) -> CertificationNode:
    return CertificationNode(
        node_id=f"deep-market-evidence:{name}",
        asset_class=name,
        provider_groups=("generic",),
        input_fingerprint=f"fingerprint-{name}",
        deadline=epoch + timedelta(minutes=5),
        decision_eligible_count=2,
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
