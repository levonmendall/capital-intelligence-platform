from __future__ import annotations

from types import SimpleNamespace

from operations import comprehensive_discovery_runtime_contract as runtime
from operations import persistent_certification_scheduler as scheduler
from operations import post_lane_cache_reclamation as reclamation


def _instance():
    instance = object.__new__(scheduler.PersistentCertificationScheduler)
    instance.values = {
        "RENDER": "true",
        "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS": "1",
    }
    return instance


def test_runtime_reclaims_only_after_durable_success_write(monkeypatch):
    events: list[str] = []

    def durable_write(self, node, *, evidence_complete_count: int):
        del self, node, evidence_complete_count
        events.append("durable_success")
        return "qualified-result"

    def reclaim(values, *, node_id: str, asset_class: str):
        del values, node_id, asset_class
        events.append("reclaim")
        return {"status": "completed"}

    monkeypatch.setattr(
        scheduler.PersistentCertificationScheduler,
        "_write_success",
        durable_write,
    )
    monkeypatch.setattr(reclamation, "run_post_lane_cache_reclamation", reclaim)

    runtime._install_post_lane_cache_reclamation()
    result = scheduler.PersistentCertificationScheduler._write_success(
        _instance(),
        SimpleNamespace(
            node_id="deep-market-evidence:international_equity",
            asset_class="international_equity",
        ),
        evidence_complete_count=11,
    )

    assert result == "qualified-result"
    assert events == ["durable_success", "reclaim"]


def test_runtime_reclamation_failure_cannot_change_qualification(monkeypatch):
    events: list[str] = []

    def durable_write(self, node, *, evidence_complete_count: int):
        del self, node, evidence_complete_count
        events.append("durable_success")
        return "qualified-result"

    def broken_reclaim(values, *, node_id: str, asset_class: str):
        del values, node_id, asset_class
        events.append("reclaim_failed")
        raise RuntimeError("advisory helper unavailable")

    monkeypatch.setattr(
        scheduler.PersistentCertificationScheduler,
        "_write_success",
        durable_write,
    )
    monkeypatch.setattr(reclamation, "run_post_lane_cache_reclamation", broken_reclaim)

    runtime._install_post_lane_cache_reclamation()
    result = scheduler.PersistentCertificationScheduler._write_success(
        _instance(),
        SimpleNamespace(
            node_id="deep-market-evidence:fx",
            asset_class="fx",
        ),
        evidence_complete_count=3,
    )

    assert result == "qualified-result"
    assert events == ["durable_success", "reclaim_failed"]


def test_runtime_install_is_idempotent(monkeypatch):
    calls: list[str] = []

    def durable_write(self, node, *, evidence_complete_count: int):
        del self, node, evidence_complete_count
        return "qualified-result"

    def reclaim(values, *, node_id: str, asset_class: str):
        del values, node_id, asset_class
        calls.append("reclaim")
        return {"status": "completed"}

    monkeypatch.setattr(
        scheduler.PersistentCertificationScheduler,
        "_write_success",
        durable_write,
    )
    monkeypatch.setattr(reclamation, "run_post_lane_cache_reclamation", reclaim)

    runtime._install_post_lane_cache_reclamation()
    runtime._install_post_lane_cache_reclamation()
    result = scheduler.PersistentCertificationScheduler._write_success(
        _instance(),
        SimpleNamespace(
            node_id="deep-market-evidence:crypto",
            asset_class="crypto",
        ),
        evidence_complete_count=5,
    )

    assert result == "qualified-result"
    assert calls == ["reclaim"]
