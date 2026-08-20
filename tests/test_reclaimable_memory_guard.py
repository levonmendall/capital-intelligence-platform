from __future__ import annotations

from operations.reclaimable_memory_guard import (
    MemorySnapshot,
    _working_set_kib,
    limit_reason,
    memory_boundaries,
)


def _snapshot(*, raw: int, inactive: int | None) -> MemorySnapshot:
    return MemorySnapshot(
        raw_current_kib=raw,
        limit_kib=2 * 1024 * 1024,
        working_set_kib=_working_set_kib(raw, inactive),
        inactive_file_kib=inactive,
        anon_kib=None,
        file_kib=None,
        kernel_kib=None,
        source="test",
    )


def _boundaries():
    return memory_boundaries(
        2 * 1024 * 1024,
        working_set_fraction=0.70,
        working_set_reserve_kib=640 * 1024,
        values={"RENDER": "true"},
    )


def test_reclaimable_file_cache_does_not_trip_soft_boundary() -> None:
    boundaries = _boundaries()
    snapshot = _snapshot(raw=1_700_000, inactive=600_000)

    assert snapshot.working_set_kib == 1_100_000
    assert snapshot.raw_current_kib > boundaries.working_set_kib
    assert snapshot.raw_current_kib < boundaries.raw_hard_kib
    assert limit_reason(snapshot, boundaries) is None


def test_nonreclaimable_working_set_still_fails_closed() -> None:
    boundaries = _boundaries()
    snapshot = _snapshot(raw=1_500_000, inactive=20_000)

    assert snapshot.working_set_kib == 1_480_000
    assert limit_reason(snapshot, boundaries) == "working_set"


def test_raw_hard_ceiling_protects_service_even_with_large_page_cache() -> None:
    boundaries = _boundaries()
    snapshot = _snapshot(raw=1_900_000, inactive=800_000)

    assert snapshot.working_set_kib < boundaries.working_set_kib
    assert limit_reason(snapshot, boundaries) == "raw_hard_ceiling"


def test_missing_memory_stat_preserves_conservative_raw_accounting() -> None:
    boundaries = _boundaries()
    snapshot = _snapshot(raw=1_500_000, inactive=None)

    assert snapshot.working_set_kib == snapshot.raw_current_kib
    assert limit_reason(snapshot, boundaries) == "working_set"


def test_default_hard_ceiling_preserves_more_headroom_than_render_limit() -> None:
    limit = 2 * 1024 * 1024
    boundaries = _boundaries()

    assert boundaries.working_set_kib == limit - (640 * 1024)
    assert boundaries.working_set_kib < boundaries.raw_hard_kib < limit
    assert limit - boundaries.raw_hard_kib > 128 * 1024
