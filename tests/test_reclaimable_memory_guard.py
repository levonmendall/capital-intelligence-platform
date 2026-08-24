from __future__ import annotations

import signal

from operations import reclaimable_memory_guard as guard
from operations.reclaimable_memory_guard import (
    MemorySnapshot,
    _working_set_kib,
    limit_reason,
    memory_boundaries,
)


class _FinishedProcess:
    pid = 4242

    def wait(self, timeout: float):
        del timeout
        return 0


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


def _cgroup_v2_snapshot(*, raw: int, inactive: int, working: int | None = None) -> MemorySnapshot:
    return MemorySnapshot(
        raw_current_kib=raw,
        limit_kib=2 * 1024 * 1024,
        working_set_kib=(
            _working_set_kib(raw, inactive) if working is None else working
        ),
        inactive_file_kib=inactive,
        anon_kib=400_000,
        file_kib=inactive + 50_000,
        kernel_kib=20_000,
        source="cgroup_v2_configured_ceiling",
        active_file_kib=50_000,
    )


def _boundaries():
    return memory_boundaries(
        2 * 1024 * 1024,
        working_set_fraction=0.70,
        working_set_reserve_kib=640 * 1024,
        values={"RENDER": "true"},
    )


def _install_snapshots(monkeypatch, *snapshots: MemorySnapshot) -> None:
    remaining = list(snapshots)
    last = remaining[-1]

    def fake_snapshot(_values):
        if remaining:
            return remaining.pop(0)
        return last

    monkeypatch.setattr(guard, "memory_snapshot", fake_snapshot)
    monkeypatch.setattr(guard, "_process_memory_kib", lambda _pid: (100, 120))


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


def test_raw_only_breach_reclaims_then_continues(monkeypatch, tmp_path) -> None:
    before = _cgroup_v2_snapshot(raw=1_920_000, inactive=1_250_000)
    after = _cgroup_v2_snapshot(raw=1_760_000, inactive=1_100_000)
    _install_snapshots(monkeypatch, before, after, after)
    reclaim_path = tmp_path / "memory.reclaim"
    reclaim_path.write_text("", encoding="ascii")
    monkeypatch.setattr(guard, "_CGROUP_V2_RECLAIM_PATH", reclaim_path)
    signals = []
    monkeypatch.setattr(
        guard,
        "_signal_process_group",
        lambda _process, sig: signals.append(sig),
    )
    events = []
    monkeypatch.setattr(
        guard,
        "_safe_log",
        lambda event, **details: events.append((event, details)),
    )

    result = guard.wait_with_reclaimable_resource_bounds(
        _FinishedProcess(),
        timeout_seconds=1.0,
        memory_high_water_fraction=0.70,
        values={"RENDER": "true"},
        memory_reserve_kib=640 * 1024,
        poll_seconds=1.0,
    )

    assert result[2] is False
    assert signals == []
    assert int(reclaim_path.read_text(encoding="ascii")) > 0
    reclaim = next(
        details
        for event, details in events
        if event == "reclaimable_memory_guard_reclaim_attempted"
    )
    assert reclaim["memory_reclaim_effective"] is True
    assert reclaim["memory_reclaim_raw_before_kib"] == before.raw_current_kib
    assert reclaim["memory_reclaim_raw_after_kib"] == after.raw_current_kib


def test_ineffective_raw_reclaim_remains_fail_closed(monkeypatch, tmp_path) -> None:
    before = _cgroup_v2_snapshot(raw=1_920_000, inactive=1_250_000)
    after = _cgroup_v2_snapshot(raw=1_910_000, inactive=1_240_000)
    _install_snapshots(monkeypatch, before, after)
    reclaim_path = tmp_path / "memory.reclaim"
    reclaim_path.write_text("", encoding="ascii")
    monkeypatch.setattr(guard, "_CGROUP_V2_RECLAIM_PATH", reclaim_path)
    signals = []
    monkeypatch.setattr(
        guard,
        "_signal_process_group",
        lambda _process, sig: signals.append(sig),
    )
    events = []
    monkeypatch.setattr(
        guard,
        "_safe_log",
        lambda event, **details: events.append((event, details)),
    )

    result = guard.wait_with_reclaimable_resource_bounds(
        _FinishedProcess(),
        timeout_seconds=1.0,
        memory_high_water_fraction=0.70,
        values={"RENDER": "true"},
        memory_reserve_kib=640 * 1024,
        poll_seconds=1.0,
    )

    assert result[2] is True
    assert signals == [signal.SIGTERM]
    trigger = next(
        details
        for event, details in events
        if event == "reclaimable_memory_guard_triggered"
    )
    assert trigger["trigger_reason"] == "raw_hard_ceiling"
    assert trigger["memory_reclaim_attempted"] is True
    assert trigger["memory_reclaim_effective"] is False


