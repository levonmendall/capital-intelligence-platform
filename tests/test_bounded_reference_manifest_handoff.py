from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import run_bounded_manual_cio_diagnostic as runtime
from operations.continuous_evidence_plane import ContinuousEvidencePlaneError


_MANIFEST_PATH_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH"
_MANIFEST_ID_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"
_PREPARING_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING"


def _install_lightweight_runtime(monkeypatch: pytest.MonkeyPatch):
    prepare = runtime.prepare_reference_readiness
    globals_ = prepare.__globals__
    monkeypatch.setitem(globals_, "_install_recovery_progress_contract", lambda: None)
    monkeypatch.setitem(globals_, "install_cme_futures_reference_lineage", lambda: None)
    monkeypatch.setitem(globals_, "MassiveFuturesReferenceProvider", lambda: object())
    monkeypatch.setitem(
        globals_,
        "CmeExecutableFuturesReferenceProvider",
        lambda **_kwargs: object(),
    )
    monkeypatch.setitem(globals_, "_production_plane_enabled", lambda _values: True)
    return prepare, globals_


def _bind_manifest(resolved, manifest) -> None:
    resolved[_MANIFEST_PATH_ENV] = "/tmp/test-data/reference-qualified.json"
    resolved[_MANIFEST_ID_ENV] = manifest.manifest_id


def test_bounded_preclock_discovery_reuses_qualified_manifest_and_restores_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare, globals_ = _install_lightweight_runtime(monkeypatch)
    manifest = SimpleNamespace(manifest_id="manifest:new")
    calls = {"reference": 0, "refresh": 0, "snapshot": 0}
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/test-data"}

    def fake_reference(resolved, **_kwargs):
        calls["reference"] += 1
        _bind_manifest(resolved, manifest)
        return manifest

    def fake_snapshot(*, values, allow_refresh):
        calls["snapshot"] += 1
        assert allow_refresh is False
        assert values[_MANIFEST_ID_ENV] == manifest.manifest_id
        assert os.environ[_PREPARING_ENV] == "true"
        assert os.environ[_MANIFEST_PATH_ENV] == values[_MANIFEST_PATH_ENV]
        assert os.environ[_MANIFEST_ID_ENV] == manifest.manifest_id
        if calls["snapshot"] == 1:
            return SimpleNamespace(reference_manifest_id="manifest:previous")
        return SimpleNamespace(reference_manifest_id=manifest.manifest_id)

    def fake_refresh(*, values, reference_preparer):
        calls["refresh"] += 1
        assert reference_preparer(values) is manifest
        assert os.environ[_MANIFEST_PATH_ENV] == values[_MANIFEST_PATH_ENV]
        assert os.environ[_MANIFEST_ID_ENV] == manifest.manifest_id
        return object()

    monkeypatch.setitem(globals_, "_prepare_reference", fake_reference)
    monkeypatch.setitem(globals_, "ensure_point_in_time_snapshot", fake_snapshot)
    monkeypatch.setitem(globals_, "refresh_continuous_evidence_plane", fake_refresh)
    monkeypatch.setenv(_PREPARING_ENV, "prior-preparing")
    monkeypatch.setenv(_MANIFEST_PATH_ENV, "/tmp/prior-reference.json")
    monkeypatch.setenv(_MANIFEST_ID_ENV, "manifest:prior")

    result = prepare(values)

    assert result is manifest
    assert calls == {"reference": 1, "refresh": 1, "snapshot": 2}
    assert os.environ[_PREPARING_ENV] == "prior-preparing"
    assert os.environ[_MANIFEST_PATH_ENV] == "/tmp/prior-reference.json"
    assert os.environ[_MANIFEST_ID_ENV] == "manifest:prior"


def test_bounded_manifest_handoff_restores_env_when_discovery_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare, globals_ = _install_lightweight_runtime(monkeypatch)
    manifest = SimpleNamespace(manifest_id="manifest:new")
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/test-data"}

    def fake_reference(resolved, **_kwargs):
        _bind_manifest(resolved, manifest)
        return manifest

    monkeypatch.setitem(globals_, "_prepare_reference", fake_reference)
    monkeypatch.setitem(
        globals_,
        "ensure_point_in_time_snapshot",
        lambda **_kwargs: SimpleNamespace(reference_manifest_id="manifest:previous"),
    )

    def fail_refresh(**_kwargs):
        assert os.environ[_PREPARING_ENV] == "true"
        assert os.environ[_MANIFEST_ID_ENV] == manifest.manifest_id
        raise ContinuousEvidencePlaneError("discovery failed")

    monkeypatch.setitem(globals_, "refresh_continuous_evidence_plane", fail_refresh)
    monkeypatch.setenv(_PREPARING_ENV, "prior-preparing")
    monkeypatch.setenv(_MANIFEST_PATH_ENV, "/tmp/prior-reference.json")
    monkeypatch.setenv(_MANIFEST_ID_ENV, "manifest:prior")

    with pytest.raises(ContinuousEvidencePlaneError, match="discovery failed"):
        prepare(values)

    assert os.environ[_PREPARING_ENV] == "prior-preparing"
    assert os.environ[_MANIFEST_PATH_ENV] == "/tmp/prior-reference.json"
    assert os.environ[_MANIFEST_ID_ENV] == "manifest:prior"


def test_bounded_manifest_handoff_does_not_refresh_integrity_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare, globals_ = _install_lightweight_runtime(monkeypatch)
    manifest = SimpleNamespace(manifest_id="manifest:new")
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/test-data"}
    refresh_calls = 0

    def fake_reference(resolved, **_kwargs):
        _bind_manifest(resolved, manifest)
        return manifest

    def fail_integrity(**_kwargs):
        raise ContinuousEvidencePlaneError("evidence-plane manifest integrity mismatch")

    def unexpected_refresh(**_kwargs):
        nonlocal refresh_calls
        refresh_calls += 1
        return object()

    monkeypatch.setitem(globals_, "_prepare_reference", fake_reference)
    monkeypatch.setitem(globals_, "ensure_point_in_time_snapshot", fail_integrity)
    monkeypatch.setitem(globals_, "refresh_continuous_evidence_plane", unexpected_refresh)

    with pytest.raises(ContinuousEvidencePlaneError, match="integrity mismatch"):
        prepare(values)

    assert refresh_calls == 0


def test_bounded_manifest_handoff_fails_closed_without_qualified_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare, globals_ = _install_lightweight_runtime(monkeypatch)
    manifest = SimpleNamespace(manifest_id="manifest:new")
    monkeypatch.setitem(globals_, "_prepare_reference", lambda _values, **_kwargs: manifest)

    with pytest.raises(
        ContinuousEvidencePlaneError,
        match="did not bind its manifest",
    ):
        prepare({"CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/test-data"})
