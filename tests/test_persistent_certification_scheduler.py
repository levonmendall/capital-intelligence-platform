from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from operations import persistent_certification_scheduler as scheduler_module
from operations.persistent_certification_scheduler import (
    CertificationNode,
    CertificationSchedulerError,
    PersistentCertificationScheduler,
    ProviderBudgetRegistry,
    install_certification_scheduler,
)


@dataclass(frozen=True, slots=True)
class _FailOneNodeRunner:
    failed_node_id: str
    evidence_count: int = 1
    message: str = "simulated provider failure"

    def __call__(self, node: CertificationNode) -> int:
        if node.node_id == self.failed_node_id:
            raise RuntimeError(self.message)
        return self.evidence_count


@dataclass(frozen=True, slots=True)
class _ConstantRunner:
    evidence_count: int = 1

    def __call__(self, _node: CertificationNode) -> int:
        return self.evidence_count


@dataclass(frozen=True, slots=True)
class _NestedCryptoFailureRunner:
    """Spawn-picklable production-shaped runner preserving an explicit direct cause."""

    def __call__(self, _node: CertificationNode) -> int:
        try:
            raise RuntimeError("coinbase checkpoint integrity failed")
        except RuntimeError as cause:
            raise CertificationSchedulerError(
                "crypto market evidence qualification failed"
            ) from cause


def _values(tmp_path):
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING": "true",
        "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS": "3",
    }


def _node(
    name: str,
    *,
    provider: str,
    epoch: datetime,
    dependencies: tuple[str, ...] = (),
) -> CertificationNode:
    return CertificationNode(
        node_id=name,
        asset_class=name.rsplit(":", 1)[-1],
        provider_groups=(provider,),
        input_fingerprint=f"fingerprint-{name}",
        deadline=epoch + timedelta(minutes=5),
        decision_eligible_count=3,
        dependencies=dependencies,
    )


def _latest_manifest(values, *, epoch: datetime) -> dict[str, object]:
    path = (
        scheduler_module._root(values)
        / scheduler_module._SCHEMA_VERSION
        / "release-test"
        / scheduler_module._epoch_key(epoch)
        / "latest.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["sha256"] == scheduler_module._digest(payload["body"])
    return payload["body"]


def test_successful_node_is_reused_after_other_node_failure(tmp_path) -> None:
    epoch = datetime(2026, 8, 18, 0, 45, tzinfo=timezone.utc)
    values = _values(tmp_path)
    equity = _node("deep-market-evidence:equity", provider="eodhd", epoch=epoch)
    crypto = _node("deep-market-evidence:crypto", provider="coinbase", epoch=epoch)
    nodes = (equity, crypto)

    first = PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )
    with pytest.raises(CertificationSchedulerError, match="crypto:RuntimeError"):
        first.run(
            nodes,
            _FailOneNodeRunner(
                failed_node_id=crypto.node_id,
                evidence_count=3,
                message="simulated crypto provider failure",
            ),
        )

    first_manifest = _latest_manifest(values, epoch=epoch)
    assert first_manifest["completed_nodes"] == [equity.node_id]
    assert first_manifest["failed_nodes"] == [crypto.node_id]
    assert first_manifest["node_results"][equity.node_id] == {
        "status": "qualified",
        "reused": False,
        "evidence_complete_count": 3,
        "failure_type": None,
        "failure_message": None,
        "failure_cause_type": None,
        "failure_cause_message": None,
        "retryable": False,
        "retry_after": None,
    }
    assert first_manifest["node_results"][crypto.node_id]["status"] == "failed"
    assert first_manifest["node_results"][crypto.node_id]["failure_type"] == "RuntimeError"
    assert (
        first_manifest["node_results"][crypto.node_id]["failure_message"]
        == "simulated crypto provider failure"
    )
    assert first_manifest["node_results"][crypto.node_id]["retryable"] is False

    second = PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )
    result = second.run(nodes, _ConstantRunner(evidence_count=2))

    assert result.failed_nodes == ()
    assert result.reused_nodes == (equity.node_id,)
    assert set(result.completed_nodes) == {node.node_id for node in nodes}
    assert result.path.exists()

    second_manifest = _latest_manifest(values, epoch=epoch)
    assert second_manifest["node_results"][equity.node_id]["reused"] is True
    assert second_manifest["node_results"][equity.node_id]["evidence_complete_count"] == 3
    assert second_manifest["node_results"][crypto.node_id]["reused"] is False
    assert second_manifest["node_results"][crypto.node_id]["evidence_complete_count"] == 2


