from __future__ import annotations

from pathlib import Path

import pytest

import production_context_publication_runtime as runtime
import production_context_screening_resource_guard as resource_guard
from production_context_screening_resource_guard import (
    SCREENING_RECLAIM_MAX_ATTEMPTS,
    SCREENING_RECLAIM_MAX_BYTES_PER_ATTEMPT,
    ScreeningResourceDeferred,
    ensure_screening_headroom,
    screening_resource_snapshot,
)


def _write_cgroup(root: Path, *, current: int, maximum: int | str) -> None:
    (root / "memory.current").write_text(str(current), encoding="utf-8")
    (root / "memory.max").write_text(str(maximum), encoding="utf-8")


def test_observed_production_boundary_fails_closed_with_stable_reason(tmp_path: Path) -> None:
    # Mirrors a failed production diagnostic: 2 GiB limit, ~1.35 GiB current,
    # 640 MiB governed reserve leaves only ~25 MiB for the screening handoff.
    _write_cgroup(
        tmp_path,
        current=1_416_404 * 1024,
        maximum=2_097_152 * 1024,
    )

    with pytest.raises(ScreeningResourceDeferred) as caught:
        ensure_screening_headroom(values={}, root=tmp_path)

    error = caught.value
    assert error.reason == "insufficient_runtime_memory_for_screening"
    assert error.snapshot.governed_headroom_bytes == 25_388 * 1024
    assert error.snapshot.minimum_governed_headroom_bytes == 64 * 1024 * 1024
    assert "container_current_bytes=" in str(error)
    assert "governed_headroom_bytes=" in str(error)


def test_adequate_governed_headroom_allows_screening(tmp_path: Path) -> None:
    _write_cgroup(
        tmp_path,
        current=1_000 * 1024 * 1024,
        maximum=2_048 * 1024 * 1024,
    )

    snapshot = ensure_screening_headroom(values={}, root=tmp_path)

    assert snapshot.governed_headroom_bytes == 408 * 1024 * 1024


def test_unbounded_or_unavailable_cgroup_does_not_false_fail(tmp_path: Path) -> None:
    _write_cgroup(tmp_path, current=1, maximum="max")

    snapshot = ensure_screening_headroom(values={}, root=tmp_path)

    assert snapshot.container_current_bytes is None
    assert snapshot.container_limit_bytes is None
    assert snapshot.governed_headroom_bytes is None


def test_resource_thresholds_can_be_raised_without_changing_strategy(tmp_path: Path) -> None:
    _write_cgroup(
        tmp_path,
        current=1_000 * 1024 * 1024,
        maximum=2_048 * 1024 * 1024,
    )
    values = {
        "CAPITAL_INTELLIGENCE_DIAGNOSTIC_MEMORY_RESERVE_BYTES": str(700 * 1024 * 1024),
        "CAPITAL_INTELLIGENCE_SCREENING_MIN_GOVERNED_HEADROOM_BYTES": str(400 * 1024 * 1024),
    }

    snapshot = screening_resource_snapshot(values=values, root=tmp_path)

    assert snapshot.diagnostic_memory_reserve_bytes == 700 * 1024 * 1024
    assert snapshot.minimum_governed_headroom_bytes == 400 * 1024 * 1024
    assert snapshot.governed_headroom_bytes == 348 * 1024 * 1024


def test_reclaims_inactive_file_cache_before_screening_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Mirrors the exact c325274 production failure shape: file cache dominates the
    # overage while anonymous memory remains well below the 640 MiB reserve boundary.
    before_kib = 1_631_984
    _write_cgroup(
        tmp_path,
        current=before_kib * 1024,
        maximum=2_097_152 * 1024,
    )
    (tmp_path / "memory.stat").write_text(
        f"inactive_file {853_236 * 1024}\n"
        f"file {853_236 * 1024}\n"
        f"anon {700_456 * 1024}\n",
        encoding="utf-8",
    )
    (tmp_path / "memory.reclaim").write_text("", encoding="utf-8")
    requests: list[int] = []

    def reclaim(*, root: Path, requested_bytes: int):
        requests.append(requested_bytes)
        current = int((root / "memory.current").read_text(encoding="utf-8"))
        (root / "memory.current").write_text(
            str(max(0, current - requested_bytes)),
            encoding="utf-8",
        )
        return True, None

    monkeypatch.setattr(resource_guard, "_write_cgroup_reclaim", reclaim)

    snapshot = ensure_screening_headroom(values={}, root=tmp_path)

    assert requests
    assert len(requests) <= SCREENING_RECLAIM_MAX_ATTEMPTS
    assert all(value <= SCREENING_RECLAIM_MAX_BYTES_PER_ATTEMPT for value in requests)
    assert snapshot.governed_headroom_bytes is not None
    assert snapshot.governed_headroom_bytes >= snapshot.minimum_governed_headroom_bytes
    assert snapshot.container_current_bytes < before_kib * 1024
    assert snapshot.diagnostic_memory_reserve_bytes == 640 * 1024 * 1024
    assert snapshot.minimum_governed_headroom_bytes == 64 * 1024 * 1024


