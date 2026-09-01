from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from operations import capability_operating_retry_refresh as runtime
from operations.manual_cio_diagnostic import (
    latest_manual_cio_diagnostic,
    request_manual_cio_diagnostic,
)


def _request(values, *, now: datetime, age_seconds: float) -> None:
    request_manual_cio_diagnostic(
        requested_by=f"render-release:{values['CAPITAL_INTELLIGENCE_RELEASE']}",
        now=now - timedelta(seconds=age_seconds),
        values=values,
    )


def test_expired_pending_request_fails_before_refresh_or_child(tmp_path, monkeypatch):
    now = datetime(2026, 8, 23, 23, 5, tzinfo=timezone.utc)
    values = {
        "RENDER": "true",
        "CAPITAL_INTELLIGENCE_RELEASE": "abc123",
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_TIMEOUT_SECONDS": "30",
    }
    _request(values, now=now, age_seconds=31)
    calls = {"refresh": 0, "child": 0}
    logs = []

    def original_runner(*_args, **_kwargs):
        calls["child"] += 1
        return 0

    def injected_prequalify(_values):
        calls["refresh"] += 1
        return True

    bootstrap = SimpleNamespace(
        _run_release_diagnostic_with_live_audit=original_runner,
        _release_diagnostic_retryable=lambda _return_code: True,
        _log=lambda event, **kwargs: logs.append((event, kwargs)),
    )
    memory_safe = SimpleNamespace(
        render_bootstrap=bootstrap,
        _prequalify_capability_operating_evidence=injected_prequalify,
    )
    monkeypatch.setattr(runtime, "_utc_now", lambda: now)
    runtime.install(memory_safe)

    result = bootstrap._run_release_diagnostic_with_live_audit(
        ("python", "run_bounded_manual_cio_diagnostic.py"),
        diagnostic_values=values,
    )

    latest = latest_manual_cio_diagnostic(values=values)
    assert result == 124
    assert calls == {"refresh": 0, "child": 0}
    assert latest is not None and latest.state == "failed"
    assert latest.completed_at == now
    assert "before bounded CIO child startup" in str(latest.detail)
    assert bootstrap._release_diagnostic_retryable(124) is False
    assert bootstrap._release_diagnostic_retryable(69) is True
    assert logs[-1][0] == "manual_cio_release_governed_deadline_exhausted"
    assert logs[-1][1]["pending_request_finalized"] is True


def test_child_receives_only_remaining_governed_time(tmp_path, monkeypatch):
    now = datetime(2026, 8, 23, 23, 5, tzinfo=timezone.utc)
    values = {
        "RENDER": "true",
        "CAPITAL_INTELLIGENCE_RELEASE": "abc123",
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_TIMEOUT_SECONDS": "1800",
    }
    _request(values, now=now, age_seconds=600)
    commands = []

    def original_runner(command, **_kwargs):
        commands.append(tuple(command))
        return 0

    bootstrap = SimpleNamespace(
        _run_release_diagnostic_with_live_audit=original_runner,
        _log=lambda *_args, **_kwargs: None,
    )
    memory_safe = SimpleNamespace(render_bootstrap=bootstrap)
    monkeypatch.setattr(runtime, "_utc_now", lambda: now)
    monkeypatch.setattr(
        runtime,
        "load_capability_operating_reference_manifest",
        lambda _values: object(),
    )
    runtime.install(memory_safe)

    result = bootstrap._run_release_diagnostic_with_live_audit(
        ("python", "run_bounded_manual_cio_diagnostic.py"),
        diagnostic_values=values,
    )

    assert result == 0
    command = commands[0]
    index = command.index("--timeout-seconds")
    assert float(command[index + 1]) == 1200.0


