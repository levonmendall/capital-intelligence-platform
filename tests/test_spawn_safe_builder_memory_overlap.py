from __future__ import annotations

from pathlib import Path

import pytest

from operations import spawn_safe_authoritative_acquisition as spawn_safe
from operations.comprehensive_discovery_input_spool import ComprehensiveDiscoverySpoolError


def test_prepare_spool_uses_current_coordinator_and_preserves_finite_children(
    tmp_path, monkeypatch
) -> None:
    request_path = tmp_path / "request.json"
    values = {"CAPITAL_INTELLIGENCE_RELEASE": "release-test"}
    calls: list[tuple[Path, dict[str, str]]] = []

    monkeypatch.setattr(spawn_safe, "manifest_available", lambda _path: False)

    def fake_build(path, *, values=None):
        calls.append((Path(path), dict(values or {})))
        return tmp_path / "manifest.json"

    monkeypatch.setattr(spawn_safe, "build_spool", fake_build)

    spawn_safe._prepare_spool_process(request_path, values)

    assert calls == [(request_path, values)]
    source = Path("operations/spawn_safe_authoritative_acquisition.py").read_text(
        encoding="utf-8"
    )
    start = source.index("def _prepare_spool_process")
    end = source.index("\ndef spawn_safe_acquire", start)
    coordinator_body = source[start:end]
    assert "build_spool(request_path, values=values)" in coordinator_body
    assert "subprocess.Popen" not in coordinator_body


def test_prepare_spool_reuses_existing_manifest(tmp_path, monkeypatch) -> None:
    request_path = tmp_path / "request.json"
    called = False

    monkeypatch.setattr(spawn_safe, "manifest_available", lambda _path: True)

    def forbidden_build(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("existing manifest must not be rebuilt")

    monkeypatch.setattr(spawn_safe, "build_spool", forbidden_build)

    spawn_safe._prepare_spool_process(request_path, {})

    assert called is False


def test_prepare_spool_preserves_durable_substage_failure_attribution(
    tmp_path, monkeypatch
) -> None:
    request_path = tmp_path / "request.json"

    monkeypatch.setattr(spawn_safe, "manifest_available", lambda _path: False)

    def failing_build(*_args, **_kwargs):
        raise ComprehensiveDiscoverySpoolError("lane child failed")

    monkeypatch.setattr(spawn_safe, "build_spool", failing_build)
    monkeypatch.setattr(
        spawn_safe,
        "load_failure",
        lambda _path: {
            "failure_stage": "bounded_lane:crypto",
            "error_type": "ResourceBoundaryExceeded",
            "error_detail": "working_set boundary exceeded",
        },
    )

    with pytest.raises(
        spawn_safe._scheduler.CertificationSchedulerError,
        match="stage=bounded_lane:crypto.*ResourceBoundaryExceeded",
    ):
        spawn_safe._prepare_spool_process(request_path, {})
