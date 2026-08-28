from __future__ import annotations

import run_bounded_manual_cio_diagnostic as runtime
from operations import reclaimable_memory_guard as guard


class _FinishedProcess:
    pid = 4242

    def wait(self, timeout: float):
        del timeout
        return 0


def _snapshot(*, raw: int, inactive: int, working: int) -> guard.MemorySnapshot:
    return guard.MemorySnapshot(
        raw_current_kib=raw,
        limit_kib=2 * 1024 * 1024,
        working_set_kib=working,
        inactive_file_kib=inactive,
        anon_kib=working - 60_000,
        file_kib=inactive + 50_000,
        kernel_kib=10_000,
        source="cgroup_v2_configured_ceiling",
        active_file_kib=50_000,
    )


def test_raw_cgroup_reclaim_error_uses_one_streaming_file_cache_fallback(monkeypatch) -> None:
    unsafe = _snapshot(raw=1_981_360, inactive=970_252, working=1_011_108)
    safe = _snapshot(raw=1_850_000, inactive=840_000, working=1_010_000)
    remaining = [unsafe, safe]

    def memory_snapshot(_values):
        if remaining:
            return remaining.pop(0)
        return safe

    monkeypatch.setattr(guard, "memory_snapshot", memory_snapshot)
    monkeypatch.setattr(guard, "_process_memory_kib", lambda _pid: (568, 568))
    reclaim_calls: list[guard.MemorySnapshot] = []

    def failed_cgroup_reclaim(snapshot, boundaries, *, values):
        del boundaries, values
        reclaim_calls.append(snapshot)
        return (
            guard.MemoryReclaimResult(
                attempted=True,
                supported=True,
                requested_kib=126_180,
                raw_before_kib=snapshot.raw_current_kib,
                raw_after_kib=snapshot.raw_current_kib,
                working_set_before_kib=snapshot.working_set_kib,
                working_set_after_kib=snapshot.working_set_kib,
                reclaimed_kib=0,
                effective=False,
                error_type="OSError",
            ),
            snapshot,
        )

    monkeypatch.setattr(guard, "_attempt_cgroup_v2_reclaim", failed_cgroup_reclaim)
    signals = []
    monkeypatch.setattr(
        guard,
        "_signal_process_group",
        lambda _process, sig: signals.append(sig),
    )
    logs = []
    monkeypatch.setattr(
        guard,
        "_safe_log",
        lambda event, **details: logs.append((event, details)),
    )

    waiter = runtime._wait_with_resource_bounds
    wrapper_globals = waiter.__globals__
    fallback_calls: list[dict[str, str]] = []

    def streaming_fallback(values):
        fallback_calls.append(dict(values))
        return {
            "supported": True,
            "scan_entries": 10_824,
            "selected_file_count": 10_824,
            "released_file_count": 10_824,
            "released_bytes": 900 * 1024 * 1024,
        }

    monkeypatch.setitem(
        wrapper_globals,
        "release_streaming_clean_file_cache",
        streaming_fallback,
    )

    result = waiter(
        _FinishedProcess(),
        timeout_seconds=1.0,
        memory_high_water_fraction=0.70,
        values={"RENDER": "true", "CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/data"},
        memory_reserve_kib=640 * 1024,
        poll_seconds=1.0,
    )

    assert result[2] is False
    assert signals == []
    assert len(reclaim_calls) == 1
    assert len(fallback_calls) == 1
    assert any(
        event == "reclaimable_memory_guard_file_cache_fallback"
        for event, _details in logs
    )
    report = runtime._last_reclaimable_memory_report
    assert report["memory_reclaim_operable"] is False
    assert report["memory_cgroup_reclaim_error_type"] == "OSError"
    assert report["memory_file_cache_fallback_attempted"] is True
    assert report["memory_file_cache_fallback_effective"] is True
    assert report["memory_file_cache_fallback_reclaimed_kib"] == 131_360
    assert report["memory_reclaim_supported"] is False
    assert report["memory_limited"] is False
