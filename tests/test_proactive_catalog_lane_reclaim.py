from __future__ import annotations

from operations import bounded_lane_comprehensive_discovery_worker_v2 as worker
from operations import comprehensive_market_discovery as facade
from operations import reclaimable_memory_guard as guard
from operations.reclaimable_memory_guard import MemoryReclaimResult, MemorySnapshot


def _snapshot(*, raw: int, working: int, inactive: int) -> MemorySnapshot:
    return MemorySnapshot(
        raw_current_kib=raw,
        limit_kib=2 * 1024 * 1024,
        working_set_kib=working,
        inactive_file_kib=inactive,
        anon_kib=500_000,
        file_kib=inactive + 50_000,
        kernel_kib=20_000,
        source="cgroup_v2_configured_ceiling",
        active_file_kib=50_000,
    )


def test_catalog_completion_orders_durable_state_cache_release_reclaim_then_progress(
    monkeypatch,
    tmp_path,
) -> None:
    order: list[str] = []

    def final_progress(stage: str, *args, **kwargs):
        del args, kwargs
        order.append(f"progress:{stage}")

    monkeypatch.setattr(
        facade._core,
        "record_manual_cio_diagnostic_progress",
        final_progress,
    )
    monkeypatch.setattr(
        worker,
        "release_current_reference_file_cache",
        lambda values: order.append("cache") or (),
    )
    monkeypatch.setattr(
        worker,
        "_reclaim_catalog_lane_cgroup_cache",
        lambda values: order.append("reclaim") or None,
    )

    def fake_catalog_stage(request_path, values, *, asset_class_value, index):
        del request_path, values, index
        order.append("state:persisted")
        facade._core.record_manual_cio_diagnostic_progress(
            f"bounded_spool_catalog_lane_complete:{asset_class_value}",
            metrics={"catalog_records": 1},
        )

    monkeypatch.setattr(worker._lane_local, "_catalog_lane_stage", fake_catalog_stage)

    worker._catalog_lane_stage(
        tmp_path / "request.json",
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
        asset_class_value="international_equity",
        index=4,
    )

    assert order == [
        "state:persisted",
        "cache",
        "reclaim",
        "progress:bounded_spool_catalog_lane_complete:international_equity",
    ]
    assert facade._core.record_manual_cio_diagnostic_progress is final_progress


def test_handoff_reclaim_uses_existing_boundaries_and_bounded_guard_attempt(
    monkeypatch,
) -> None:
    limit = 2 * 1024 * 1024
    actual = guard.memory_boundaries(
        limit,
        working_set_fraction=0.70,
        working_set_reserve_kib=640 * 1024,
        values={"RENDER": "true"},
    )
    before = _snapshot(
        raw=actual.raw_hard_kib - 8 * 1024,
        working=700_000,
        inactive=1_100_000,
    )
    after = _snapshot(
        raw=actual.raw_hard_kib - 96 * 1024,
        working=700_000,
        inactive=1_020_000,
    )
    monkeypatch.setattr(worker._memory_guard, "memory_snapshot", lambda _values: before)
    calls: list[tuple[MemorySnapshot, guard.MemoryBoundaries, dict[str, str]]] = []

    def fake_attempt(snapshot, boundaries, *, values):
        calls.append((snapshot, boundaries, dict(values)))
        return (
            MemoryReclaimResult(
                attempted=True,
                supported=True,
                requested_kib=64 * 1024,
                raw_before_kib=before.raw_current_kib,
                raw_after_kib=after.raw_current_kib,
                working_set_before_kib=before.working_set_kib,
                working_set_after_kib=after.working_set_kib,
                reclaimed_kib=88 * 1024,
                effective=True,
                error_type=None,
            ),
            after,
        )

    monkeypatch.setattr(worker._memory_guard, "_attempt_cgroup_v2_reclaim", fake_attempt)
    monkeypatch.setattr(worker._memory_guard, "_safe_log", lambda *args, **kwargs: None)
    values = {"RENDER": "true"}
    original = dict(values)

    result = worker._reclaim_catalog_lane_cgroup_cache(values)

    assert result is not None and result.attempted is True
    assert len(calls) == 1
    _snapshot_arg, proactive, passed_values = calls[0]
    assert proactive.working_set_kib == actual.working_set_kib
    assert proactive.raw_hard_kib == (
        actual.raw_hard_kib - worker._CATALOG_HANDOFF_RECLAIM_MARGIN_KIB
    )
    assert guard._raw_reclaim_request_kib(before, proactive) <= 256 * 1024
    assert actual.working_set_kib == limit - (640 * 1024)
    assert actual.raw_hard_kib == int(limit * 0.90)
    assert passed_values == original
    assert values == original


def test_handoff_reclaim_is_fail_soft(monkeypatch) -> None:
    actual = guard.memory_boundaries(
        2 * 1024 * 1024,
        working_set_fraction=0.70,
        working_set_reserve_kib=640 * 1024,
        values={"RENDER": "true"},
    )
    before = _snapshot(
        raw=actual.raw_hard_kib,
        working=700_000,
        inactive=1_100_000,
    )
    monkeypatch.setattr(worker._memory_guard, "memory_snapshot", lambda _values: before)
    monkeypatch.setattr(
        worker._memory_guard,
        "_attempt_cgroup_v2_reclaim",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("reclaim unavailable")),
    )
    monkeypatch.setattr(worker._memory_guard, "_safe_log", lambda *args, **kwargs: None)

    assert worker._reclaim_catalog_lane_cgroup_cache({"RENDER": "true"}) is None


def test_handoff_reclaim_does_not_run_below_preemptive_margin(monkeypatch) -> None:
    actual = guard.memory_boundaries(
        2 * 1024 * 1024,
        working_set_fraction=0.70,
        working_set_reserve_kib=640 * 1024,
        values={"RENDER": "true"},
    )
    before = _snapshot(
        raw=actual.raw_hard_kib - worker._CATALOG_HANDOFF_RECLAIM_MARGIN_KIB - 1,
        working=700_000,
        inactive=1_100_000,
    )
    monkeypatch.setattr(worker._memory_guard, "memory_snapshot", lambda _values: before)
    monkeypatch.setattr(
        worker._memory_guard,
        "_attempt_cgroup_v2_reclaim",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected reclaim")),
    )

    assert worker._reclaim_catalog_lane_cgroup_cache({"RENDER": "true"}) is None


def test_handoff_reclaim_never_masks_working_set_pressure(monkeypatch) -> None:
    actual = guard.memory_boundaries(
        2 * 1024 * 1024,
        working_set_fraction=0.70,
        working_set_reserve_kib=640 * 1024,
        values={"RENDER": "true"},
    )
    before = _snapshot(
        raw=actual.raw_hard_kib,
        working=actual.working_set_kib,
        inactive=500_000,
    )
    monkeypatch.setattr(worker._memory_guard, "memory_snapshot", lambda _values: before)
    monkeypatch.setattr(
        worker._memory_guard,
        "_attempt_cgroup_v2_reclaim",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected reclaim")),
    )

    assert worker._reclaim_catalog_lane_cgroup_cache({"RENDER": "true"}) is None
