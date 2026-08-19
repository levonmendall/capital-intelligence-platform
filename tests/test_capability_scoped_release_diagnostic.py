from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from operations import capability_scoped_release_diagnostic as runtime


AS_OF = datetime(2026, 8, 19, 20, 30, tzinfo=timezone.utc)


def test_capability_reference_manifest_is_bound_to_fresh_operating_snapshot(
    monkeypatch, tmp_path
):
    instruments = (
        SimpleNamespace(execution_asset_class=SimpleNamespace(value="us_equity")),
        SimpleNamespace(execution_asset_class=SimpleNamespace(value="us_equity")),
        SimpleNamespace(execution_asset_class=SimpleNamespace(value="crypto")),
    )
    state_path = tmp_path / "capability_operating_evidence" / "latest.json"
    evidence = SimpleNamespace(
        snapshot_id="snapshot-operating-123",
        as_of=AS_OF,
        universe=SimpleNamespace(instruments=instruments),
        state_path=state_path,
    )
    monkeypatch.setattr(
        runtime,
        "load_capability_operating_evidence",
        lambda **_kwargs: evidence,
    )
    values = {
        "RENDER": "true",
        "CAPITAL_INTELLIGENCE_RELEASE": "abc123",
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
    }

    manifest = runtime.load_capability_operating_reference_manifest(values)

    assert manifest.manifest_id == "capability-operating:snapshot-operating-123"
    assert manifest.release == "abc123"
    assert manifest.captured_at == AS_OF
    assert manifest.path == state_path
    assert manifest.eodhd_exchanges == ()
    assert manifest.futures_roots == ()
    assert manifest.catalog_counts == (("crypto", 1), ("us_equity", 2))
    assert (
        values["CAPITAL_INTELLIGENCE_CIO_PAPER_EVIDENCE_SNAPSHOT_ID"]
        == "snapshot-operating-123"
    )


def test_capability_scope_is_default_on_render_but_explicit_false_wins():
    assert runtime.capability_scoped_operation_enabled({"RENDER": "true"}) is True
    assert (
        runtime.capability_scoped_operation_enabled(
            {
                "RENDER": "true",
                "CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION": "false",
            }
        )
        is False
    )


def test_installed_release_environment_removes_legacy_all_market_gate():
    bootstrap = SimpleNamespace()
    bootstrap._release_diagnostic_environment = lambda _values: {
        "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true",
        "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_MARKET_DISCOVERY": "true",
        "CAPITAL_INTELLIGENCE_DISCOVERY_REQUIRE_COMPLETE_MARKET_COVERAGE": "true",
    }
    bootstrap._run_release_diagnostic_with_live_audit = lambda *_args, **_kwargs: 0
    bootstrap._publish_release_diagnostic_audit = lambda _values: 0
    bootstrap._log = lambda *_args, **_kwargs: None
    memory_safe = SimpleNamespace(render_bootstrap=bootstrap)

    runtime.install(memory_safe)
    diagnostic = bootstrap._release_diagnostic_environment({"RENDER": "true"})

    assert diagnostic["CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION"] == "true"
    assert diagnostic["CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY"] == "false"
    assert (
        diagnostic["CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_MARKET_DISCOVERY"]
        == "false"
    )
    assert (
        diagnostic["CAPITAL_INTELLIGENCE_DISCOVERY_REQUIRE_COMPLETE_MARKET_COVERAGE"]
        == "false"
    )


def test_singleflight_observes_owned_same_release_instead_of_starting_second_child(
    monkeypatch,
):
    request = SimpleNamespace(
        request_id="request-1",
        state="in_progress",
        requested_by="render-release:abc123",
    )
    terminal = SimpleNamespace(
        request_id="request-1",
        state="completed",
        requested_by="render-release:abc123",
    )
    sequence = iter((request, terminal))
    latest = {"value": terminal}

    def read_latest(**_kwargs):
        try:
            latest["value"] = next(sequence)
        except StopIteration:
            pass
        return latest["value"]

    monkeypatch.setattr(runtime, "latest_manual_cio_diagnostic", read_latest)
    monkeypatch.setattr(runtime, "_active_owner_exists", lambda *_args, **_kwargs: True)

    published: list[object] = []
    result = runtime._coalesce_running_diagnostic(
        {
            "RENDER": "true",
            "CAPITAL_INTELLIGENCE_RELEASE": "abc123",
        },
        publish_audit=lambda values: published.append(values),
        refresh_seconds=0.1,
    )

    assert result == 0
    assert published


def test_singleflight_falls_back_to_normal_recovery_when_owner_is_gone(monkeypatch):
    request = SimpleNamespace(
        request_id="request-stale",
        state="in_progress",
        requested_by="render-release:abc123",
    )
    monkeypatch.setattr(
        runtime,
        "latest_manual_cio_diagnostic",
        lambda **_kwargs: request,
    )
    monkeypatch.setattr(runtime, "_active_owner_exists", lambda *_args, **_kwargs: False)

    result = runtime._coalesce_running_diagnostic(
        {
            "RENDER": "true",
            "CAPITAL_INTELLIGENCE_RELEASE": "abc123",
        },
        publish_audit=lambda _values: None,
        refresh_seconds=0.1,
    )

    assert result is None


def test_owner_lease_requires_matching_live_process(tmp_path):
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    lease = tmp_path / "manual-cio-diagnostic-owner.json"
    lease.write_text(
        '{"request_id":"request-live","pid":%d}\n' % os.getpid(),
        encoding="utf-8",
    )

    assert runtime._active_owner_exists("request-live", values) is True
    assert runtime._active_owner_exists("different-request", values) is False


def test_installed_singleflight_does_not_invoke_original_runner_when_coalesced(
    monkeypatch,
):
    calls = {"original": 0}
    logs: list[tuple[str, dict[str, object]]] = []
    current = SimpleNamespace(
        request_id="request-1",
        state="in_progress",
        requested_by="render-release:abc123",
    )

    def original_runner(*_args, **_kwargs):
        calls["original"] += 1
        return 99

    bootstrap = SimpleNamespace()
    bootstrap._release_diagnostic_environment = lambda values: dict(values)
    bootstrap._run_release_diagnostic_with_live_audit = original_runner
    bootstrap._publish_release_diagnostic_audit = lambda _values: 0
    bootstrap._log = lambda event, **kwargs: logs.append((event, kwargs))
    memory_safe = SimpleNamespace(render_bootstrap=bootstrap)

    monkeypatch.setattr(runtime, "_coalesce_running_diagnostic", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        runtime,
        "latest_manual_cio_diagnostic",
        lambda **_kwargs: current,
    )

    runtime.install(memory_safe)
    result = bootstrap._run_release_diagnostic_with_live_audit(
        ("python", "run_bounded_manual_cio_diagnostic.py"),
        diagnostic_values={
            "RENDER": "true",
            "CAPITAL_INTELLIGENCE_RELEASE": "abc123",
        },
    )

    assert result == 0
    assert calls["original"] == 0
    assert logs[-1][0] == "manual_cio_release_diagnostic_singleflight_observed"
    assert logs[-1][1]["competing_child_started"] is False
    assert logs[-1][1]["complete_all_market_coverage_required"] is False
