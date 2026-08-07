"""Regression coverage for the bounded manual CIO diagnostic watchdog."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import run_bounded_manual_cio_diagnostic as watchdog


class CompletedProcess:
    returncode = 3

    def __init__(self) -> None:
        self.wait_calls = []

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        return self.returncode


class TimedOutProcess:
    returncode = None

    def __init__(self) -> None:
        self.wait_calls = []
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if len(self.wait_calls) == 1:
            raise watchdog.subprocess.TimeoutExpired(("python", "diagnostic"), timeout)
        self.returncode = -15
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def test_watchdog_emits_start_and_finish_events(monkeypatch, capsys, tmp_path: Path) -> None:
    process = CompletedProcess()
    calls = []

    def popen(command, *, env, cwd):
        calls.append((command, env, cwd))
        return process

    monkeypatch.setattr(watchdog.subprocess, "Popen", popen)
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-observable",
    }

    assert watchdog.run_bounded_diagnostic(values=values, timeout_seconds=17) == 3

    output = capsys.readouterr().out
    assert "manual_cio_diagnostic_run_started" in output
    assert "manual_cio_diagnostic_process_finished" in output
    assert "release-observable" in output
    assert Path(calls[0][0][1]).name == "run_manual_cio_diagnostic.py"
    assert Path(calls[0][2]) == Path(calls[0][0][1]).parent
    assert process.wait_calls == [17.0]


def test_watchdog_passes_force_only_to_an_explicit_replacement(monkeypatch) -> None:
    commands = []

    def popen(command, *, env, cwd):
        del env, cwd
        commands.append(tuple(command))
        return CompletedProcess()

    monkeypatch.setattr(watchdog.subprocess, "Popen", popen)

    assert watchdog.run_bounded_diagnostic(
        force=True,
        values={"CAPITAL_INTELLIGENCE_RELEASE": "release-retry"},
        timeout_seconds=5,
    ) == 3

    assert commands[0][-1] == "--force"
    assert Path(commands[0][-2]).name == "run_manual_cio_diagnostic.py"


def test_watchdog_times_out_and_closes_claimed_request(monkeypatch, capsys) -> None:
    process = TimedOutProcess()
    existing = SimpleNamespace(
        request_id="request-123",
        state="in_progress",
        cycle_key="canonical-cio:test:event:manual",
        snapshot_identifier=None,
        detail=(
            "governed_progress=deep_market_evidence:international_equity; "
            "decision_eligible_records=417"
        ),
    )
    finish_calls = []

    monkeypatch.setattr(
        watchdog.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        watchdog,
        "latest_manual_cio_diagnostic",
        lambda **_kwargs: existing,
    )

    def finish(request, **kwargs):
        finish_calls.append((request, kwargs))
        return SimpleNamespace(request_id=request.request_id, state="failed")

    monkeypatch.setattr(watchdog, "finish_manual_cio_diagnostic", finish)

    assert watchdog.run_bounded_diagnostic(
        values={"CAPITAL_INTELLIGENCE_RELEASE": "release-timeout"},
        timeout_seconds=2,
    ) == 124

    assert process.terminated is True
    assert process.killed is False
    assert finish_calls[0][0] is existing
    assert finish_calls[0][1]["succeeded"] is False
    assert "last_governed_progress=deep_market_evidence:international_equity" in (
        finish_calls[0][1]["detail"]
    )
    assert "decision_eligible_records=417" in finish_calls[0][1]["detail"]
    output = capsys.readouterr().out
    assert "manual_cio_diagnostic_timed_out" in output
    assert "request-123" in output


def test_timeout_configuration_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        watchdog.run_bounded_diagnostic(
            values={"CAPITAL_INTELLIGENCE_RELEASE": "release-invalid"},
            timeout_seconds=0,
        )
