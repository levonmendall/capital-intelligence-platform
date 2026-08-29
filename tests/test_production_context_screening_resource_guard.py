from __future__ import annotations

from pathlib import Path

import pytest

import production_context_publication_runtime as runtime
import production_context_screening_resource_guard as resource_guard
from production_context_screening_resource_guard import (
    ScreeningResourceDeferred,
    ensure_screening_headroom,
    reclaim_released_file_cache_for_screening,
    screening_resource_snapshot,
)


def _write_cgroup(root: Path, *, current: int, maximum: int | str) -> None:
    (root / "memory.current").write_text(str(current), encoding="utf-8")
    (root / "memory.max").write_text(str(maximum), encoding="utf-8")


def _write_memory_stat(root: Path, *, inactive_file: int, file: int | None = None) -> None:
    file_value = inactive_file if file is None else file
    (root / "memory.stat").write_text(
        f"inactive_file {inactive_file}\nfile {file_value}\n",
        encoding="utf-8",
    )


def test_observed_production_boundary_fails_closed_with_stable_reason(tmp_path: Path) -> None:
    # Mirrors the failed production diagnostic: 2 GiB limit, ~1.35 GiB current,
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


def test_screening_reclaim_restores_exact_existing_headroom_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    maximum = 2_048 * 1024 * 1024
    reserve = 640 * 1024 * 1024
    minimum = 64 * 1024 * 1024
    target = maximum - reserve - minimum
    current = target + 180 * 1024 * 1024
    inactive = 512 * 1024 * 1024
    _write_cgroup(tmp_path, current=current, maximum=maximum)
    _write_memory_stat(tmp_path, inactive_file=inactive)
    (tmp_path / "memory.reclaim").write_text("", encoding="utf-8")
    requests: list[int] = []

    def reclaim(root: Path, requested_bytes: int) -> None:
        requests.append(requested_bytes)
        before = int((root / "memory.current").read_text(encoding="utf-8"))
        after = max(target - 1, before - requested_bytes)
        (root / "memory.current").write_text(str(after), encoding="utf-8")

    monkeypatch.setattr(resource_guard, "_request_cgroup_v2_reclaim", reclaim)

    result = reclaim_released_file_cache_for_screening(values={}, root=tmp_path)

    assert result.attempted is True
    assert result.supported is True
    assert result.effective is True
    assert result.target_current_bytes == target
    assert result.current_before_bytes == current
    assert result.current_after_bytes <= target
    assert result.attempt_count == 1
    assert requests == [min(256 * 1024 * 1024, current - target + 32 * 1024 * 1024)]


def test_screening_headroom_remeasures_after_successful_reclaim(
    tmp_path: Path,
    monkeypatch,
) -> None:
    maximum = 2_048 * 1024 * 1024
    reserve = 640 * 1024 * 1024
    minimum = 64 * 1024 * 1024
    target = maximum - reserve - minimum
    _write_cgroup(
        tmp_path,
        current=target + 96 * 1024 * 1024,
        maximum=maximum,
    )
    _write_memory_stat(tmp_path, inactive_file=384 * 1024 * 1024)
    (tmp_path / "memory.reclaim").write_text("", encoding="utf-8")

    def reclaim(root: Path, requested_bytes: int) -> None:
        assert requested_bytes > 0
        (root / "memory.current").write_text(str(target - 1), encoding="utf-8")

    monkeypatch.setattr(resource_guard, "_request_cgroup_v2_reclaim", reclaim)

    snapshot = ensure_screening_headroom(values={}, root=tmp_path)

    assert snapshot.governed_headroom_bytes == minimum + 1
    assert snapshot.minimum_governed_headroom_bytes == minimum


def test_ineffective_reclaim_does_not_weaken_fail_closed_guard(
    tmp_path: Path,
    monkeypatch,
) -> None:
    maximum = 2_048 * 1024 * 1024
    reserve = 640 * 1024 * 1024
    minimum = 64 * 1024 * 1024
    target = maximum - reserve - minimum
    current = target + 160 * 1024 * 1024
    _write_cgroup(tmp_path, current=current, maximum=maximum)
    _write_memory_stat(tmp_path, inactive_file=512 * 1024 * 1024)
    (tmp_path / "memory.reclaim").write_text("", encoding="utf-8")
    requests: list[int] = []

    def ineffective(_root: Path, requested_bytes: int) -> None:
        requests.append(requested_bytes)

    monkeypatch.setattr(resource_guard, "_request_cgroup_v2_reclaim", ineffective)

    with pytest.raises(ScreeningResourceDeferred) as caught:
        ensure_screening_headroom(values={}, root=tmp_path)

    assert caught.value.snapshot.governed_headroom_bytes < minimum
    assert len(requests) == 3
    assert all(0 < request <= 256 * 1024 * 1024 for request in requests)


def test_reclaim_is_not_attempted_without_inactive_file_pages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    maximum = 2_048 * 1024 * 1024
    target = maximum - 640 * 1024 * 1024 - 64 * 1024 * 1024
    _write_cgroup(
        tmp_path,
        current=target + 80 * 1024 * 1024,
        maximum=maximum,
    )
    _write_memory_stat(tmp_path, inactive_file=0, file=700 * 1024 * 1024)
    (tmp_path / "memory.reclaim").write_text("", encoding="utf-8")

    def unexpected(*_args, **_kwargs) -> None:
        raise AssertionError("inactive-file-gated reclaim should not run")

    monkeypatch.setattr(resource_guard, "_request_cgroup_v2_reclaim", unexpected)

    result = reclaim_released_file_cache_for_screening(values={}, root=tmp_path)

    assert result.attempted is False
    assert result.effective is False
    assert result.inactive_file_before_bytes == 0


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
