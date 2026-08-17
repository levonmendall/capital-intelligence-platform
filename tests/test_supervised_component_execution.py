from __future__ import annotations

from datetime import datetime, timezone
import time
from types import SimpleNamespace

import pytest

from operations import component_qualified_evidence_maintenance as maintenance
from operations.supervised_component_execution import (
    SupervisedComponentExecutionError,
    SupervisedComponentTimeout,
    run_supervised_component,
)


def test_supervised_component_returns_small_result() -> None:
    result = run_supervised_component(
        component="test-component",
        operation=lambda: {"qualified": True},
        timeout_seconds=1.0,
    )

    assert result == {"qualified": True}


def test_supervised_component_can_ignore_unpicklable_result() -> None:
    result = run_supervised_component(
        component="test-component",
        operation=lambda: (lambda: None),
        timeout_seconds=1.0,
        return_value=False,
    )

    assert result is None


def test_supervised_component_redacts_child_error_secrets() -> None:
    def fail() -> None:
        raise RuntimeError("provider api_key=supersecret failed")

    with pytest.raises(SupervisedComponentExecutionError) as captured:
        run_supervised_component(
            component="test-component",
            operation=fail,
            timeout_seconds=1.0,
        )

    message = str(captured.value)
    assert "supersecret" not in message
    assert "api_key=<redacted>" in message


def test_supervised_component_hard_timeout_returns_control() -> None:
    started = time.monotonic()
    with pytest.raises(SupervisedComponentTimeout, match="execution budget"):
        run_supervised_component(
            component="hung-provider",
            operation=lambda: time.sleep(5.0),
            timeout_seconds=0.05,
        )
    elapsed = time.monotonic() - started

    assert elapsed < 2.0


def test_reference_binding_prepares_only_missing_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cutoff = datetime.now(timezone.utc)
    manifest = SimpleNamespace(manifest_id="manifest-qualified")
    calls = {"bind": 0, "prepare": 0, "supervise": 0}

    def bind(_values, *, now):
        assert now == cutoff
        calls["bind"] += 1
        if calls["bind"] == 1:
            raise maintenance.ReferenceReadinessError("missing")
        return manifest

    def prepare(_values):
        calls["prepare"] += 1
        return SimpleNamespace(manifest_id="prepared")

    def supervise(
        _values,
        *,
        component,
        operation,
        timeout_env,
        default_timeout,
        return_value,
    ):
        assert component == "reference-readiness"
        assert timeout_env == maintenance._REFERENCE_TIMEOUT_ENV
        assert default_timeout == maintenance._DEFAULT_REFERENCE_TIMEOUT_SECONDS
        assert return_value is False
        calls["supervise"] += 1
        operation()
        return None

    monkeypatch.setattr(maintenance, "bind_reference_manifest_from_components", bind)
    monkeypatch.setattr(maintenance._plane, "_default_reference_preparer", prepare)
    monkeypatch.setattr(maintenance, "_run_supervised", supervise)

    result = maintenance._bound_or_prepare_reference_manifest(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/test"},
        preparation_cutoff=cutoff,
    )

    assert result is manifest
    assert calls == {"bind": 2, "prepare": 1, "supervise": 1}


def test_legacy_refresh_uses_supervised_provider_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    cutoff = datetime.now(timezone.utc)
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    manifest = SimpleNamespace(manifest_id="manifest-qualified")
    public = lambda _timestamp: SimpleNamespace(state="available")
    discovery = lambda _timestamp: None
    expected = object()

    monkeypatch.setattr(maintenance, "_supervised_public_collector", lambda _values: public)
    monkeypatch.setattr(maintenance, "_supervised_discovery_runner", lambda _values: discovery)

    def legacy(**kwargs):
        assert kwargs["as_of"] == cutoff
        assert kwargs["values"] == values
        assert kwargs["public_collector"] is public
        assert kwargs["discovery"] is discovery
        assert kwargs["reference_preparer"](values) is manifest
        return expected

    monkeypatch.setattr(
        maintenance._legacy_maintenance,
        "maintain_continuous_evidence_plane",
        legacy,
    )

    assert maintenance._legacy_refresh(
        requested=cutoff,
        values=values,
        reference_manifest=manifest,
    ) is expected
