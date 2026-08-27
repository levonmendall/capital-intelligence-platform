from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from operations import bounded_comprehensive_discovery_spool as bounded
from operations import comprehensive_discovery_runtime_contract as runtime_contract
from operations import lane_local_comprehensive_discovery_spool as lane_spool
from operations import transactional_comprehensive_discovery_lane as transaction
from operations import transactional_lane_comprehensive_discovery_coordinator as coordinator


def test_transaction_state_uses_existing_integrity_envelope() -> None:
    assert transaction._TRANSACTION_SCHEMA == bounded._STAGE_SCHEMA


def test_transaction_resume_rejects_any_raw_catalog_retention(monkeypatch, tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        transaction._bounded,
        "_load_stage_state",
        lambda *args, **kwargs: {
            "schema_version": transaction._TRANSACTION_SCHEMA,
            "transactional_lane_compaction": True,
            "raw_catalog_persisted": True,
            "request_id": "request-1",
            "asset_class": "international_equity",
        },
    )

    assert (
        transaction._reusable_transaction_state(
            request,
            request_id="request-1",
            asset_class="international_equity",
            index=4,
        )
        is None
    )


def test_transaction_resume_requires_retained_artifacts_to_verify(monkeypatch, tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    publication = tmp_path / "provider-preselection-004-international_equity.json"
    publication.write_text("{}", encoding="utf-8")
    state = {
        "schema_version": transaction._TRANSACTION_SCHEMA,
        "transactional_lane_compaction": True,
        "raw_catalog_persisted": False,
        "request_id": "request-1",
        "asset_class": "international_equity",
        "blob": {"relative_path": "merged.pkl"},
        "scheduled": True,
        "provider_preselection_path": str(publication),
        "node": {"lane_blob": {"relative_path": "lane.pkl"}},
    }
    verified: list[str] = []
    monkeypatch.setattr(transaction._bounded, "_load_stage_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(
        transaction._legacy,
        "_descriptor",
        lambda value: SimpleNamespace(relative_path=str(value["relative_path"])),
    )
    monkeypatch.setattr(
        transaction._legacy,
        "_verify_blob",
        lambda directory, descriptor: verified.append(descriptor.relative_path),
    )

    loaded = transaction._reusable_transaction_state(
        request,
        request_id="request-1",
        asset_class="international_equity",
        index=4,
    )

    assert loaded is state
    assert verified == ["merged.pkl", "lane.pkl"]


def test_parent_reclaims_only_after_transaction_child_exit_and_before_completion(monkeypatch, tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    events: list[str] = []

    monkeypatch.setattr(
        coordinator,
        "_record_transaction_start",
        lambda *args, **kwargs: events.append("start"),
    )

    class Process:
        def wait(self, timeout=None) -> int:
            events.append("child_exit")
            return 0

    monkeypatch.setattr(coordinator.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(coordinator, "_process_tree_alive", lambda _process: False)
    monkeypatch.setattr(
        coordinator._bounded,
        "_load_stage_state",
        lambda *args, **kwargs: (
            events.append("state_loaded")
            or {
                "schema_version": transaction._TRANSACTION_SCHEMA,
                "transactional_lane_compaction": True,
                "raw_catalog_persisted": False,
                "asset_class": "international_equity",
                "raw_record_count": 10,
                "record_count": 12,
                "peak_rss_bytes": 100,
            }
        ),
    )
    monkeypatch.setattr(
        coordinator,
        "run_post_lane_cache_reclamation",
        lambda *args, **kwargs: events.append("reclaimed"),
    )
    monkeypatch.setattr(
        coordinator,
        "_publish_transaction_completion",
        lambda **kwargs: events.append("completion_published"),
    )

    state = coordinator._run_lane_transaction(
        request,
        {"RENDER": "true", "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS": "1"},
        asset_class="international_equity",
        index=4,
        decision_epoch=datetime.now(timezone.utc),
    )

    assert state["raw_catalog_persisted"] is False
    assert events == [
        "start",
        "child_exit",
        "state_loaded",
        "reclaimed",
        "completion_published",
    ]


def test_post_transaction_reclamation_failure_cannot_change_durable_lane(monkeypatch, tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    published: list[bool] = []

    class Process:
        def wait(self, timeout=None) -> int:
            return 0

    monkeypatch.setattr(coordinator, "_record_transaction_start", lambda *args, **kwargs: None)
    monkeypatch.setattr(coordinator.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(coordinator, "_process_tree_alive", lambda _process: False)
    monkeypatch.setattr(
        coordinator._bounded,
        "_load_stage_state",
        lambda *args, **kwargs: {
            "schema_version": transaction._TRANSACTION_SCHEMA,
            "transactional_lane_compaction": True,
            "raw_catalog_persisted": False,
            "asset_class": "fx",
            "raw_record_count": 1,
            "record_count": 1,
            "peak_rss_bytes": 1,
        },
    )
    monkeypatch.setattr(
        coordinator,
        "run_post_lane_cache_reclamation",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("advisory")),
    )
    monkeypatch.setattr(
        coordinator,
        "_publish_transaction_completion",
        lambda **kwargs: published.append(True),
    )

    state = coordinator._run_lane_transaction(
        request,
        {},
        asset_class="fx",
        index=1,
        decision_epoch=datetime.now(timezone.utc),
    )

    assert state["transactional_lane_compaction"] is True
    assert published == [True]


def test_runtime_installs_transactional_coordinator_last(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        lane_spool,
        "install_lane_local_comprehensive_discovery_spool",
        lambda: calls.append("lane_spool"),
    )
    monkeypatch.setattr(
        coordinator,
        "install_transactional_lane_comprehensive_discovery_coordinator",
        lambda: calls.append("transactional_coordinator"),
    )

    runtime_contract._install_lane_local_spool()

    assert calls == ["lane_spool", "transactional_coordinator"]


def test_spool_builder_no_longer_runs_three_separate_lane_stages() -> None:
    source = inspect.getsource(coordinator.build_spool)
    assert "_run_lane_transaction(" in source
    assert '"catalog-lane"' not in source
    assert '"publication-lane"' not in source
    assert '"screening-lane"' not in source

    transaction_source = inspect.getsource(transaction.run_lane_transaction)
    assert "_load_catalog_records(" in transaction_source
    assert "_bounded_lane._merge_certified_lane(" in transaction_source
    assert "_build_deep_lane(" in transaction_source
    assert "raw_catalog_persisted\": False" in transaction_source
    assert "_raw_catalog_path(" not in transaction_source
