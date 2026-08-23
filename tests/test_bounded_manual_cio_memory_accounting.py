from __future__ import annotations

import run_bounded_manual_cio_diagnostic_core as watchdog


class _FinishedProcess:
    pid = 123
    returncode = 0

    def wait(self, timeout=None):
        return 0


def test_governed_cgroup_memory_excludes_reclaimable_file_cache(monkeypatch):
    monkeypatch.setattr(
        watchdog,
        "_read_memory_stat_kib",
        lambda _path: {
            "anon": 400_000,
            "file": 1_000_000,
            "kernel": 100_000,
            "shmem": 20_000,
        },
    )
    monkeypatch.setattr(watchdog, "_proc_total_rss_kib", lambda: 600_000)

    governed, source = watchdog._governed_cgroup_memory_kib(1_600_000)

    assert governed == 600_000
    assert source == "cgroup_v2_nonreclaimable"


def test_governed_cgroup_memory_falls_back_to_total_when_stat_unavailable(monkeypatch):
    monkeypatch.setattr(watchdog, "_read_memory_stat_kib", lambda _path: None)

    governed, source = watchdog._governed_cgroup_memory_kib(1_600_000)

    assert governed == 1_600_000
    assert source == "cgroup_current_fallback"


def test_normal_guard_does_not_trip_on_reclaimable_page_cache(monkeypatch):
    monkeypatch.setattr(watchdog, "_process_memory_kib", lambda _pid: (200_000, 220_000))
    monkeypatch.setattr(
        watchdog,
        "_container_memory_sample_kib",
        lambda _values: (600_000, 1_600_000, 2_000_000, "cgroup_v2_nonreclaimable"),
    )
    monkeypatch.setattr(watchdog, "_signal_process_group", lambda *_args: None)

    result = watchdog._wait_with_resource_bounds(
        _FinishedProcess(),
        timeout_seconds=1,
        memory_high_water_fraction=0.70,
        memory_reserve_kib=640_000,
        poll_seconds=0.01,
    )

    assert result[2] is False
    assert result[4] == 1_600_000


def test_normal_guard_trips_on_nonreclaimable_memory(monkeypatch):
    monkeypatch.setattr(watchdog, "_process_memory_kib", lambda _pid: (200_000, 220_000))
    monkeypatch.setattr(
        watchdog,
        "_container_memory_sample_kib",
        lambda _values: (1_500_000, 1_600_000, 2_000_000, "cgroup_v2_nonreclaimable"),
    )
    monkeypatch.setattr(watchdog, "_signal_process_group", lambda *_args: None)

    result = watchdog._wait_with_resource_bounds(
        _FinishedProcess(),
        timeout_seconds=1,
        memory_high_water_fraction=0.70,
        memory_reserve_kib=640_000,
        poll_seconds=0.01,
    )

    assert result[2] is True


def test_hard_total_guard_still_trips_before_cgroup_limit(monkeypatch):
    monkeypatch.setattr(watchdog, "_process_memory_kib", lambda _pid: (200_000, 220_000))
    monkeypatch.setattr(
        watchdog,
        "_container_memory_sample_kib",
        lambda _values: (600_000, 1_850_000, 2_000_000, "cgroup_v2_nonreclaimable"),
    )
    monkeypatch.setattr(watchdog, "_signal_process_group", lambda *_args: None)

    result = watchdog._wait_with_resource_bounds(
        _FinishedProcess(),
        timeout_seconds=1,
        memory_high_water_fraction=0.70,
        memory_reserve_kib=640_000,
        poll_seconds=0.01,
    )

    assert result[2] is True
