from __future__ import annotations

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


def test_true_non_file_working_set_pressure_remains_fail_closed():
    boundaries = MemoryBoundaries(
        working_set_kib=1_441_792,
        raw_hard_kib=1_887_436,
    )

    assert not should_reclaim_file_backed_working_set(
        _snapshot(working_set_kib=1_459_628, active_file_kib=20_000),
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
