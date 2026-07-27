"""Deterministic release command, timeout, and diagnostic tests."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from operations.release_validation import (
    ReleaseValidationRunner,
    ReleaseValidationStep,
)
from run_release_validation import _steps

UTC = timezone.utc


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


class Monotonic:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        current = self.value
        self.value += 0.25
        return current


def test_release_plan_is_one_ordered_bounded_command_surface() -> None:
    host = _steps(include_container=False)
    complete = _steps(include_container=True)

    assert tuple(item.name for item in host) == (
        "compile_python",
        "initialize_platform",
        "validate_daily_plan",
        "run_intelligence",
        "full_test_suite",
    )
    assert tuple(item.name for item in complete[-3:]) == (
        "build_validation_image",
        "run_container_acceptance",
        "build_runtime_image",
    )
    assert all(item.timeout_seconds > 0 for item in complete)
    assert not any("run_regime.py" in item.command for item in complete)


def test_release_runner_persists_incremental_pass_report(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] > 0
        assert kwargs["env"]["PYTHONHASHSEED"] == "0"
        return subprocess.CompletedProcess(command, 0, "passed\n", "")

    report_path = tmp_path / "release.json"
    runner = ReleaseValidationRunner(
        steps=(
            ReleaseValidationStep("first", ("python", "first.py"), 10),
            ReleaseValidationStep("second", ("python", "second.py"), 20),
        ),
        report_path=report_path,
        working_directory=tmp_path,
        environment={"PYTHONHASHSEED": "0", "TZ": "UTC", "LC_ALL": "C.UTF-8"},
        run_command=run,
        clock=Clock(),
        monotonic=Monotonic(),
    )

    report = runner.run()
    persisted = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["status"] == "passed"
    assert persisted == report
    assert report["passed_steps"] == 2
    assert report["failed_steps"] == 0
    assert calls == [["python", "first.py"], ["python", "second.py"]]
    assert report["real_money_authorized"] is False
    assert report["performance_claims_permitted"] is False


def test_release_runner_fails_fast_and_preserves_bounded_diagnostics(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def run(command, **kwargs):
        del kwargs
        calls.append(command[1])
        if command[1] == "fail.py":
            return subprocess.CompletedProcess(
                command,
                7,
                "x" * 200,
                "failure detail",
            )
        return subprocess.CompletedProcess(command, 0, "unexpected", "")

    report = ReleaseValidationRunner(
        steps=(
            ReleaseValidationStep("failure", ("python", "fail.py"), 10),
            ReleaseValidationStep("must_not_run", ("python", "later.py"), 10),
        ),
        report_path=tmp_path / "release.json",
        working_directory=tmp_path,
        environment={},
        maximum_diagnostic_characters=40,
        run_command=run,
        clock=Clock(),
        monotonic=Monotonic(),
    ).run()

    assert report["status"] == "failed"
    assert calls == ["fail.py"]
    assert report["failed_steps"] == 1
    result = report["steps"][0]
    assert result["return_code"] == 7
    assert result["stdout"].endswith("x" * 40)
    assert "earlier characters omitted" in result["stdout"]
    assert result["stderr"] == "failure detail"


def test_release_runner_classifies_timeout_and_does_not_continue(
    tmp_path: Path,
) -> None:
    calls = 0

    def run(command, **kwargs):
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(
            command,
            kwargs["timeout"],
            output="partial stdout",
            stderr="timeout detail",
        )

    report = ReleaseValidationRunner(
        steps=(
            ReleaseValidationStep("timeout", ("python", "slow.py"), 1),
            ReleaseValidationStep("later", ("python", "later.py"), 1),
        ),
        report_path=tmp_path / "release.json",
        working_directory=tmp_path,
        environment={},
        run_command=run,
        clock=Clock(),
        monotonic=Monotonic(),
    ).run()

    assert calls == 1
    assert report["status"] == "failed"
    assert report["timed_out_steps"] == 1
    assert report["steps"][0]["status"] == "timed_out"
    assert report["steps"][0]["return_code"] is None
    assert report["steps"][0]["stdout"] == "partial stdout"
    assert report["steps"][0]["stderr"] == "timeout detail"