def test_ineffective_reclaim_still_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _write_cgroup(
        tmp_path,
        current=1_631_984 * 1024,
        maximum=2_097_152 * 1024,
    )
    (tmp_path / "memory.stat").write_text(
        f"inactive_file {853_236 * 1024}\n",
        encoding="utf-8",
    )
    (tmp_path / "memory.reclaim").write_text("", encoding="utf-8")
    attempts: list[int] = []

    def ineffective(*, root: Path, requested_bytes: int):
        del root
        attempts.append(requested_bytes)
        return True, None

    monkeypatch.setattr(resource_guard, "_write_cgroup_reclaim", ineffective)

    with pytest.raises(ScreeningResourceDeferred):
        ensure_screening_headroom(values={}, root=tmp_path)

    # No-progress detection prevents an advisory reclaim loop from delaying the
    # unchanged fail-closed guard.
    assert len(attempts) == 1


def test_unsupported_reclaim_still_fails_closed(tmp_path: Path) -> None:
    _write_cgroup(
        tmp_path,
        current=1_631_984 * 1024,
        maximum=2_097_152 * 1024,
    )
    (tmp_path / "memory.stat").write_text(
        f"inactive_file {853_236 * 1024}\n",
        encoding="utf-8",
    )

    with pytest.raises(ScreeningResourceDeferred):
        ensure_screening_headroom(values={}, root=tmp_path)


def test_start_progress_is_persisted_before_low_headroom_failure(monkeypatch) -> None:
    order: list[str] = []

    def fail_headroom() -> None:
        order.append("guard")
        raise ScreeningResourceDeferred(
            screening_resource_snapshot(
                values={
                    "CAPITAL_INTELLIGENCE_DIAGNOSTIC_MEMORY_RESERVE_BYTES": "1",
                    "CAPITAL_INTELLIGENCE_SCREENING_MIN_GOVERNED_HEADROOM_BYTES": "1",
                },
                root=Path("/definitely-missing-cgroup"),
            )
        )

    monkeypatch.setattr(runtime, "ensure_screening_headroom", fail_headroom)
    guarded = runtime._screening_resource_progress_probe(order.append)

    with pytest.raises(ScreeningResourceDeferred):
        guarded("production_context_screening_start_persisted")

    assert order == ["production_context_screening_start_persisted", "guard"]


def test_graph_release_reclaims_heap_and_evidence_cache_before_progress(monkeypatch) -> None:
    order: list[str] = []

    def trim() -> bool:
        order.append("trim")
        return True

    def release_cache(_values) -> tuple[Path, ...]:
        order.append("cache")
        return ()

    monkeypatch.setattr(runtime, "trim_released_heap", trim)
    monkeypatch.setattr(
        runtime,
        "release_completed_operating_evidence_file_cache",
        release_cache,
    )
    guarded = runtime._screening_resource_progress_probe(order.append)

    guarded("production_context_screening_graph_released")

    assert order == [
        "trim",
        "cache",
        "production_context_screening_graph_released",
    ]


def test_cache_release_is_not_repeated_at_screening_start(monkeypatch) -> None:
    order: list[str] = []

    def release_cache(_values) -> tuple[Path, ...]:
        order.append("cache")
        return ()

    def guard() -> None:
        order.append("guard")

    monkeypatch.setattr(
        runtime,
        "release_completed_operating_evidence_file_cache",
        release_cache,
    )
    monkeypatch.setattr(runtime, "ensure_screening_headroom", guard)
    guarded = runtime._screening_resource_progress_probe(order.append)

    guarded("production_context_screening_start_persisted")

    assert order == ["production_context_screening_start_persisted", "guard"]
