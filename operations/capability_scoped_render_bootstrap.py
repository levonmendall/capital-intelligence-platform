"""Install capability evidence as an additional all-market Render requirement.

Release diagnostics require both a complete immutable all-market evidence generation and a
fresh immutable capability-operating snapshot before the CIO request is created. Capability
scope constrains which instruments may be operated on; it never narrows discovery,
certification, or market-coverage requirements.

Both evidence owners remain resource bounded and share the exclusive heavy-memory lane. No
investment rule, threshold, construction, paper-execution, or real-money authority changes.
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


def prequalify_capability_operating_evidence(
    memory_safe,
    diagnostic_values: MutableMapping[str, str],
) -> bool:
    """Require one fresh operating snapshot without rewriting all-market status.

    The comprehensive release prequalifier owns the release-wide generation/status. This
    function owns only the orthogonal operating-capability requirement, preventing the
    narrower snapshot from replacing or downgrading the all-market certification record.
    """

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
    command = (
        sys.executable,
        "run_bounded_capability_operating_evidence.py",
        "--once",
    )

    for attempt in range(1, maximum_attempts + 1):
        memory_safe.render_bootstrap._log(
            "release_operating_evidence_prequalification_starting",
            command=list(command),
            release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            attempt=attempt,
            maximum_attempts=maximum_attempts,
            diagnostic_request_created=False,
            complete_all_market_coverage_required=True,
            paper_only=True,
            real_money_authorized=False,
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
            memory_safe.render_bootstrap._log(
                "release_operating_evidence_prequalification_finished",
                return_code=0,
                release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
                snapshot_id=evidence.snapshot_id,
                instrument_count=len(evidence.universe.instruments),
                holding_only_count=len(evidence.holding_only_symbols),
                comprehensive_all_market_generation_preserved=True,
                complete_all_market_coverage_required=True,
                diagnostic_request_created=False,
                paper_only=True,
                real_money_authorized=False,
                elapsed_seconds=max(
                    0.0,
                    (datetime.now(timezone.utc) - started_at).total_seconds(),
                ),
            )
            return True

        memory_safe.render_bootstrap._log(
            "release_operating_evidence_prequalification_retrying"
            if attempt < maximum_attempts
            else "release_operating_evidence_prequalification_failed",
            return_code=return_code,
            failure_detail=output,
            release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            attempt=attempt,
            maximum_attempts=maximum_attempts,
            complete_all_market_coverage_required=True,
            diagnostic_request_created=False,
            paper_only=True,
            real_money_authorized=False,
        )
        if attempt < maximum_attempts and retry_seconds:
            time.sleep(retry_seconds)

    return False


def install(memory_safe) -> None:
    """Require all-market and capability evidence while keeping concerns independent."""

    if getattr(memory_safe, _INSTALLED_ATTR, False):
        return

    original_managed_processes = memory_safe.memory_safe_managed_processes
    original_prequalify = memory_safe._prequalify_release_evidence
    original_start = memory_safe._start_release_diagnostic_after_prequalification

    os.environ.setdefault("CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PASS_TIMEOUT_SECONDS", "480")
    os.environ.setdefault("CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_INTERVAL_SECONDS", "300")
    os.environ.setdefault("CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_PASS_TIMEOUT_SECONDS", "480")
    os.environ.setdefault("CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_MAX_AGE_SECONDS", "900")

    def prequalify_required_evidence(
        diagnostic_values: MutableMapping[str, str],
    ) -> bool:
        if not _enabled(diagnostic_values):
            return original_prequalify(diagnostic_values)

        # The broad release generation is always first and remains the canonical
        # prequalification status. Operating evidence is an additional fail-closed gate.
        if not original_prequalify(diagnostic_values):
            return False
        return prequalify_capability_operating_evidence(memory_safe, diagnostic_values)

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
            if not prequalify_required_evidence(diagnostic_values):
                return
            memory_safe.render_bootstrap.prime_release_diagnostic_request(values)
            memory_safe.render_bootstrap._run_release_diagnostic_after_readiness(
                values,
                not_before=datetime.now(timezone.utc),
            )

        thread = threading.Thread(
            name="release-all-market-evidence-then-cio-diagnostic",
            target=qualify_then_run,
            daemon=True,
        )
        thread.start()
        memory_safe.render_bootstrap._log(
            "release_required_evidence_prequalification_armed",
            release=values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            diagnostic_request_created=False,
            complete_all_market_coverage_required=True,
            capability_operating_evidence_required=True,
            paper_only=True,
            real_money_authorized=False,
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
                command=(
                    python,
                    "run_bounded_capability_operating_evidence.py",
                    "--loop",
                ),
                critical=False,
                restart_delay_seconds=30,
            )
        )
        return tuple(specs)

    memory_safe._prequalify_release_evidence = prequalify_required_evidence
    memory_safe._start_release_diagnostic_after_prequalification = start_release_diagnostic
    memory_safe.memory_safe_managed_processes = managed_processes
    setattr(memory_safe, _INSTALLED_ATTR, True)


__all__ = ["install", "prequalify_capability_operating_evidence"]
