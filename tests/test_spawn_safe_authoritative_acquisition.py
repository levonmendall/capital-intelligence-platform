from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pickle

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


def test_spawn_payload_contains_only_selected_lane_records() -> None:
    epoch = datetime(2026, 8, 18, 18, 30, tzinfo=timezone.utc)
    equity = _node("equity", epoch)
    crypto = _node("crypto", epoch)
    runner = SpawnSafeLaneRunner(
        deep_records={
            equity.node_id: ("eq-1", "eq-2"),
            crypto.node_id: ("crypto-1",),
        },
        timestamp=epoch,
        policy="policy-v1",
    )

    child = runner.for_node(crypto)
    assert child.records == ("crypto-1",)
    assert "eq-1" not in child.records
    assert pickle.loads(pickle.dumps(child)).records == ("crypto-1",)


def test_spawn_payload_requires_exact_node_membership() -> None:
    epoch = datetime(2026, 8, 18, 18, 31, tzinfo=timezone.utc)
    known = _node("equity", epoch)
    unknown = _node("crypto", epoch)
    runner = SpawnSafeLaneRunner(
        deep_records={known.node_id: ("eq-1",)},
        timestamp=epoch,
        policy="policy-v1",
    )

    try:
        runner.for_node(unknown)
    except RuntimeError as error:
        assert unknown.node_id in str(error)
    else:
        raise AssertionError("missing lane records must fail closed")