def test_forced_retry_cannot_reset_release_lifecycle_deadline(tmp_path, monkeypatch):
    now = datetime(2026, 8, 23, 23, 5, tzinfo=timezone.utc)
    values = {
        "RENDER": "true",
        "CAPITAL_INTELLIGENCE_RELEASE": "abc123",
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_TIMEOUT_SECONDS": "1800",
        "CAPITAL_INTELLIGENCE_RELEASE_DIAGNOSTIC_LIFECYCLE_STARTED_AT": (
            now - timedelta(seconds=1801)
        ).isoformat(),
    }
    calls = {"child": 0}
    logs = []

    def original_runner(*_args, **_kwargs):
        calls["child"] += 1
        return 0

    bootstrap = SimpleNamespace(
        _run_release_diagnostic_with_live_audit=original_runner,
        _release_diagnostic_retryable=lambda _return_code: True,
        _log=lambda event, **kwargs: logs.append((event, kwargs)),
    )
    memory_safe = SimpleNamespace(render_bootstrap=bootstrap)
    monkeypatch.setattr(runtime, "_utc_now", lambda: now)
    monkeypatch.setattr(
        runtime,
        "load_capability_operating_reference_manifest",
        lambda _values: object(),
    )
    runtime.install(memory_safe)

    result = bootstrap._run_release_diagnostic_with_live_audit(
        ("python", "run_bounded_manual_cio_diagnostic.py", "--force"),
        diagnostic_values=values,
    )

    assert result == 124
    assert calls == {"child": 0}
    assert logs[-1][0] == "manual_cio_release_governed_deadline_exhausted"
    assert logs[-1][1]["pending_request_finalized"] is False
    assert bootstrap._release_diagnostic_retryable(124) is False


def test_replacement_request_uses_earlier_release_lifecycle_start(tmp_path, monkeypatch):
    now = datetime(2026, 8, 23, 23, 5, tzinfo=timezone.utc)
    values = {
        "RENDER": "true",
        "CAPITAL_INTELLIGENCE_RELEASE": "abc123",
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_TIMEOUT_SECONDS": "1800",
        "CAPITAL_INTELLIGENCE_RELEASE_DIAGNOSTIC_LIFECYCLE_STARTED_AT": (
            now - timedelta(seconds=600)
        ).isoformat(),
    }
    _request(values, now=now, age_seconds=0)
    commands = []

    bootstrap = SimpleNamespace(
        _run_release_diagnostic_with_live_audit=lambda command, **_kwargs: (
            commands.append(tuple(command)) or 0
        ),
        _log=lambda *_args, **_kwargs: None,
    )
    memory_safe = SimpleNamespace(render_bootstrap=bootstrap)
    monkeypatch.setattr(runtime, "_utc_now", lambda: now)
    monkeypatch.setattr(
        runtime,
        "load_capability_operating_reference_manifest",
        lambda _values: object(),
    )
    runtime.install(memory_safe)

    assert bootstrap._run_release_diagnostic_with_live_audit(
        ("python", "run_bounded_manual_cio_diagnostic.py", "--force"),
        diagnostic_values=values,
    ) == 0
    command = commands[0]
    index = command.index("--timeout-seconds")
    assert float(command[index + 1]) == 1200.0


def test_late_refresh_batch_is_capped_to_remaining_deadline(tmp_path, monkeypatch):
    now = datetime(2026, 8, 23, 23, 5, tzinfo=timezone.utc)
    values = {
        "RENDER": "true",
        "CAPITAL_INTELLIGENCE_RELEASE": "abc123",
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_TIMEOUT_SECONDS": "1800",
        "CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_ATTEMPTS": "3",
        "CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_RETRY_SECONDS": "15",
        "CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_PASS_TIMEOUT_SECONDS": "480",
    }
    _request(values, now=now, age_seconds=1680)
    captured = {}

    def stale(_values):
        raise RuntimeError("stale")

    def fake_prequalify(_memory_safe, bounded_values):
        captured.update(bounded_values)
        return False

    monkeypatch.setattr(runtime, "_utc_now", lambda: now)
    monkeypatch.setattr(runtime, "load_capability_operating_reference_manifest", stale)
    monkeypatch.setattr(
        "operations.capability_scoped_render_bootstrap.prequalify_capability_operating_evidence",
        fake_prequalify,
    )
    bootstrap = SimpleNamespace(
        _run_release_diagnostic_with_live_audit=lambda *_args, **_kwargs: 0,
        _log=lambda *_args, **_kwargs: None,
    )
    memory_safe = SimpleNamespace(
        render_bootstrap=bootstrap,
        _positive_int=lambda *_args, **_kwargs: 1,
        _nonnegative_seconds=lambda *_args, **_kwargs: 0.0,
    )
    runtime.install(memory_safe)

    result = bootstrap._run_release_diagnostic_with_live_audit(
        ("python", "run_bounded_manual_cio_diagnostic.py"),
        diagnostic_values=values,
    )

    assert result == 69
    assert captured["CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_ATTEMPTS"] == "3"
    assert float(
        captured["CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_SUBPROCESS_TIMEOUT_SECONDS"]
    ) < 30.0
    assert float(
        captured["CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_RETRY_SECONDS"]
    ) == 15.0
