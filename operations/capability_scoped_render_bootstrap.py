"""Install capability-scoped Render startup semantics without weakening CIO controls.

Release diagnostics require a fresh immutable operating-evidence snapshot before the CIO
request is created. Comprehensive all-market evidence becomes a noncritical background
coverage expander. Both workers remain resource bounded; the comprehensive pass receives a
bounded lane slice so it cannot starve operating evidence beyond its freshness window.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Mapping, MutableMapping

from operations.capability_operating_evidence import (
    CapabilityOperatingEvidenceError,
    load_capability_operating_evidence,
)

_INSTALLED_ATTR = "_capability_scoped_operating_bootstrap_installed"


def _enabled(values: Mapping[str, str]) -> bool:
    raw = values.get("CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION")
    if raw is not None and str(raw).strip():
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    return str(values.get("RENDER") or "").strip().lower() == "true"


def install(memory_safe) -> None:
    """Patch the Render memory-safe bootstrap at its narrow operational seams."""

    if getattr(memory_safe, _INSTALLED_ATTR, False):
        return

    original_managed_processes = memory_safe.memory_safe_managed_processes
    original_prequalify = memory_safe._prequalify_release_evidence
    original_start = memory_safe._start_release_diagnostic_after_prequalification

    # Comprehensive discovery may make incremental progress in the background, but one
    # attempt may not hold the exclusive memory lane long enough to starve two operating
    # evidence cadences. Component/DAG checkpoints make these bounded passes resumable.
    os.environ.setdefault("CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PASS_TIMEOUT_SECONDS", "480")
    os.environ.setdefault("CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_INTERVAL_SECONDS", "300")
    os.environ.setdefault("CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_PASS_TIMEOUT_SECONDS", "480")
    os.environ.setdefault("CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_MAX_AGE_SECONDS", "900")

    def prequalify_operating_evidence(
        diagnostic_values: MutableMapping[str, str],
    ) -> bool:
        if not _enabled(diagnostic_values):
            return original_prequalify(diagnostic_values)

        started_at = datetime.now(timezone.utc)
        maximum_attempts = memory_safe._positive_int(
            diagnostic_values,
            "CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_ATTEMPTS",
            3,
        )
        retry_seconds = memory_safe._nonnegative_seconds(
            diagnostic_values,
            "CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_RETRY_SECONDS",
            15.0,
        )
        status = memory_safe.write_release_evidence_prequalification(
            diagnostic_values,
            state="in_progress",
            stage="evidence_prequalifying",
            started_at=started_at,
            detail=(
                "validating independent capability operating evidence; comprehensive "
                "all-market coverage is not an operating gate"
            ),
            metrics={
                "attempt": 1,
                "maximum_attempts": maximum_attempts,
                "complete_all_market_coverage_required": 0,
            },
        )
        prequalification_id = str(status["prequalification_id"])
        memory_safe.render_bootstrap._publish_release_diagnostic_audit(diagnostic_values)
        command = (
            sys.executable,
            "run_bounded_capability_operating_evidence.py",
            "--once",
        )

        for attempt in range(1, maximum_attempts + 1):
            if attempt > 1:
                memory_safe.write_release_evidence_prequalification(
                    diagnostic_values,
                    state="in_progress",
                    stage="evidence_refresh",
                    prequalification_id=prequalification_id,
                    started_at=started_at,
                    detail=(
                        f"retrying operating evidence qualification attempt {attempt} "
                        f"of {maximum_attempts}"
                    ),
                    metrics={
                        "attempt": attempt,
                        "maximum_attempts": maximum_attempts,
                        "complete_all_market_coverage_required": 0,
                    },
                )
                memory_safe.render_bootstrap._publish_release_diagnostic_audit(
                    diagnostic_values
                )

            memory_safe.render_bootstrap._log(
                "release_operating_evidence_prequalification_starting",
                command=list(command),
                release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
                prequalification_id=prequalification_id,
                attempt=attempt,
                maximum_attempts=maximum_attempts,
                diagnostic_request_created=False,
                complete_all_market_coverage_required=False,
                paper_only=True,
            )

            try:
                completed = subprocess.run(
                    command,
                    env=dict(diagnostic_values),
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                return_code = int(completed.returncode)
                output = str(completed.stdout or "")[-1600:]
            except OSError as error:
                return_code = 2
                output = f"{type(error).__name__}: {error}"

            evidence = None
            if return_code == 0:
                try:
                    evidence = load_capability_operating_evidence(
                        cutoff=datetime.now(timezone.utc),
                        values=diagnostic_values,
                    )
                except CapabilityOperatingEvidenceError as error:
                    output = str(error)

            if return_code == 0 and evidence is not None:
                memory_safe.write_release_evidence_prequalification(
                    diagnostic_values,
                    state="completed",
                    stage="evidence_generation_ready",
                    prequalification_id=prequalification_id,
                    started_at=started_at,
                    detail=(
                        "fresh immutable capability operating evidence ready; "
                        "comprehensive discovery remains asynchronous"
                    ),
                    generation_id=evidence.snapshot_id,
                    metrics={
                        "attempt": attempt,
                        "maximum_attempts": maximum_attempts,
                        "instrument_count": len(evidence.universe.instruments),
                        "holding_only_count": len(evidence.holding_only_symbols),
                        "complete_all_market_coverage_required": 0,
                    },
                )
                memory_safe.render_bootstrap._publish_release_diagnostic_audit(
                    diagnostic_values
                )
                memory_safe.render_bootstrap._log(
                    "release_operating_evidence_prequalification_finished",
                    return_code=0,
                    release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
                    prequalification_id=prequalification_id,
                    snapshot_id=evidence.snapshot_id,
                    instrument_count=len(evidence.universe.instruments),
                    complete_all_market_coverage_required=False,
                    diagnostic_request_created=False,
                    paper_only=True,
                )
                return True

            detail = (
                f"bounded operating evidence qualification returned code {return_code}; "
                f"detail={output}"
            )[:1800]
            if attempt < maximum_attempts:
                memory_safe.write_release_evidence_prequalification(
                    diagnostic_values,
                    state="in_progress",
                    stage="evidence_refresh",
                    prequalification_id=prequalification_id,
                    started_at=started_at,
                    detail=detail + "; retrying",
                    metrics={
                        "attempt": attempt,
                        "maximum_attempts": maximum_attempts,
                        "qualifier_return_code": abs(return_code),
                        "complete_all_market_coverage_required": 0,
                    },
                )
                memory_safe.render_bootstrap._publish_release_diagnostic_audit(
                    diagnostic_values
                )
                if retry_seconds:
                    time.sleep(retry_seconds)
                continue

            memory_safe.write_release_evidence_prequalification(
                diagnostic_values,
                state="failed",
                stage="evidence_prequalification_failed",
                prequalification_id=prequalification_id,
                started_at=started_at,
                detail=detail,
                metrics={
                    "attempt": attempt,
                    "maximum_attempts": maximum_attempts,
                    "qualifier_return_code": abs(return_code),
                    "complete_all_market_coverage_required": 0,
                },
            )
            memory_safe.render_bootstrap._publish_release_diagnostic_audit(
                diagnostic_values
            )
            memory_safe.render_bootstrap._log(
                "release_operating_evidence_prequalification_failed",
                return_code=return_code,
                failure_detail=output,
                release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
                prequalification_id=prequalification_id,
                complete_all_market_coverage_required=False,
                diagnostic_request_created=False,
                paper_only=True,
            )
            return False
        return False

    def start_release_diagnostic(values: MutableMapping[str, str]):
        if not _enabled(values):
            return original_start(values)
        if not memory_safe.render_bootstrap._enabled(
            values,
            "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE",
            default=False,
        ):
            return None

        def qualify_then_run() -> None:
            diagnostic_values = memory_safe.render_bootstrap._release_diagnostic_environment(
                values
            )
            if not prequalify_operating_evidence(diagnostic_values):
                return
            memory_safe.render_bootstrap.prime_release_diagnostic_request(values)
            memory_safe.render_bootstrap._run_release_diagnostic_after_readiness(
                values,
                not_before=datetime.now(timezone.utc),
            )

        thread = threading.Thread(
            name="release-operating-evidence-then-cio-diagnostic",
            target=qualify_then_run,
            daemon=True,
        )
        thread.start()
        memory_safe.render_bootstrap._log(
            "release_operating_evidence_prequalification_armed",
            release=values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            diagnostic_request_created=False,
            complete_all_market_coverage_required=False,
            operating_evidence_required=True,
            paper_only=True,
        )
        return thread

    def managed_processes(*, port: int, python_executable: str | None = None):
        specs = list(
            original_managed_processes(
                port=port,
                python_executable=python_executable,
            )
        )
        if not _enabled(os.environ):
            return tuple(specs)
        if any(spec.name == "capability-operating-evidence" for spec in specs):
            return tuple(specs)
        python = python_executable or sys.executable
        specs.append(
            memory_safe.render_supervisor.ManagedProcess(
                name="capability-operating-evidence",
                command=(python, "run_bounded_capability_operating_evidence.py"),
                critical=False,
                restart_delay_seconds=30,
            )
        )
        return tuple(specs)

    memory_safe._prequalify_release_evidence = prequalify_operating_evidence
    memory_safe._start_release_diagnostic_after_prequalification = start_release_diagnostic
    memory_safe.memory_safe_managed_processes = managed_processes
    setattr(memory_safe, _INSTALLED_ATTR, True)


__all__ = ["install"]
