from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from operations import bounded_provider_preselection_publication as publication
from operations import comprehensive_discovery_input_spool as legacy
from operations import transactional_comprehensive_discovery_lane as transaction
from operations import transactional_lane_comprehensive_discovery_coordinator as coordinator


def test_bounded_publication_fails_when_atomic_artifact_does_not_survive_readback(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "provider.json"
    candidate = SimpleNamespace(path=target, catalog_count=1, signal_count=1)
    monkeypatch.setattr(publication, "_records_for_lane", lambda catalogs: (object(),))
    monkeypatch.setattr(publication, "_streaming_catalog_fingerprint", lambda records: "fp")
    monkeypatch.setattr(publication, "_existing_result_bounded", lambda *args, **kwargs: None)

    with pytest.raises(
        publication.ProviderPreselectionPublicationError,
        match="durable exact-path readback verification",
    ):
        publication.verify_provider_preselection_publication(
            {object(): (object(),)},
            publication=candidate,
            as_of=datetime.now(timezone.utc),
            policy=SimpleNamespace(preselection_freshness_days=3),
            expected_path=target,
        )


def test_transaction_resume_refuses_unverified_scheduled_publication(monkeypatch, tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        transaction._bounded,
        "_load_stage_state",
        lambda *args, **kwargs: {
            "schema_version": transaction._TRANSACTION_SCHEMA,
            "transactional_lane_compaction": True,
            "raw_catalog_persisted": False,
            "request_id": "request-1",
            "asset_class": "international_equity",
            "blob": {"relative_path": "merged.pkl"},
            "scheduled": True,
            "provider_preselection_path": str(tmp_path / "provider.json"),
            "provider_publication_verified": False,
        },
    )

    assert transaction._reusable_transaction_state(
        request,
        request_id="request-1",
        asset_class="international_equity",
        index=4,
    ) is None


def test_parent_refuses_lane_completion_without_publication_proof(monkeypatch, tmp_path: Path) -> None:
    class Process:
        pid = 12345
        def wait(self, timeout=None):
            return 0
        def poll(self):
            return 0

    state = {
        "schema_version": transaction._TRANSACTION_SCHEMA,
        "transactional_lane_compaction": True,
        "raw_catalog_persisted": False,
        "asset_class": "international_equity",
        "raw_record_count": 1,
        "record_count": 1,
        "peak_rss_bytes": 1,
        "scheduled": True,
        "provider_preselection_path": str(tmp_path / "missing-provider.json"),
        "provider_publication_verified": False,
    }
    monkeypatch.setattr(coordinator, "_record_transaction_start", lambda *args, **kwargs: None)
    monkeypatch.setattr(coordinator, "_remaining_epoch_seconds", lambda **kwargs: 100.0)
    monkeypatch.setattr(coordinator.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(coordinator, "_process_tree_alive", lambda process: False)
    monkeypatch.setattr(coordinator._bounded, "_load_stage_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(
        coordinator,
        "_publish_transaction_completion",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not publish completion")),
    )

    with pytest.raises(
        legacy.ComprehensiveDiscoverySpoolError,
        match="lacks verified provider publication",
    ):
        coordinator._run_lane_transaction(
            tmp_path / "request.json",
            {},
            asset_class="international_equity",
            index=4,
            decision_epoch=datetime.now(timezone.utc),
        )
