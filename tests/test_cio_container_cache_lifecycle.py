import os
import sqlite3

from operations import bounded_terminal_screening as screening
from operations import manual_cio_diagnostic as diagnostic


def test_spool_connection_disables_sqlite_mmap(tmp_path):
    database = tmp_path / "spool.sqlite3"
    connection = sqlite3.connect(database)
    try:
        screening._configure_spool_connection(connection)
        row = connection.execute("PRAGMA mmap_size").fetchone()
        assert row is not None
        assert int(row[0]) == 0
    finally:
        connection.close()


def test_file_cache_advice_is_best_effort_and_preserves_file(tmp_path, monkeypatch):
    target = tmp_path / "durable.json"
    target.write_text("evidence\n", encoding="utf-8")
    calls = []

    monkeypatch.setattr(screening.os, "open", lambda path, flags: 41)
    monkeypatch.setattr(screening.os, "close", lambda descriptor: calls.append(("close", descriptor)))
    monkeypatch.setattr(
        screening.os,
        "posix_fadvise",
        lambda descriptor, offset, length, advice: calls.append(
            ("advise", descriptor, offset, length, advice)
        ),
        raising=False,
    )
    monkeypatch.setattr(screening.os, "POSIX_FADV_DONTNEED", 4, raising=False)

    screening._advise_file_cache_dontneed(target)

    assert ("advise", 41, 0, 0, 4) in calls
    assert ("close", 41) in calls
    assert target.read_text(encoding="utf-8") == "evidence\n"


def test_cgroup_memory_stat_reports_anon_file_shmem_and_kernel(monkeypatch):
    def fake_counters(path):
        if str(path) == "/sys/fs/cgroup/memory.stat":
            return {
                "anon": 100 * 1024,
                "file": 200 * 1024,
                "shmem": 30 * 1024,
                "kernel": 40 * 1024,
            }
        return {}

    monkeypatch.setattr(diagnostic, "_read_keyed_byte_counters", fake_counters)

    assert diagnostic._cgroup_memory_stat_kib() == {
        "container_anon_kib": 100,
        "container_file_kib": 200,
        "container_shmem_kib": 30,
        "container_kernel_kib": 40,
    }


def test_terminal_resource_metrics_include_container_composition_and_service_rss(monkeypatch):
    monkeypatch.setattr(
        diagnostic,
        "_read_kib_field",
        lambda _path, field: 210 if field == "VmRSS" else 250,
    )
    monkeypatch.setattr(diagnostic, "_proc_total_rss_kib", lambda: 900)
    monkeypatch.setattr(
        diagnostic,
        "_cgroup_memory_stat_kib",
        lambda: {
            "container_anon_kib": 700,
            "container_file_kib": 500,
            "container_shmem_kib": 20,
            "container_kernel_kib": 80,
        },
    )
    monkeypatch.setattr(diagnostic, "_container_memory_kib", lambda _values: (1325, 2048))
    monkeypatch.setattr(diagnostic, "_configured_memory_reserve_kib", lambda _values: 640)
    monkeypatch.setattr(
        diagnostic,
        "_configured_memory_high_water_fraction",
        lambda _values: 0.70,
    )

    metrics = diagnostic._terminal_screening_resource_metrics({})

    assert metrics["rss_kib"] == 210
    assert metrics["hwm_kib"] == 250
    assert metrics["service_rss_kib"] == 900
    assert metrics["container_anon_kib"] == 700
    assert metrics["container_file_kib"] == 500
    assert metrics["container_shmem_kib"] == 20
    assert metrics["container_kernel_kib"] == 80
    assert metrics["container_current_kib"] == 1325
    assert metrics["container_limit_kib"] == 2048
    assert metrics["governed_boundary_kib"] == 1433
    assert metrics["governed_headroom_kib"] == 108


def test_new_container_metrics_are_governed_progress_metrics():
    normalized = dict(
        diagnostic._normalize_progress_metrics(
            {
                "service_rss_kib": 1,
                "container_anon_kib": 2,
                "container_file_kib": 3,
                "container_shmem_kib": 4,
                "container_kernel_kib": 5,
            }
        )
    )
    assert normalized == {
        "container_anon_kib": 2,
        "container_file_kib": 3,
        "container_kernel_kib": 5,
        "container_shmem_kib": 4,
        "service_rss_kib": 1,
    }
