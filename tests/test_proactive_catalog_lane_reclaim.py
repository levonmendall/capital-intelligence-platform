from __future__ import annotations

from operations import bounded_lane_comprehensive_discovery_worker_v2 as worker
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


def test_catalog_reclaim_scope_only_wraps_expected_raw_catalog_pickle(
    monkeypatch,
    tmp_path,
) -> None:
    order: list[str] = []

    monkeypatch.setattr(
        worker,
        "_release_catalog_lane_reference_cache",
        lambda values, *, phase: order.append(f"cache:{phase}") or (),
    )
    monkeypatch.setattr(
        worker,
        "_reclaim_catalog_lane_cgroup_cache",
        lambda values, *, phase="handoff": order.append(f"reclaim:{phase}") or None,
    )

    def fake_write(directory, name, value):
        del directory, value
        order.append(f"write:{name}")
        return object()

    monkeypatch.setattr(worker._legacy, "_write_pickle_blob", fake_write)

    def fake_catalog_stage(request_path, values, *, asset_class_value, index):
        del request_path, values
        worker._legacy._write_pickle_blob(tmp_path, "unrelated.pkl", ())
        worker._legacy._write_pickle_blob(
            tmp_path,
            f"raw-catalog-{index:03d}-{asset_class_value}.pkl",
            ("record",),
        )

    monkeypatch.setattr(worker._lane_local, "_catalog_lane_stage", fake_catalog_stage)

    worker._catalog_lane_stage(
        tmp_path / "request.json",
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
        asset_class_value="international_equity",
        index=4,
    )

    assert order == [
        "write:unrelated.pkl",
        "cache:pre_persist",
        "reclaim:pre_persist",
        "write:raw-catalog-004-international_equity.pkl",
        "reclaim:post_persist",
    ]
    assert worker._legacy._write_pickle_blob is fake_write


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

    result = worker._reclaim_catalog_lane_cgroup_cache(values, phase="pre_persist")

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


def test_reclaim_checkpoint_telemetry_exposes_file_cache_before_and_after(
    monkeypatch,
) -> None:
    actual = guard.memory_boundaries(
        2 * 1024 * 1024,
        working_set_fraction=0.70,
        working_set_reserve_kib=640 * 1024,
        values={"RENDER": "true"},
    )
    before = _snapshot(
        raw=actual.raw_hard_kib - 4 * 1024,
        working=700_000,
        inactive=1_100_000,
    )
    after = _snapshot(
        raw=actual.raw_hard_kib - 100 * 1024,
        working=690_000,
        inactive=1_000_000,
    )
    monkeypatch.setattr(worker._memory_guard, "memory_snapshot", lambda _values: before)
    monkeypatch.setattr(
        worker._memory_guard,
        "_attempt_cgroup_v2_reclaim",
        lambda snapshot, boundaries, *, values: (
            MemoryReclaimResult(
                attempted=True,
                supported=True,
                requested_kib=96 * 1024,
                raw_before_kib=before.raw_current_kib,
                raw_after_kib=after.raw_current_kib,
                working_set_before_kib=before.working_set_kib,
                working_set_after_kib=after.working_set_kib,
                reclaimed_kib=96 * 1024,
                effective=True,
                error_type=None,
            ),
            after,
        ),
    )
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        worker._memory_guard,
        "_safe_log",
        lambda event, **details: events.append((event, details)),
    )

    worker._reclaim_catalog_lane_cgroup_cache({"RENDER": "true"}, phase="pre_persist")

    event, details = events[-1]
    assert event == "catalog_lane_reclaim_checkpoint"
    assert details["catalog_reclaim_phase"] == "pre_persist"
    assert details["memory_reclaim_inactive_file_before_kib"] == before.inactive_file_kib
    assert details["memory_reclaim_inactive_file_after_kib"] == after.inactive_file_kib
    assert details["memory_reclaim_active_file_before_kib"] == before.active_file_kib
    assert details["memory_reclaim_active_file_after_kib"] == after.active_file_kib
    assert details["memory_reclaim_requested_kib"] == 96 * 1024
    assert details["memory_reclaim_delta_kib"] == 96 * 1024


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
