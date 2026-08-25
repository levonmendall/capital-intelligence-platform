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
        file_kib=inactive + 16,
        kernel_kib=20_000,
        source="cgroup_v2_configured_ceiling",
        active_file_kib=16,
    )


def _boundaries() -> guard.MemoryBoundaries:
    return guard.memory_boundaries(
        2 * 1024 * 1024,
        working_set_fraction=0.70,
        working_set_reserve_kib=640 * 1024,
        values={"RENDER": "true"},
    )


def test_serialization_reclaims_inactive_file_cache_before_legacy_margin(
    monkeypatch,
) -> None:
    actual = _boundaries()
    before = _snapshot(
        raw=actual.raw_hard_kib - 200 * 1024,
        working=700_000,
        inactive=1_100_000,
    )
    after = _snapshot(
        raw=actual.raw_hard_kib - 320 * 1024,
        working=700_000,
        inactive=980_000,
    )
    monkeypatch.setattr(worker._memory_guard, "memory_snapshot", lambda _values: before)
    calls: list[guard.MemoryBoundaries] = []

    def fake_attempt(snapshot, boundaries, *, values):
        del snapshot, values
        calls.append(boundaries)
        return (
            MemoryReclaimResult(
                attempted=True,
                supported=True,
                requested_kib=120 * 1024,
                raw_before_kib=before.raw_current_kib,
                raw_after_kib=after.raw_current_kib,
                working_set_before_kib=before.working_set_kib,
                working_set_after_kib=after.working_set_kib,
                reclaimed_kib=120 * 1024,
                effective=True,
                error_type=None,
            ),
            after,
        )

    monkeypatch.setattr(worker._memory_guard, "_attempt_cgroup_v2_reclaim", fake_attempt)
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        worker._memory_guard,
        "_safe_log",
        lambda event, **details: events.append((event, details)),
    )

    result = worker._reclaim_catalog_lane_cgroup_cache(
        {"RENDER": "true"}, phase="during_persist"
    )

    assert result is not None and result.attempted is True
    assert len(calls) == 1
    proactive = calls[0]
    assert proactive.working_set_kib == actual.working_set_kib
    assert proactive.raw_hard_kib == (
        actual.raw_hard_kib - worker._CATALOG_FILE_CACHE_RECLAIM_HEADROOM_KIB
    )
    assert proactive.raw_hard_kib < (
        actual.raw_hard_kib - worker._CATALOG_HANDOFF_RECLAIM_MARGIN_KIB
    )
    assert guard._raw_reclaim_request_kib(before, proactive) <= guard._RECLAIM_MAX_KIB
    assert actual.working_set_kib == (2 * 1024 * 1024) - (640 * 1024)
    assert actual.raw_hard_kib == int((2 * 1024 * 1024) * 0.90)
    event, details = events[-1]
    assert event == "catalog_lane_reclaim_checkpoint"
    assert details["catalog_reclaim_trigger"] == "inactive_file_serialization_pressure"
    assert details["raw_hard_boundary_kib"] == actual.raw_hard_kib


def test_serialization_does_not_reclaim_early_without_substantial_inactive_file(
    monkeypatch,
) -> None:
    actual = _boundaries()
    before = _snapshot(
        raw=actual.raw_hard_kib - 200 * 1024,
        working=700_000,
        inactive=worker._CATALOG_FILE_CACHE_MIN_INACTIVE_KIB - 1,
    )
    monkeypatch.setattr(worker._memory_guard, "memory_snapshot", lambda _values: before)
    monkeypatch.setattr(
        worker._memory_guard,
        "_attempt_cgroup_v2_reclaim",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected reclaim")),
    )

    assert (
        worker._reclaim_catalog_lane_cgroup_cache(
            {"RENDER": "true"}, phase="during_persist"
        )
        is None
    )


def test_early_inactive_file_trigger_is_scoped_to_serialization_checkpoints(
    monkeypatch,
) -> None:
    actual = _boundaries()
    before = _snapshot(
        raw=actual.raw_hard_kib - 200 * 1024,
        working=700_000,
        inactive=1_100_000,
    )
    monkeypatch.setattr(worker._memory_guard, "memory_snapshot", lambda _values: before)
    monkeypatch.setattr(
        worker._memory_guard,
        "_attempt_cgroup_v2_reclaim",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected reclaim")),
    )

    assert (
        worker._reclaim_catalog_lane_cgroup_cache(
            {"RENDER": "true"}, phase="pre_persist"
        )
        is None
    )
    assert worker._CATALOG_HANDOFF_RECLAIM_MARGIN_KIB == 32 * 1024
    assert worker._CATALOG_FILE_CACHE_RECLAIM_HEADROOM_KIB == 256 * 1024
    assert worker._CATALOG_FILE_CACHE_MIN_INACTIVE_KIB == 256 * 1024
    assert guard._RECLAIM_MAX_KIB == 256 * 1024
    assert worker._DEFAULT_MEMORY_HIGH_WATER_FRACTION == 0.70
    assert worker._DEFAULT_MEMORY_RESERVE_MB == 640.0
