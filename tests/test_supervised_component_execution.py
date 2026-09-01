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
    run_supervised_components,
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


def test_supervised_component_preserves_safe_remote_failure_metadata() -> None:
    class ProviderError(RuntimeError):
        status_code = 403
        retryable = False

    outcomes = run_supervised_components(
        components={"provider-root": lambda: (_ for _ in ()).throw(ProviderError("denied"))},
        timeout_seconds=1.0,
        maximum_parallel=1,
    )

    failure = outcomes["provider-root"]
    assert isinstance(failure, SupervisedComponentExecutionError)
    assert failure.remote_error_type == "ProviderError"
    assert failure.status_code == 403
    assert failure.retryable is False


def test_supervised_component_batch_overlaps_independent_timeouts() -> None:
    started = time.monotonic()
    outcomes = run_supervised_components(
        components={
            f"hung-{index}": lambda: time.sleep(5.0)
            for index in range(3)
        },
        timeout_seconds=0.05,
        maximum_parallel=3,
    )
    elapsed = time.monotonic() - started

    assert all(isinstance(outcome, SupervisedComponentTimeout) for outcome in outcomes.values())
    assert elapsed < 1.0


def test_reference_binding_reuses_original_cutoff_without_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    manifest = SimpleNamespace(manifest_id="manifest-qualified")
    calls = {"bind": 0}

    def bind(_values, *, now):
        assert now == cutoff
        calls["bind"] += 1
        return manifest

    monkeypatch.setattr(maintenance, "bind_reference_manifest_from_components", bind)

    result, effective_cutoff = maintenance._bound_or_prepare_reference_manifest(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/test"},
        preparation_cutoff=cutoff,
    )

    assert result is manifest
    assert effective_cutoff == cutoff
    assert calls == {"bind": 1}


def test_reference_binding_advances_epoch_after_missing_component_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    manifest = SimpleNamespace(manifest_id="manifest-qualified")
    calls = {"bind": 0, "prepare": 0}
    bind_timestamps: list[datetime] = []

    def bind(_values, *, now):
        bind_timestamps.append(now)
        calls["bind"] += 1
        if calls["bind"] == 1:
            assert now == cutoff
            raise maintenance.ReferenceReadinessError("missing")
        assert now > cutoff
        return manifest

    def prepare(_values):
        calls["prepare"] += 1
        return SimpleNamespace(manifest_id="prepared")

    monkeypatch.setattr(maintenance, "bind_reference_manifest_from_components", bind)
    monkeypatch.setattr(maintenance, "prepare_supervised_reference_prequalification", prepare)
    monkeypatch.setattr(
        maintenance,
        "_run_supervised",
        lambda *_args, **_kwargs: pytest.fail(
            "aggregate reference supervisor must not wrap component supervisors"
        ),
    )

    result, effective_cutoff = maintenance._bound_or_prepare_reference_manifest(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/test"},
        preparation_cutoff=cutoff,
    )

    assert result is manifest
    assert effective_cutoff == bind_timestamps[1]
    assert effective_cutoff > cutoff
    assert calls == {"bind": 2, "prepare": 1}


def test_maintenance_uses_advanced_reference_cutoff_for_remaining_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    requested = datetime(2026, 1, 1, tzinfo=timezone.utc)
    resumed = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
    advanced = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    manifest = SimpleNamespace(manifest_id="manifest-qualified")
    expected = object()

    monkeypatch.setattr(maintenance._plane, "evidence_plane_enabled", lambda _values: True)
    monkeypatch.setattr(maintenance._plane, "load_latest_evidence_plane", lambda _values: None)
    monkeypatch.setattr(maintenance, "_latest_payload", lambda _values: None)
    monkeypatch.setattr(
        maintenance,
        "_resumable_evidence_cutoff",
        lambda _values, *, requested: resumed,
    )

    def bind(_values, *, preparation_cutoff):
        assert preparation_cutoff == resumed
        return manifest, advanced

    def refresh(*, requested, values, reference_manifest):
        assert requested == advanced
        assert values == {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
        assert reference_manifest is manifest
        return expected

    monkeypatch.setattr(maintenance, "_bound_or_prepare_reference_manifest", bind)
    monkeypatch.setattr(maintenance, "_legacy_refresh", refresh)

    assert maintenance.maintain_component_qualified_evidence_plane(
        as_of=requested,
        values=values,
    ) is expected


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
