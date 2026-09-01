from __future__ import annotations

import run_bounded_manual_cio_diagnostic as bounded_watchdog
from operations import reclaimable_memory_guard as guard
from operations.reclaimable_memory_guard import MemoryBoundaries, MemorySnapshot
from operations.working_set_file_cache_reclamation import (
    should_reclaim_file_backed_working_set,
)


def _snapshot(*, working_set_kib: int, active_file_kib: int | None) -> MemorySnapshot:
    return MemorySnapshot(
        raw_current_kib=1_670_436,
        limit_kib=2_097_152,
        working_set_kib=working_set_kib,
        inactive_file_kib=210_808,
        anon_kib=900_000,
        file_kib=650_000,
        kernel_kib=80_000,
        source="cgroup_v2_configured_ceiling",
        memory_events=(),
        active_file_kib=active_file_kib,
    )


def test_small_working_set_crossing_is_reclaimable_when_active_file_explains_it():
    boundaries = MemoryBoundaries(
        working_set_kib=1_441_792,
        raw_hard_kib=1_887_436,
    )

    assert should_reclaim_file_backed_working_set(
        _snapshot(working_set_kib=1_459_628, active_file_kib=120_000),
        boundaries,
    )


def test_post_888_production_sized_crossing_does_not_require_extra_32mib_cushion():
    boundaries = MemoryBoundaries(
        working_set_kib=1_441_792,
        raw_hard_kib=1_887_436,
    )

    # Production crossed by only 2,824 KiB. Active-file ownership need only explain that
    # crossing; the caller remeasures the unchanged boundary after one bounded clean-file
    # pass. The former extra 32 MiB classifier cushion incorrectly suppressed this attempt.
    assert should_reclaim_file_backed_working_set(
        _snapshot(working_set_kib=1_444_616, active_file_kib=8_192),
        boundaries,
    )


def test_true_non_file_working_set_pressure_remains_fail_closed():
    boundaries = MemoryBoundaries(
        working_set_kib=1_441_792,
        raw_hard_kib=1_887_436,
    )

    # Active-file ownership is smaller than the observed crossing, so the conservative
    # non-file remainder itself is still at/above the governed boundary.
    assert not should_reclaim_file_backed_working_set(
        _snapshot(working_set_kib=1_459_628, active_file_kib=2_000),
        boundaries,
    )


def test_missing_active_file_accounting_never_enables_reclamation():
    boundaries = MemoryBoundaries(
        working_set_kib=1_441_792,
        raw_hard_kib=1_887_436,
    )

    assert not should_reclaim_file_backed_working_set(
        _snapshot(working_set_kib=1_459_628, active_file_kib=None),
        boundaries,
    )


def test_below_boundary_never_reclaims_even_with_large_active_file_cache():
    boundaries = MemoryBoundaries(
        working_set_kib=1_441_792,
        raw_hard_kib=1_887_436,
    )

    assert not should_reclaim_file_backed_working_set(
        _snapshot(working_set_kib=1_400_000, active_file_kib=500_000),
        boundaries,
    )


def test_production_wait_reclaims_file_backed_crossing_before_guard_decision(monkeypatch):
    before = _snapshot(working_set_kib=1_444_616, active_file_kib=8_192)
    after = _snapshot(working_set_kib=1_439_000, active_file_kib=2_500)
    snapshots = iter((before, after))
    released: list[dict[str, str]] = []
    observed: list[MemorySnapshot] = []

    monkeypatch.setattr(guard, "memory_snapshot", lambda values=None: next(snapshots))

    def fake_guard_wait(process, **kwargs):
        del process
        observed.append(guard.memory_snapshot(kwargs.get("values")))
        return (0, False, False, 60_840, 1_637_864)

    monkeypatch.setattr(guard, "wait_with_reclaimable_resource_bounds", fake_guard_wait)
    wait = bounded_watchdog._wait_with_resource_bounds
    monkeypatch.setitem(
        wait.__globals__,
        "release_streaming_clean_file_cache",
        lambda values: released.append(dict(values))
        or {
            "supported": True,
            "scan_entries": 10,
            "released_file_count": 2,
            "released_bytes": 8 * 1024 * 1024,
        },
    )

    result = wait(
        object(),
        timeout_seconds=30.0,
        memory_high_water_fraction=0.70,
        values={"RENDER": "true"},
        memory_reserve_kib=640 * 1024,
        poll_seconds=0.1,
    )

    assert result == (0, False, False, 60_840, 1_637_864)
    assert released == [{"RENDER": "true"}]
    assert observed == [after]


def test_production_wait_does_not_reclaim_true_non_file_pressure(monkeypatch):
    before = _snapshot(working_set_kib=1_459_628, active_file_kib=2_000)
    released: list[dict[str, str]] = []
    observed: list[MemorySnapshot] = []

    monkeypatch.setattr(guard, "memory_snapshot", lambda values=None: before)

    def fake_guard_wait(process, **kwargs):
        del process
        observed.append(guard.memory_snapshot(kwargs.get("values")))
        return (None, False, True, 60_684, 1_670_436)

    monkeypatch.setattr(guard, "wait_with_reclaimable_resource_bounds", fake_guard_wait)
    wait = bounded_watchdog._wait_with_resource_bounds
    monkeypatch.setitem(
        wait.__globals__,
        "release_streaming_clean_file_cache",
        lambda values: released.append(dict(values)) or {"supported": True},
    )

    result = wait(
        object(),
        timeout_seconds=30.0,
        memory_high_water_fraction=0.70,
        values={"RENDER": "true"},
        memory_reserve_kib=640 * 1024,
        poll_seconds=0.1,
    )

    assert result == (None, False, True, 60_684, 1_670_436)
    assert released == []
    assert observed == [before]
