"""Tests for nonblocking provider-validation refreshes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import run_background_provider_validation as worker


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

    def run(command, *, env, check):
        calls.append((command, env, check))
        return SimpleNamespace(returncode=3)

    monkeypatch.setattr(worker.subprocess, "run", run)
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_ENVIRONMENT", "production")

    worker._run_release_diagnostic()

    assert calls[0][0][1:] == ("run_manual_cio_diagnostic.py",)
    assert calls[0][1]["CAPITAL_INTELLIGENCE_ENVIRONMENT"] == "production"
    assert calls[0][2] is False