def test_working_set_breach_never_uses_raw_reclaim(monkeypatch, tmp_path) -> None:
    unsafe = _cgroup_v2_snapshot(raw=1_600_000, inactive=50_000, working=1_550_000)
    _install_snapshots(monkeypatch, unsafe)
    reclaim_path = tmp_path / "memory.reclaim"
    reclaim_path.write_text("", encoding="ascii")
    monkeypatch.setattr(guard, "_CGROUP_V2_RECLAIM_PATH", reclaim_path)
    signals = []
    monkeypatch.setattr(
        guard,
        "_signal_process_group",
        lambda _process, sig: signals.append(sig),
    )
    events = []
    monkeypatch.setattr(
        guard,
        "_safe_log",
        lambda event, **details: events.append((event, details)),
    )

    result = guard.wait_with_reclaimable_resource_bounds(
        _FinishedProcess(),
        timeout_seconds=1.0,
        memory_high_water_fraction=0.70,
        values={"RENDER": "true"},
        memory_reserve_kib=640 * 1024,
        poll_seconds=1.0,
    )

    assert result[2] is True
    assert signals == [signal.SIGTERM]
    assert reclaim_path.read_text(encoding="ascii") == ""
    assert not any(
        event == "reclaimable_memory_guard_reclaim_attempted"
        for event, _details in events
    )
    trigger = next(
        details
        for event, details in events
        if event == "reclaimable_memory_guard_triggered"
    )
    assert trigger["trigger_reason"] == "working_set"


def test_unavailable_reclaim_fails_closed_if_raw_stays_unsafe(
    monkeypatch,
    tmp_path,
) -> None:
    unsafe = _cgroup_v2_snapshot(raw=1_920_000, inactive=1_250_000)
    _install_snapshots(monkeypatch, unsafe, unsafe)
    monkeypatch.setattr(
        guard,
        "_CGROUP_V2_RECLAIM_PATH",
        tmp_path / "missing-memory.reclaim",
    )
    signals = []
    monkeypatch.setattr(
        guard,
        "_signal_process_group",
        lambda _process, sig: signals.append(sig),
    )
    events = []
    monkeypatch.setattr(
        guard,
        "_safe_log",
        lambda event, **details: events.append((event, details)),
    )

    result = guard.wait_with_reclaimable_resource_bounds(
        _FinishedProcess(),
        timeout_seconds=1.0,
        memory_high_water_fraction=0.70,
        values={"RENDER": "true"},
        memory_reserve_kib=640 * 1024,
        poll_seconds=1.0,
    )

    assert result[2] is True
    assert signals == [signal.SIGTERM]
    trigger = next(
        details
        for event, details in events
        if event == "reclaimable_memory_guard_triggered"
    )
    assert trigger["memory_reclaim_supported"] is False
    assert trigger["memory_reclaim_error_type"] == "UnsupportedCgroupReclaim"


def test_reclaim_request_is_bounded_and_does_not_change_boundaries() -> None:
    limit = 2 * 1024 * 1024
    boundaries = _boundaries()
    unsafe = _cgroup_v2_snapshot(raw=2_050_000, inactive=1_500_000)

    request = guard._raw_reclaim_request_kib(unsafe, boundaries)

    assert request <= 256 * 1024
    assert request <= unsafe.inactive_file_kib
    assert boundaries.working_set_kib == limit - (640 * 1024)
    assert boundaries.raw_hard_kib == int(limit * 0.90)
