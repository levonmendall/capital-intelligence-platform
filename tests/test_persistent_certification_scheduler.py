from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def test_successful_node_is_reused_after_other_node_failure(tmp_path) -> None:
    epoch = datetime(2026, 8, 18, 0, 45, tzinfo=timezone.utc)
    values = _values(tmp_path)
    nodes = (
        _node("deep-market-evidence:equity", provider="eodhd", epoch=epoch),
        _node("deep-market-evidence:crypto", provider="coinbase", epoch=epoch),
    )
    first_calls: list[str] = []

    def first_runner(node: CertificationNode) -> int:
        first_calls.append(node.node_id)
        if node.node_id.endswith("crypto"):
            raise RuntimeError("simulated crypto provider failure")
        return 3

    first = PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )
    with pytest.raises(CertificationSchedulerError, match="crypto:RuntimeError"):
        first.run(nodes, first_runner)
    assert set(first_calls) == {node.node_id for node in nodes}

    second_calls: list[str] = []

    def second_runner(node: CertificationNode) -> int:
        second_calls.append(node.node_id)
        return 2

    second = PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )
    result = second.run(nodes, second_runner)

    assert second_calls == ["deep-market-evidence:crypto"]
    assert result.failed_nodes == ()
    assert result.reused_nodes == ("deep-market-evidence:equity",)
    assert set(result.completed_nodes) == {node.node_id for node in nodes}
    assert result.path.exists()


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
    calls: list[str] = []

    def runner(node: CertificationNode) -> int:
        calls.append(node.node_id)
        if node.node_id == root.node_id:
            raise RuntimeError("root unavailable")
        return 1

    first = PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )
    with pytest.raises(CertificationSchedulerError):
        first.run((root, dependent, independent), runner)

    assert root.node_id in calls
    assert independent.node_id in calls
    assert dependent.node_id not in calls

    second_calls: list[str] = []

    def second_runner(node: CertificationNode) -> int:
        second_calls.append(node.node_id)
        return 1

    second = PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )
    result = second.run((root, dependent, independent), second_runner)
    assert independent.node_id not in second_calls
    assert result.reused_nodes == (independent.node_id,)
    assert set(result.completed_nodes) == {root.node_id, dependent.node_id, independent.node_id}


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