def test_nested_crypto_failure_persists_exact_terminal_truth(tmp_path) -> None:
    epoch = datetime(2026, 8, 18, 0, 47, tzinfo=timezone.utc)
    values = _values(tmp_path)
    crypto = _node("deep-market-evidence:crypto", provider="coinbase", epoch=epoch)
    scheduler = PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )

    with pytest.raises(CertificationSchedulerError) as raised:
        scheduler.run((crypto,), _NestedCryptoFailureRunner())

    assert "crypto market evidence qualification failed" in str(raised.value)
    assert "cause=RuntimeError: coinbase checkpoint integrity failed" in str(raised.value)
    assert "retryable=false" in str(raised.value)

    manifest = _latest_manifest(values, epoch=epoch)
    result = manifest["node_results"][crypto.node_id]
    assert result["failure_type"] == "CertificationSchedulerError"
    assert result["failure_message"] == "crypto market evidence qualification failed"
    assert result["failure_cause_type"] == "RuntimeError"
    assert result["failure_cause_message"] == "coinbase checkpoint integrity failed"
    assert result["retryable"] is False
    assert result["retry_after"] is None


def test_provider_budget_is_shared_without_blocking_unrelated_provider(tmp_path) -> None:
    values = _values(tmp_path)
    values["CAPITAL_INTELLIGENCE_CERTIFICATION_PROVIDER_EODHD_CAPACITY"] = "1"
    values["CAPITAL_INTELLIGENCE_CERTIFICATION_PROVIDER_COINBASE_CAPACITY"] = "1"
    registry = ProviderBudgetRegistry(values, ("eodhd", "coinbase"))

    first_eodhd = registry.try_acquire(("eodhd",))
    assert first_eodhd == ("eodhd",)
    assert registry.try_acquire(("eodhd",)) is None

    coinbase = registry.try_acquire(("coinbase",))
    assert coinbase == ("coinbase",)
    registry.release(coinbase)

    registry.release(first_eodhd)
    second_eodhd = registry.try_acquire(("eodhd",))
    assert second_eodhd == ("eodhd",)
    registry.release(second_eodhd)


def test_failed_dependency_does_not_prevent_independent_work_from_persisting(tmp_path) -> None:
    epoch = datetime(2026, 8, 18, 0, 50, tzinfo=timezone.utc)
    values = _values(tmp_path)
    root = _node("root:eodhd", provider="eodhd", epoch=epoch)
    dependent = _node(
        "dependent:equity",
        provider="eodhd",
        epoch=epoch,
        dependencies=(root.node_id,),
    )
    independent = _node("independent:crypto", provider="coinbase", epoch=epoch)

    first = PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )
    with pytest.raises(CertificationSchedulerError):
        first.run(
            (root, dependent, independent),
            _FailOneNodeRunner(
                failed_node_id=root.node_id,
                evidence_count=1,
                message="root unavailable",
            ),
        )

    first_manifest = _latest_manifest(values, epoch=epoch)
    assert first_manifest["node_results"][root.node_id]["failure_type"] == "RuntimeError"
    assert first_manifest["node_results"][independent.node_id]["status"] == "qualified"
    assert first_manifest["node_results"][independent.node_id]["evidence_complete_count"] == 1
    assert first_manifest["node_results"][dependent.node_id]["status"] == "failed"
    assert (
        first_manifest["node_results"][dependent.node_id]["failure_type"]
        == "CertificationSchedulerError"
    )

    second = PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )
    result = second.run((root, dependent, independent), _ConstantRunner(evidence_count=1))
    assert result.reused_nodes == (independent.node_id,)
    assert set(result.completed_nodes) == {root.node_id, dependent.node_id, independent.node_id}

    second_manifest = _latest_manifest(values, epoch=epoch)
    assert second_manifest["node_results"][independent.node_id]["reused"] is True
    assert second_manifest["node_results"][root.node_id]["reused"] is False
    assert second_manifest["node_results"][dependent.node_id]["reused"] is False


def test_install_scheduler_only_prewarms_canonical_enabled_path(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    def delegate(**_kwargs):
        calls.append("delegate")
        return "result"

    fake_core = SimpleNamespace(discover_comprehensive_markets=delegate)
    install_certification_scheduler(fake_core)

    prewarm_calls: list[str] = []

    def fake_prewarm(_core, **_kwargs):
        prewarm_calls.append("prewarm")
        return None

    monkeypatch.setattr(scheduler_module, "prewarm_comprehensive_discovery", fake_prewarm)
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_RELEASE", "release-test")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING", "true")

    as_of = datetime(2026, 8, 18, 0, 55, tzinfo=timezone.utc)
    assert fake_core.discover_comprehensive_markets(as_of=as_of) == "result"
    assert prewarm_calls == ["prewarm"]

    prewarm_calls.clear()
    assert (
        fake_core.discover_comprehensive_markets(
            as_of=as_of,
            market_probe=lambda *_args, **_kwargs: {},
        )
        == "result"
    )
    assert prewarm_calls == []
    assert calls == ["delegate", "delegate"]
