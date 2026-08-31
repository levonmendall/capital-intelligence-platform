from __future__ import annotations

from pathlib import Path

from operations import reclaimable_memory_guard as guard


def test_resolves_nested_process_cgroup_from_unified_mount(tmp_path: Path) -> None:
    cgroup = tmp_path / "cgroup"
    mountinfo = tmp_path / "mountinfo"
    cgroup.write_text("0::/render.slice/service.scope\n", encoding="utf-8")
    mountinfo.write_text(
        "34 23 0:29 / /sys/fs/cgroup rw,nosuid,nodev,noexec,relatime - cgroup2 cgroup rw\n",
        encoding="utf-8",
    )

    assert guard._resolve_process_cgroup_v2_directory(
        cgroup_path=cgroup,
        mountinfo_path=mountinfo,
    ) == Path("/sys/fs/cgroup/render.slice/service.scope")


def test_resolves_process_path_relative_to_non_root_mount_root(tmp_path: Path) -> None:
    cgroup = tmp_path / "cgroup"
    mountinfo = tmp_path / "mountinfo"
    cgroup.write_text("0::/platform.slice/render.scope\n", encoding="utf-8")
    mountinfo.write_text(
        "34 23 0:29 /platform.slice /sys/fs/cgroup rw - cgroup2 cgroup rw\n",
        encoding="utf-8",
    )

    assert guard._resolve_process_cgroup_v2_directory(
        cgroup_path=cgroup,
        mountinfo_path=mountinfo,
    ) == Path("/sys/fs/cgroup/render.scope")


def test_malformed_process_cgroup_falls_back_to_legacy_paths(monkeypatch) -> None:
    monkeypatch.setattr(guard, "_resolve_process_cgroup_v2_directory", lambda: None)

    paths = guard._cgroup_v2_paths()

    assert paths.process_scoped is False
    assert paths.current == guard._CGROUP_V2_CURRENT_PATH
    assert paths.stat == guard._CGROUP_V2_STAT_PATH
    assert paths.reclaim == guard._CGROUP_V2_RECLAIM_PATH


def test_process_scoped_snapshot_uses_nested_memory_files(monkeypatch, tmp_path: Path) -> None:
    nested = tmp_path / "service.scope"
    nested.mkdir()
    (nested / "memory.current").write_text(str(1_500_000 * 1024), encoding="utf-8")
    (nested / "memory.max").write_text(str(2_048_000 * 1024), encoding="utf-8")
    (nested / "memory.stat").write_text(
        "inactive_file 409600000\nactive_file 102400000\nanon 716800000\nfile 512000000\nkernel 51200000\n",
        encoding="utf-8",
    )
    (nested / "memory.events").write_text("oom 0\noom_kill 0\n", encoding="utf-8")
    monkeypatch.setattr(guard, "_resolve_process_cgroup_v2_directory", lambda: nested)

    snapshot = guard.memory_snapshot({})

    assert snapshot.source == "cgroup_v2_process"
    assert snapshot.raw_current_kib == 1_500_000
    assert snapshot.inactive_file_kib == 400_000
    assert snapshot.working_set_kib == 1_100_000
    assert snapshot.active_file_kib == 100_000


def test_process_scoped_reclaim_never_climbs_to_parent(monkeypatch, tmp_path: Path) -> None:
    nested = tmp_path / "service.scope"
    nested.mkdir()
    parent_reclaim = tmp_path / "memory.reclaim"
    parent_reclaim.write_text("", encoding="ascii")
    monkeypatch.setattr(guard, "_resolve_process_cgroup_v2_directory", lambda: nested)

    assert guard._reclaim_path() == nested / "memory.reclaim"
    assert not guard._reclaim_path().exists()
    assert parent_reclaim.exists()


def test_process_scoped_reclaim_path_is_used_when_available(monkeypatch, tmp_path: Path) -> None:
    nested = tmp_path / "service.scope"
    nested.mkdir()
    reclaim = nested / "memory.reclaim"
    reclaim.write_text("", encoding="ascii")
    monkeypatch.setattr(guard, "_resolve_process_cgroup_v2_directory", lambda: nested)

    assert guard._reclaim_path() == reclaim
