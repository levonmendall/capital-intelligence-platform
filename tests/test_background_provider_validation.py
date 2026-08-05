"""Tests for nonblocking provider-validation refreshes."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from types import SimpleNamespace

import run_background_provider_validation as worker


class FakeProcess:
    pid = 4321

    def __init__(self, *, running: bool = True) -> None:
        self.running = running
        self.terminated = False
        self.waited = False

    def poll(self):
        return None if self.running and not self.terminated else 0

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout=None):
        del timeout
        self.waited = True
        self.running = False
        return 0

    def kill(self) -> None:
        self.terminated = True
        self.running = False


def test_validate_once_persists_governed_report(monkeypatch, tmp_path: Path) -> None:
    report = SimpleNamespace(
        ready=False,
        release="release-123",
        failed_required_checks=("eodhd_exchange_directory",),
    )
    report_path = tmp_path / "provider-validation-report.json"
    calls = []

    monkeypatch.setattr(worker, "validate_live_providers", lambda: report)

    def write(value):
        calls.append(value)
        return report_path

    monkeypatch.setattr(worker, "write_provider_validation_report", write)

    returned_report, returned_path = worker.validate_once()

    assert returned_report is report
    assert returned_path == report_path
    assert calls == [report]


def test_once_mode_returns_failure_without_exposing_provider_detail(
    monkeypatch,
    capsys,
) -> None:
    secret = "do-not-print-this-secret"

    def fail():
        raise RuntimeError(secret)

    monkeypatch.setattr(worker, "validate_once", fail)

    assert worker.main(["--once"]) == 1
    output = capsys.readouterr().out
    assert "RuntimeError" in output
    assert secret not in output


def test_loop_rejects_nonpositive_interval() -> None:
    try:
        worker.run_loop(interval_seconds=0, initial_delay_seconds=0)
    except ValueError as error:
        assert "interval_seconds" in str(error)
    else:
        raise AssertionError("expected interval validation to fail")


def test_release_diagnostic_is_launched_as_a_separate_process(monkeypatch) -> None:
    calls = []
    process = FakeProcess(running=False)

    def popen(command, *, env):
        calls.append((command, env))
        return process

    monkeypatch.setattr(worker.subprocess, "Popen", popen)
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_ENVIRONMENT", "production")

    returned = worker._run_release_diagnostic()

    assert returned is process
    assert calls[0][0][1:] == ("run_manual_cio_diagnostic.py",)
    assert calls[0][1]["CAPITAL_INTELLIGENCE_ENVIRONMENT"] == "production"


def test_diagnostic_starts_before_first_provider_validation(monkeypatch) -> None:
    events = []
    stopping = Event()
    process = FakeProcess()

    def launch():
        events.append("diagnostic")
        return process

    def validate():
        events.append("validation")
        stopping.set()
        return SimpleNamespace(), Path("report.json")

    monkeypatch.setattr(worker, "_run_release_diagnostic", launch)
    monkeypatch.setattr(worker, "validate_once", validate)

    assert worker.run_loop(
        interval_seconds=60,
        initial_delay_seconds=0,
        stop_event=stopping,
    ) == 0
    assert events == ["diagnostic", "validation"]
    assert process.terminated is True
    assert process.waited is True
