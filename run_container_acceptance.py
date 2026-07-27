"""Validate the fenced 12-stage workflow and canonical CIO integration in-container."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence

import run_daily_operations


ROOT = Path(__file__).resolve().parent
PLAN = ROOT / "deploy" / "canonical-daily-operations.json"
VALIDATION_BINDINGS = (
    ROOT / "deploy" / "canonical-daily-stage-bindings.validation.json"
)


def _run_daily_validation(database: Path) -> dict[str, object]:
    os.environ["CAPITAL_INTELLIGENCE_DAILY_STAGE_BINDINGS"] = str(
        VALIDATION_BINDINGS
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = run_daily_operations.main(
            (
                "--plan",
                str(PLAN),
                "--database",
                str(database),
                "--worker-identifier",
                "container-acceptance-worker",
                "--lease-seconds",
                "30",
                "--lease-heartbeat-seconds",
                "1",
                "--operation-id",
                "canonical-daily:container-acceptance",
                "--idempotency-key",
                "canonical-daily:container-acceptance:process-v1",
                "--scheduled-for",
                "2026-07-27T00:00:00+00:00",
                "--decision-timestamp",
                "2026-07-27T01:00:00+00:00",
                "--knowledge-cutoff",
                "2026-07-27T01:00:00+00:00",
                "--started-at",
                "2026-07-27T02:00:00+00:00",
                "--operation-timezone",
                "UTC",
                "--operation-hour",
                "0",
                "--process-version",
                "capital-intelligence-investment-process.validation-v1",
                "--code-version",
                "container-acceptance",
            )
        )
    raw = output.getvalue().strip()
    if exit_code != 0:
        raise RuntimeError(
            f"fenced daily workflow exited {exit_code}: {raw or 'no output'}"
        )
    payload = json.loads(raw)
    if payload.get("status") != "completed":
        raise RuntimeError(
            f"fenced daily workflow did not complete: {payload}"
        )
    if len(payload.get("completed_stages", ())) != 12:
        raise RuntimeError("fenced daily workflow did not complete all 12 stages")
    return payload


def _run_canonical_cio_integration(timeout_seconds: int) -> dict[str, object]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_canonical_production_context_adapter.py",
        "--maxfail=1",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            "canonical CIO integration exceeded its container timeout"
        ) from error
    if completed.returncode != 0:
        raise RuntimeError(
            "canonical CIO integration failed:\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return {
        "status": "passed",
        "command": command,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "timeout_seconds": timeout_seconds,
    }


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    try:
        with tempfile.TemporaryDirectory(
            prefix="capital-intelligence-container-acceptance-"
        ) as temporary:
            daily = _run_daily_validation(Path(temporary) / "daily.db")
            cio = _run_canonical_cio_integration(timeout_seconds=300)
        print(
            json.dumps(
                {
                    "status": "passed",
                    "python": sys.version.split()[0],
                    "daily_operation": {
                        "identifier": daily["identifier"],
                        "status": daily["status"],
                        "completed_stages": daily["completed_stages"],
                        "output_identifiers": daily["output_identifiers"],
                    },
                    "canonical_cio_integration": cio,
                    "fixture_only_daily_bindings": True,
                    "real_money_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": str(error),
                    "real_money_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
