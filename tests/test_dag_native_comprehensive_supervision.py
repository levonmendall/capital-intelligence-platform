from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
from types import SimpleNamespace

import pytest

from operations import component_qualified_evidence_maintenance as maintenance
from operations import dag_native_comprehensive_supervision as dag_native
from operations import persistent_certification_scheduler as scheduler


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
    # unrelated scheduler tests that still use parent-memory call counters.
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

    def first_runner(node: scheduler.CertificationNode) -> int:
        if node.node_id == slow.node_id:
            time.sleep(2.0)
        return node.decision_eligible_count

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
        first.run((fast, slow), first_runner)
    assert time.monotonic() - started < 1.5

    second = scheduler.PersistentCertificationScheduler(
        values=values,
        release_sha="release-test",
        epoch=epoch,
        policy_version="policy-v1",
    )
    result = second.run((fast, slow), lambda _node: 1)

    assert result.failed_nodes == ()
    assert result.reused_nodes == (fast.node_id,)
    assert set(result.completed_nodes) == {fast.node_id, slow.node_id}


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
