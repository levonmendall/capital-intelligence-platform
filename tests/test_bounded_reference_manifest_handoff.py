from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import pytest

import run_bounded_manual_cio_diagnostic as runtime
from operations.continuous_evidence_plane import ContinuousEvidencePlaneError


def _install_lightweight_runtime(monkeypatch: pytest.MonkeyPatch):
    prepare = runtime.prepare_reference_readiness
    globals_ = prepare.__globals__
    monkeypatch.setitem(globals_, "_install_recovery_progress_contract", lambda: None)
    monkeypatch.setitem(globals_, "install_cme_futures_reference_lineage", lambda: None)
    monkeypatch.setitem(globals_, "MassiveFuturesReferenceProvider", lambda: "massive")
    monkeypatch.setitem(
        globals_,
        "CmeExecutableFuturesReferenceProvider",
        lambda **kwargs: ("cme", kwargs),
    )
    return prepare, globals_


def test_production_bounded_cio_consumes_prequalified_manifest_without_provider_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare, globals_ = _install_lightweight_runtime(monkeypatch)
    manifest = SimpleNamespace(manifest_id="manifest:new")
    calls = {"loader": 0, "reference": 0}
    values = {
        "CAPITAL_INTELLIGENCE_ENVIRONMENT": "production",
        "CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/test-data",
    }

    def load_prequalified(resolved):
        calls["loader"] += 1
        assert resolved is values
        resolved["CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH"] = (
            "/tmp/test-data/reference-qualified.json"
        )
        resolved["CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"] = manifest.manifest_id
        return manifest

    def unexpected_reference(*_args, **_kwargs):
        calls["reference"] += 1
        raise AssertionError("production CIO must not acquire reference/provider evidence")

    monkeypatch.setitem(globals_, "_production_plane_enabled", lambda _values: True)
    monkeypatch.setitem(
        globals_,
        "load_prequalified_reference_manifest",
        load_prequalified,
    )
    monkeypatch.setitem(globals_, "_prepare_reference", unexpected_reference)

    result = prepare(values)

    assert result is manifest
    assert calls == {"loader": 1, "reference": 0}
    assert values["CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"] == manifest.manifest_id


def test_production_bounded_cio_propagates_missing_or_stale_prequalified_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare, globals_ = _install_lightweight_runtime(monkeypatch)
    reference_calls = 0
    values = {
        "CAPITAL_INTELLIGENCE_ENVIRONMENT": "production",
        "CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/test-data",
    }

    def fail_loader(_resolved):
        raise ContinuousEvidencePlaneError(
            "continuous evidence plane is missing or stale for the CIO cutoff"
        )

    def unexpected_reference(*_args, **_kwargs):
        nonlocal reference_calls
        reference_calls += 1
        return object()

    monkeypatch.setitem(globals_, "_production_plane_enabled", lambda _values: True)
    monkeypatch.setitem(
        globals_,
        "load_prequalified_reference_manifest",
        fail_loader,
    )
    monkeypatch.setitem(globals_, "_prepare_reference", unexpected_reference)

    with pytest.raises(
        ContinuousEvidencePlaneError,
        match="missing or stale",
    ):
        prepare(values)

    assert reference_calls == 0


def test_production_bounded_cio_requires_mutable_child_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare, globals_ = _install_lightweight_runtime(monkeypatch)
    monkeypatch.setitem(globals_, "_production_plane_enabled", lambda _values: True)
    monkeypatch.setitem(
        globals_,
        "load_prequalified_reference_manifest",
        lambda _values: object(),
    )

    with pytest.raises(TypeError, match="mutable watchdog environment"):
        prepare(MappingProxyType({"CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/test-data"}))


def test_nonproduction_bounded_cio_retains_reference_preparation_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare, globals_ = _install_lightweight_runtime(monkeypatch)
    manifest = SimpleNamespace(manifest_id="manifest:local")
    observed: dict[str, object] = {}
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/test-data"}

    def reference(resolved, **kwargs):
        observed["resolved"] = resolved
        observed["provider"] = kwargs["massive_futures_provider"]
        return manifest

    monkeypatch.setitem(globals_, "_production_plane_enabled", lambda _values: False)
    monkeypatch.setitem(globals_, "_prepare_reference", reference)
    monkeypatch.setitem(
        globals_,
        "load_prequalified_reference_manifest",
        lambda _values: (_ for _ in ()).throw(
            AssertionError("nonproduction must not require a production evidence generation")
        ),
    )

    result = prepare(values)

    assert result is manifest
    assert observed["resolved"] is values
    provider = observed["provider"]
    assert provider[0] == "cme"
    assert provider[1]["fallback_provider"] == "massive"
    assert provider[1]["values"] is values
