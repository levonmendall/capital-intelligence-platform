from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import time
from types import SimpleNamespace

import pytest

from operations import component_qualified_evidence_maintenance as maintenance
from operations import dag_native_comprehensive_supervision as dag_native
from operations import persistent_certification_scheduler as scheduler


@dataclass(frozen=True, slots=True)
class _TimedRunner:
    slow_node_id: str | None = None
    delay_seconds: float = 0.0
    evidence_count: int = 2

    def __call__(self, node: scheduler.CertificationNode) -> int:
        if self.slow_node_id and node.node_id == self.slow_node_id:
            time.sleep(self.delay_seconds)
        return self.evidence_count


@dataclass(frozen=True, slots=True)
class _SingleNodeRunner:
    evidence_count: int = 1

    def __call__(self, _node: scheduler.CertificationNode) -> int:
        return self.evidence_count


def _node(name: str, *, provider: str, epoch: datetime) -> scheduler.CertificationNode:
    return scheduler.CertificationNode(
        node_id=f"deep-market-evidence:{name}",
        asset_class=name,
        provider_groups=(provider,),
        input_fingerprint=f"fingerprint-{name}",
        deadline=epoch + timedelta(minutes=15),
        decision_eligible_count=2,
    )


def _values(tmp_path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING": "true",
        "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS": "2",
        "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_NODE_TIMEOUT_SECONDS": "0.08",
    }


def _runtime_journal_path(tmp_path, epoch: datetime):
    return (
        tmp_path
        / "certification-dag"
        / scheduler._SCHEMA_VERSION
        / "release-test"
        / scheduler._epoch_key(epoch)
        / "runtime-latest.json"
    )


def test_lane_timeout_does_not_discard_independent_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    epoch = datetime(2026, 8, 18, 17, 45, tzinfo=timezone.utc)
    values = _values(tmp_path)
    fast = _node("equity", provider="eodhd", epoch=epoch)
    slow = _node("crypto", provider="coinbase", epoch=epoch)

    # The production installer intentionally replaces these runtime seams. Register their
    # original values with monkeypatch first so this process-isolation test cannot alter
    # unrelated scheduler tests.
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
    dag_native.install_dag_native_comprehensive_supervision()

    first = scheduler.PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )
    started = time.monotonic()
    with pytest.raises(
        scheduler.CertificationSchedulerError,
        match="deep-market-evidence:crypto:SupervisedComponentTimeout",
    ):
        first.run(
            (fast, slow),
            _TimedRunner(
                slow_node_id=slow.node_id,
                delay_seconds=4.0,
                evidence_count=2,
            ),
        )
    assert time.monotonic() - started < 3.0

    runtime = json.loads(_runtime_journal_path(tmp_path, epoch).read_text(encoding="utf-8"))
    assert runtime["node_states"][fast.node_id]["state"] == "qualified"
    assert runtime["node_states"][slow.node_id]["state"] == "failed"
    assert runtime["node_states"][slow.node_id]["failure_type"] == "SupervisedComponentTimeout"
    assert runtime["counts"]["completed_nodes"] == 1
    assert runtime["counts"]["failed_nodes"] == 1

    second = scheduler.PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )
    result = second.run((fast, slow), _SingleNodeRunner())

    assert result.failed_nodes == ()
    assert result.reused_nodes == (fast.node_id,)
    assert set(result.completed_nodes) == {fast.node_id, slow.node_id}


def test_unpicklable_lane_runner_fails_in_parent_with_exact_node(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    epoch = datetime(2026, 8, 18, 17, 47, tzinfo=timezone.utc)
    values = _values(tmp_path)
    node = _node("equity", provider="eodhd", epoch=epoch)

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
    dag_native.install_dag_native_comprehensive_supervision()

    runner = lambda _node: 1  # noqa: E731 - intentionally unpicklable local callable.
    instance = scheduler.PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )
    with pytest.raises(
        scheduler.CertificationSchedulerError,
        match="deep-market-evidence:equity:SpawnSerializationError",
    ):
        instance.run((node,), runner)

    runtime = json.loads(_runtime_journal_path(tmp_path, epoch).read_text(encoding="utf-8"))
    assert runtime["node_states"][node.node_id]["state"] == "failed"
    assert runtime["node_states"][node.node_id]["failure_type"] == "SpawnSerializationError"


def test_discovery_coordinator_does_not_use_aggregate_supervisor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    cutoff = datetime(2026, 8, 18, 17, 50, tzinfo=timezone.utc)
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
    }
    calls: list[datetime] = []

    monkeypatch.setattr(
        maintenance,
        "_supervised_discovery_runner",
        maintenance._supervised_discovery_runner,
    )

    def component_factory(_values):
        def run(timestamp: datetime):
            calls.append(timestamp)
            return object()

        return run

    monkeypatch.setattr(maintenance, "_component_discovery_runner", component_factory)
    monkeypatch.setattr(
        maintenance,
        "_run_supervised",
        lambda *_args, **_kwargs: pytest.fail(
            "aggregate comprehensive-discovery supervisor must not run"
        ),
    )
    monkeypatch.setattr(
        maintenance,
        "load_qualified_comprehensive_discovery_snapshot",
        lambda *, evidence_as_of, values: SimpleNamespace(
            result=(evidence_as_of, values["CAPITAL_INTELLIGENCE_RELEASE"])
        ),
    )

    dag_native._install_discovery_coordinator()
    runner = maintenance._supervised_discovery_runner(values)
    assert runner(cutoff) == (cutoff, "release-test")
    assert calls == [cutoff]


def test_node_timeout_configuration_remains_bounded(tmp_path) -> None:
    values = _values(tmp_path)
    assert dag_native._node_timeout_seconds(values) == pytest.approx(0.08)

    values["CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_NODE_TIMEOUT_SECONDS"] = "0"
    with pytest.raises(ValueError, match="must be positive"):
        dag_native._node_timeout_seconds(values)

    values["CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_NODE_TIMEOUT_SECONDS"] = "3601"
    with pytest.raises(ValueError, match="no more than 3600"):
        dag_native._node_timeout_seconds(values)
