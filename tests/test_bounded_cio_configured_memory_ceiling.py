from __future__ import annotations

import run_bounded_manual_cio_diagnostic as bounded


def test_configured_memory_limit_caps_looser_cgroup(monkeypatch) -> None:
    monkeypatch.setattr(
        bounded,
        "_cgroup_memory_kib",
        lambda: (512 * 1024, 8192 * 1024),
    )

    current_kib, limit_kib, source = bounded._container_memory_kib(
        {"CAPITAL_INTELLIGENCE_CONTAINER_MEMORY_LIMIT_MB": "2048"}
    )

    assert current_kib == 512 * 1024
    assert limit_kib == 2048 * 1024
    assert source == "cgroup_configured_ceiling"


def test_stricter_cgroup_limit_remains_authoritative(monkeypatch) -> None:
    monkeypatch.setattr(
        bounded,
        "_cgroup_memory_kib",
        lambda: (512 * 1024, 1024 * 1024),
    )

    current_kib, limit_kib, source = bounded._container_memory_kib(
        {"CAPITAL_INTELLIGENCE_CONTAINER_MEMORY_LIMIT_MB": "2048"}
    )

    assert current_kib == 512 * 1024
    assert limit_kib == 1024 * 1024
    assert source == "cgroup"


def test_render_default_caps_looser_cgroup(monkeypatch) -> None:
    monkeypatch.setattr(
        bounded,
        "_cgroup_memory_kib",
        lambda: (768 * 1024, 16384 * 1024),
    )

    current_kib, limit_kib, source = bounded._container_memory_kib({"RENDER": "true"})

    assert current_kib == 768 * 1024
    assert limit_kib == 2048 * 1024
    assert source == "cgroup_configured_ceiling"
