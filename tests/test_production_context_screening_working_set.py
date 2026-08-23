from __future__ import annotations

from pathlib import Path

import pytest

from production_context_screening_resource_guard import (
    ScreeningResourceDeferred,
    ensure_screening_headroom,
    screening_resource_snapshot,
)

_MIB = 1024 * 1024


def _write_v2_memory(
    root: Path,
    *,
    current_mib: int,
    limit_mib: int = 2048,
    inactive_file_mib: int | None,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "memory.current").write_text(
        str(current_mib * _MIB),
        encoding="utf-8",
    )
    (root / "memory.max").write_text(
        str(limit_mib * _MIB),
        encoding="utf-8",
    )
    if inactive_file_mib is not None:
        (root / "memory.stat").write_text(
            f"anon {max(1, current_mib - inactive_file_mib) * _MIB}\n"
            f"file {inactive_file_mib * _MIB}\n"
            f"inactive_file {inactive_file_mib * _MIB}\n",
            encoding="utf-8",
        )


def test_reclaimable_page_cache_does_not_false_block_screening(tmp_path: Path) -> None:
    _write_v2_memory(
        tmp_path,
        current_mib=1700,
        inactive_file_mib=900,
    )

    snapshot = ensure_screening_headroom(values={}, root=tmp_path)

    assert snapshot.memory_accounting_source == "cgroup_v2"
    assert snapshot.container_current_bytes == 1700 * _MIB
    assert snapshot.inactive_file_bytes == 900 * _MIB
    assert snapshot.working_set_bytes == 800 * _MIB
    assert snapshot.working_set_boundary_bytes == 1408 * _MIB
    assert snapshot.raw_hard_boundary_bytes is not None
    assert snapshot.container_current_bytes < snapshot.raw_hard_boundary_bytes
    assert snapshot.governed_headroom_bytes == 608 * _MIB
    assert snapshot.governed_headroom_bytes > snapshot.minimum_governed_headroom_bytes


def test_active_working_set_at_governed_boundary_blocks_screening(tmp_path: Path) -> None:
    _write_v2_memory(
        tmp_path,
        current_mib=1500,
        inactive_file_mib=32,
    )

    with pytest.raises(ScreeningResourceDeferred) as captured:
        ensure_screening_headroom(values={}, root=tmp_path)

    snapshot = captured.value.snapshot
    assert snapshot.working_set_boundary_reached is True
    assert snapshot.raw_hard_boundary_reached is False
    assert snapshot.working_set_bytes == 1468 * _MIB


def test_raw_hard_ceiling_blocks_even_when_page_cache_is_reclaimable(tmp_path: Path) -> None:
    _write_v2_memory(
        tmp_path,
        current_mib=1900,
        inactive_file_mib=1000,
    )

    with pytest.raises(ScreeningResourceDeferred) as captured:
        ensure_screening_headroom(values={}, root=tmp_path)

    snapshot = captured.value.snapshot
    assert snapshot.working_set_boundary_reached is False
    assert snapshot.raw_hard_boundary_reached is True
    assert snapshot.working_set_bytes == 900 * _MIB


def test_missing_memory_stat_cannot_manufacture_reclaimable_headroom(tmp_path: Path) -> None:
    _write_v2_memory(
        tmp_path,
        current_mib=1500,
        inactive_file_mib=None,
    )

    snapshot = screening_resource_snapshot(values={}, root=tmp_path)
    assert snapshot.inactive_file_bytes is None
    assert snapshot.working_set_bytes == snapshot.container_current_bytes

    with pytest.raises(ScreeningResourceDeferred):
        ensure_screening_headroom(values={}, root=tmp_path)
