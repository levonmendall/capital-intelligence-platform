from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from operations import comprehensive_discovery_memory_attribution as attribution
from operations import reclaimable_memory_guard as memory_guard


def test_cgroup_v2_stat_metrics_are_projected_in_kib(monkeypatch):
    payload = {
        "anon": 10 * 1024,
        "file": 20 * 1024,
        "shmem": 3 * 1024,
        "file_mapped": 4 * 1024,
        "file_dirty": 5 * 1024,
        "file_writeback": 6 * 1024,
        "inactive_file": 7 * 1024,
        "active_file": 8 * 1024,
        "kernel": 9 * 1024,
        "sock": 2 * 1024,
        "pagetables": 11 * 1024,
        "slab_reclaimable": 12 * 1024,
        "slab_unreclaimable": 13 * 1024,
    }
    monkeypatch.setattr(memory_guard, "_read_key_values", lambda path: payload)

    metrics = attribution._cgroup_stat_metrics()

    assert metrics["memory_cgroup_anon_kib"] == 10
    assert metrics["memory_cgroup_file_kib"] == 20
    assert metrics["memory_cgroup_file_mapped_kib"] == 4
    assert metrics["memory_cgroup_file_dirty_kib"] == 5
    assert metrics["memory_cgroup_file_writeback_kib"] == 6
    assert metrics["memory_cgroup_inactive_file_kib"] == 7
    assert metrics["memory_cgroup_active_file_kib"] == 8
    assert metrics["memory_cgroup_shmem_kib"] == 3
    assert metrics["memory_cgroup_kernel_kib"] == 9


def test_data_store_metrics_attribute_bounded_stat_only_footprints(tmp_path):
    historical = tmp_path / "historical_evidence"
    historical.mkdir()
    (historical / "market_history.sqlite3").write_bytes(b"x" * 2048)
    (historical / "market_history.sqlite3-wal").write_bytes(b"x" * 1024)
    (historical / "market_history.sqlite3-shm").write_bytes(b"x" * 4096)

    spool = tmp_path / "comprehensive-discovery-spool"
    spool.mkdir()
    (spool / "lane.pkl").write_bytes(b"x" * 3072)

    reference = tmp_path / "reference_readiness"
    reference.mkdir()
    (reference / "asset.json").write_bytes(b"x" * 5120)

    continuous = tmp_path / "continuous_evidence_plane"
    continuous.mkdir()
    (continuous / "blob.json").write_bytes(b"x" * 6144)

    other = tmp_path / "other_store"
    other.mkdir()
    (other / "other.bin").write_bytes(b"x" * 7168)

    metrics = attribution._bounded_data_store_metrics(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    )

    assert metrics["memory_store_historical_kib"] == 7
    assert metrics["memory_store_historical_sqlite_kib"] == 2
    assert metrics["memory_store_historical_wal_kib"] == 1
    assert metrics["memory_store_historical_shm_kib"] == 4
    assert metrics["memory_store_discovery_spool_kib"] == 3
    assert metrics["memory_store_reference_kib"] == 5
    assert metrics["memory_store_continuous_evidence_kib"] == 6
    assert metrics["memory_store_other_kib"] == 7
    assert metrics["memory_store_data_total_kib"] == 28
    assert metrics["memory_store_data_file_count"] == 7
    assert metrics["memory_store_scan_truncated"] == 0


def test_safe_attribution_metrics_drop_unknown_negative_and_boolean_values():
    metrics = attribution.safe_persisted_attribution_metrics(
        {
            "memory_cgroup_file_kib": 123,
            "memory_store_reference_kib": 456,
            "memory_store_scan_truncated": False,
            "memory_raw_current_kib": -1,
            "secret_path": 999,
        }
    )

    assert metrics == {
        "memory_cgroup_file_kib": 123,
        "memory_store_reference_kib": 456,
    }


def test_capture_memory_attribution_merges_snapshot_cgroup_and_store_metrics(monkeypatch):
    monkeypatch.setattr(
        memory_guard,
        "memory_snapshot",
        lambda values: SimpleNamespace(
            raw_current_kib=2000,
            working_set_kib=600,
            anon_kib=500,
            file_kib=1400,
            inactive_file_kib=1300,
            active_file_kib=100,
            kernel_kib=50,
            source="cgroup_v2",
        ),
    )
    monkeypatch.setattr(
        attribution,
        "_cgroup_stat_metrics",
        lambda: {
            "memory_cgroup_file_kib": 1400,
            "memory_cgroup_file_mapped_kib": 25,
            "memory_cgroup_file_dirty_kib": 4,
        },
    )
    monkeypatch.setattr(
        attribution,
        "_bounded_data_store_metrics",
        lambda values: {"memory_store_historical_sqlite_kib": 900},
    )
    events = []
    monkeypatch.setattr(memory_guard, "_safe_log", lambda event, **details: events.append((event, details)))

    metrics = attribution.capture_memory_attribution(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/data"},
        phase="terminal_resource_failure_context",
        stage="comprehensive_discovery",
        asset_class="international_equity",
        lane_index=4,
    )

    assert metrics["memory_raw_current_kib"] == 2000
    assert metrics["memory_working_set_current_kib"] == 600
    assert metrics["memory_cgroup_file_kib"] == 1400
    assert metrics["memory_cgroup_file_mapped_kib"] == 25
    assert metrics["memory_cgroup_file_unmapped_kib"] == 1375
    assert metrics["memory_store_historical_sqlite_kib"] == 900
    assert events[0][0] == "cgroup_file_memory_attribution"
    assert events[0][1]["decision_authority"] is False
    assert events[0][1]["real_money_authorized"] is False


def test_capture_memory_attribution_is_fail_soft(monkeypatch):
    monkeypatch.setattr(
        memory_guard,
        "memory_snapshot",
        lambda values: (_ for _ in ()).throw(OSError("unavailable")),
    )
    monkeypatch.setattr(memory_guard, "_safe_log", lambda *args, **kwargs: None)

    assert (
        attribution.capture_memory_attribution(
            {}, phase="test", stage="comprehensive_discovery"
        )
        == {}
    )


def test_terminal_failure_context_adds_live_attribution_to_validated_progress(monkeypatch):
    from operations import lane_local_watchdog_progress as watchdog

    observed = SimpleNamespace(
        component="bounded-catalog-lane-complete:international_equity",
        updated_at=datetime(2026, 8, 25, 4, 32, tzinfo=timezone.utc),
        metrics={
            "candidate_lanes": 13,
            "completed_catalog_lanes": 5,
            "catalog_records": 34245,
            "unsafe_metric": 999,
        },
    )
    monkeypatch.setattr(
        watchdog,
        "lane_local_bounded_discovery_progress",
        lambda values, boundary: observed,
    )
    monkeypatch.setattr(
        attribution,
        "capture_memory_attribution",
        lambda *args, **kwargs: {
            "memory_cgroup_file_kib": 1380,
            "memory_store_historical_sqlite_kib": 900,
        },
    )

    context = attribution.lane_local_memory_failure_context(
        {}, boundary=datetime(2026, 8, 25, 4, 0, tzinfo=timezone.utc)
    )

    assert context is not None
    assert context["component"] == "bounded-catalog-lane-complete:international_equity"
    assert context["metrics"]["completed_catalog_lanes"] == 5
    assert context["metrics"]["memory_cgroup_file_kib"] == 1380
    assert context["metrics"]["memory_store_historical_sqlite_kib"] == 900
    assert "unsafe_metric" not in context["metrics"]
    assert context["decision_authority"] is False
    assert context["real_money_authorized"] is False
