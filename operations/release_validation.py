"""Deterministic, bounded release validation with durable diagnostics."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence


class ReleaseValidationError(RuntimeError):
    """Raised when a release validation step cannot complete successfully."""


@dataclass(frozen=True, slots=True)
class ReleaseValidationStep:
    name: str
    command: tuple[str, ...]
    timeout_seconds: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("release validation step name cannot be empty")
        if not isinstance(self.command, tuple) or not self.command or not all(
            isinstance(item, str) and item for item in self.command
        ):
            raise TypeError("release validation command must be a non-empty tuple")
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds,
            int,
        ):
            raise TypeError("timeout_seconds must be an integer")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class ReleaseValidationStepResult:
    name: str
    command: tuple[str, ...]
    status: str
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    timeout_seconds: int
    return_code: int | None
    stdout: str
    stderr: str

    def __post_init__(self) -> None:
        if self.status not in {"passed", "failed", "timed_out"}:
            raise ValueError("unsupported release validation step status")
        if self.completed_at < self.started_at:
            raise ValueError("release validation completion cannot predate start")
        if self.duration_seconds < 0:
            raise ValueError("release validation duration cannot be negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "command": list(self.command),
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": round(self.duration_seconds, 6),
            "timeout_seconds": self.timeout_seconds,
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def _bounded(value: str | bytes | None, *, maximum_characters: int) -> str:
    if value is None:
        return ""
    decoded = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    if len(decoded) <= maximum_characters:
        return decoded
    omitted = len(decoded) - maximum_characters
    return f"[... {omitted} earlier characters omitted ...]\n" + decoded[-maximum_characters:]


class ReleaseValidationRunner:
    """Run an ordered release plan and persist a report after every step."""

    def __init__(
        self,
        *,
        steps: Sequence[ReleaseValidationStep],
        report_path: str | Path,
        working_directory: str | Path,
        environment: Mapping[str, str] | None = None,
        maximum_diagnostic_characters: int = 20_000,
        run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.steps = tuple(steps)
        if not self.steps:
            raise ValueError("release validation requires at least one step")
        names = tuple(item.name for item in self.steps)
        if len(names) != len(set(names)):
            raise ValueError("release validation step names must be unique")
        self.report_path = Path(report_path)
        self.working_directory = Path(working_directory)
        self.environment = dict(environment or os.environ)
        if maximum_diagnostic_characters < 1:
            raise ValueError("maximum_diagnostic_characters must be positive")
        self.maximum_diagnostic_characters = maximum_diagnostic_characters
        self.run_command = run_command
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic

    def _report(
        self,
        *,
        started_at: datetime,
        results: Sequence[ReleaseValidationStepResult],
        status: str,
    ) -> dict[str, object]:
        completed_at = self.clock()
        return {
            "schema_version": "capital-intelligence-release-validation.v1",
            "status": status,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "working_directory": str(self.working_directory),
            "python_hash_seed": self.environment.get("PYTHONHASHSEED"),
            "timezone": self.environment.get("TZ"),
            "locale": self.environment.get("LC_ALL"),
            "steps": [item.to_dict() for item in results],
            "passed_steps": sum(item.status == "passed" for item in results),
            "failed_steps": sum(item.status == "failed" for item in results),
            "timed_out_steps": sum(item.status == "timed_out" for item in results),
            "real_money_authorized": False,
            "performance_claims_permitted": False,
        }

    def _write_report(self, report: Mapping[str, object]) -> None:
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.report_path.with_suffix(self.report_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(dict(report), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.report_path)

    def run(self) -> dict[str, object]:
        started_at = self.clock()
        results: list[ReleaseValidationStepResult] = []
        self._write_report(
            self._report(started_at=started_at, results=results, status="running")
        )
        for step in self.steps:
            step_started = self.clock()
            monotonic_started = self.monotonic()
            try:
                completed = self.run_command(
                    list(step.command),
                    cwd=self.working_directory,
                    env=self.environment,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=step.timeout_seconds,
                )
            except subprocess.TimeoutExpired as error:
                step_completed = self.clock()
                result = ReleaseValidationStepResult(
                    name=step.name,
                    command=step.command,
                    status="timed_out",
                    started_at=step_started,
                    completed_at=step_completed,
                    duration_seconds=max(0.0, self.monotonic() - monotonic_started),
                    timeout_seconds=step.timeout_seconds,
                    return_code=None,
                    stdout=_bounded(
                        error.stdout,
                        maximum_characters=self.maximum_diagnostic_characters,
                    ),
                    stderr=_bounded(
                        error.stderr,
                        maximum_characters=self.maximum_diagnostic_characters,
                    ),
                )
                results.append(result)
                report = self._report(
                    started_at=started_at,
                    results=results,
                    status="failed",
                )
                self._write_report(report)
                return report
            step_completed = self.clock()
            result = ReleaseValidationStepResult(
                name=step.name,
                command=step.command,
                status="passed" if completed.returncode == 0 else "failed",
                started_at=step_started,
                completed_at=step_completed,
                duration_seconds=max(0.0, self.monotonic() - monotonic_started),
                timeout_seconds=step.timeout_seconds,
                return_code=completed.returncode,
                stdout=_bounded(
                    completed.stdout,
                    maximum_characters=self.maximum_diagnostic_characters,
                ),
                stderr=_bounded(
                    completed.stderr,
                    maximum_characters=self.maximum_diagnostic_characters,
                ),
            )
            results.append(result)
            status = "running" if result.status == "passed" else "failed"
            report = self._report(
                started_at=started_at,
                results=results,
                status=status,
            )
            self._write_report(report)
            if result.status != "passed":
                return report
        report = self._report(
            started_at=started_at,
            results=results,
            status="passed",
        )
        self._write_report(report)
        return report


__all__ = [
    "ReleaseValidationError",
    "ReleaseValidationRunner",
    "ReleaseValidationStep",
    "ReleaseValidationStepResult",
]
