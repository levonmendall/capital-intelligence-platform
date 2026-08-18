"""Supervise release evidence prequalification by durable child progress.

The Render release bootstrap starts evidence qualification before a CIO request exists.
Individual reference, public-live, and certification-DAG work units already have killable
execution budgets and durable progress journals, but the parent bootstrap historically
waited on the aggregate evidence subprocess with an unbounded ``subprocess.run``. A
coordinator stall could therefore leave production in ``evidence_prequalifying`` forever
while the public audit displayed an unrelated stale child journal.

This module installs a narrow subprocess proxy into the memory-safe Render bootstrap. It
recognizes only the one-shot bounded continuous-evidence command, observes only
credential-safe current-attempt journals, republishes the active parent phase through the
existing integrity-protected release-prequalification record, and terminates the aggregate
process only when *durable progress* has stopped beyond the execution budget of the active
unit. Long all-market work remains valid while progress advances.

Nothing here has investment, candidate, specialist, construction, sizing, execution, or
real-money authority. A parent stall is fail-closed and is transported through the
existing credential-safe failure channel as ``ParentStallTimeout``.
"""

from __future__ import annotations

import json
import math
import os
import signal
import subprocess as _subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from types import ModuleType
from typing import Mapping

from operations.public_live_requirement_qualification import load_public_live_requirement_progress
from operations.release_evidence_prequalification import (
    load_release_certification_dag_progress,
    load_release_evidence_prequalification,
    write_release_evidence_prequalification,
)
from operations.supervised_reference_prequalification import load_reference_prequalification_progress

_FAILURE_EVENT = "continuous_evidence_plane_failure_context"
_EVIDENCE_SCRIPT = "run_bounded_continuous_evidence_plane.py"
_POLL_ENV = "CAPITAL_INTELLIGENCE_RELEASE_EVIDENCE_PARENT_POLL_SECONDS"
_REFERENCE_TIMEOUT_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_REFERENCE_COMPONENT_TIMEOUT_SECONDS"
_REFERENCE_LEGACY_TIMEOUT_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_REFERENCE_TIMEOUT_SECONDS"
_PUBLIC_TIMEOUT_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_PUBLIC_REQUIREMENT_TIMEOUT_SECONDS"
_PUBLIC_LEGACY_TIMEOUT_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_PUBLIC_TIMEOUT_SECONDS"
_DAG_TIMEOUT_ENV = "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_NODE_TIMEOUT_SECONDS"
_STARTUP_STALL_ENV = "CAPITAL_INTELLIGENCE_RELEASE_EVIDENCE_STARTUP_STALL_SECONDS"
_FINALIZER_STALL_ENV = "CAPITAL_INTELLIGENCE_RELEASE_EVIDENCE_FINALIZER_STALL_SECONDS"
_DEFAULT_POLL_SECONDS = 5.0
_DEFAULT_REFERENCE_TIMEOUT_SECONDS = 120.0
_DEFAULT_PUBLIC_TIMEOUT_SECONDS = 75.0
_DEFAULT_DAG_TIMEOUT_SECONDS = 540.0
_DEFAULT_STARTUP_STALL_SECONDS = 180.0
_DEFAULT_FINALIZER_STALL_SECONDS = 900.0
_COMPONENT_MARGIN_SECONDS = 45.0
_DAG_MARGIN_SECONDS = 120.0
_TERMINATION_GRACE_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class PrequalificationProgress:
    phase: str
    component: str
    updated_at: datetime
    state: str
    stall_limit_seconds: float
    metrics: Mapping[str, int]

    @property
    def marker(self) -> tuple[str, str, str, str]:
        return self.phase, self.component, self.state, self.updated_at.isoformat()


def _aware(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _positive_seconds(values: Mapping[str, str], names: tuple[str, ...], default: float) -> float:
    raw = next((str(values.get(name) or os.getenv(name, "")).strip() for name in names if str(values.get(name) or os.getenv(name, "")).strip()), "")
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{names[0]} must be numeric") from error
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{names[0]} must be positive")
    return value


def _nonnegative_metrics(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {str(name): int(item) for name, item in value.items() if isinstance(name, str) and name.strip() and isinstance(item, int) and not isinstance(item, bool) and item >= 0}


def _current(progress: Mapping[str, object] | None, *, boundary: datetime) -> bool:
    updated_at = _aware(progress.get("updated_at")) if isinstance(progress, Mapping) else None
    return updated_at is not None and updated_at >= boundary


def _count_metrics(progress: Mapping[str, object]) -> dict[str, int]:
    names = ("required_count", "qualified_count", "reused_count", "newly_qualified_count", "failed_count", "pending_count")
    return {name: int(progress.get(name) or 0) for name in names if isinstance(progress.get(name), int) and not isinstance(progress.get(name), bool)}


def _reference_progress(values: Mapping[str, str], *, boundary: datetime) -> PrequalificationProgress | None:
    progress = load_reference_prequalification_progress(values)
    if not _current(progress, boundary=boundary):
        return None
    assert progress is not None
    updated_at = _aware(progress.get("updated_at"))
    assert updated_at is not None
    state = str(progress.get("state") or "qualifying").strip().lower()
    active = str(progress.get("active_component") or "").strip()
    phase = "reference_binding" if state == "qualified" and not active else "reference_acquisition"
    component = "release-reference-manifest" if phase == "reference_binding" else active or "reference-controller"
    timeout = _positive_seconds(values, (_REFERENCE_TIMEOUT_ENV, _REFERENCE_LEGACY_TIMEOUT_ENV), _DEFAULT_REFERENCE_TIMEOUT_SECONDS)
    return PrequalificationProgress(phase, component, updated_at, state, max(_DEFAULT_STARTUP_STALL_SECONDS, timeout + _COMPONENT_MARGIN_SECONDS), _count_metrics(progress))


def _public_progress(values: Mapping[str, str], *, boundary: datetime) -> PrequalificationProgress | None:
    progress = load_public_live_requirement_progress(values)
    if not _current(progress, boundary=boundary):
        return None
    assert progress is not None
    updated_at = _aware(progress.get("updated_at"))
    assert updated_at is not None
    state = str(progress.get("state") or "qualifying").strip().lower()
    active = str(progress.get("active_required_information") or "").strip()
    if state == "qualified" and not active:
        return PrequalificationProgress("discovery_bootstrap", "comprehensive-discovery", updated_at, state, _positive_seconds(values, (_STARTUP_STALL_ENV,), _DEFAULT_STARTUP_STALL_SECONDS), _count_metrics(progress))
    timeout = _positive_seconds(values, (_PUBLIC_TIMEOUT_ENV, _PUBLIC_LEGACY_TIMEOUT_ENV), _DEFAULT_PUBLIC_TIMEOUT_SECONDS)
    return PrequalificationProgress("public_live", active or "public-live-controller", updated_at, state, max(120.0, timeout + _COMPONENT_MARGIN_SECONDS), _count_metrics(progress))


def _dag_progress(values: Mapping[str, str], *, boundary: datetime) -> PrequalificationProgress | None:
    # A retry may reuse the original decision epoch. Require a current-attempt journal
    # update, but do not reject a still-valid resumed epoch merely because it predates this
    # child process launch.
    progress = load_release_certification_dag_progress(values, started_at=None)
    if not _current(progress, boundary=boundary):
        return None
    assert progress is not None
    updated_at = _aware(progress.get("updated_at"))
    assert updated_at is not None
    counts = progress.get("counts") if isinstance(progress.get("counts"), Mapping) else {}
    running = int(counts.get("running_nodes") or 0)
    pending = int(counts.get("pending_nodes") or 0)
    failed = int(counts.get("failed_nodes") or 0)
    if running or pending:
        component = str(progress.get("active_node") or progress.get("focus_node") or "certification-dag").strip()
        timeout = _positive_seconds(values, (_DAG_TIMEOUT_ENV,), _DEFAULT_DAG_TIMEOUT_SECONDS)
        return PrequalificationProgress("comprehensive_discovery", component, updated_at, "running", timeout + _DAG_MARGIN_SECONDS, _nonnegative_metrics(counts))
    if failed:
        component = str(progress.get("blocking_node") or progress.get("focus_node") or "certification-dag").strip()
        return PrequalificationProgress("comprehensive_discovery", component, updated_at, "failed", _positive_seconds(values, (_STARTUP_STALL_ENV,), _DEFAULT_STARTUP_STALL_SECONDS), _nonnegative_metrics(counts))
    return PrequalificationProgress("global_finalizer", "provider-free-finalizer", updated_at, "running", _positive_seconds(values, (_FINALIZER_STALL_ENV,), _DEFAULT_FINALIZER_STALL_SECONDS), _nonnegative_metrics(counts))


def observe_current_prequalification_progress(values: Mapping[str, str], *, started_at: datetime) -> PrequalificationProgress:
    """Return the newest credential-safe journal updated by the current child attempt."""
    boundary = started_at.astimezone(timezone.utc)
    candidates = [item for item in (_reference_progress(values, boundary=boundary), _public_progress(values, boundary=boundary), _dag_progress(values, boundary=boundary)) if item is not None]
    if candidates:
        return max(candidates, key=lambda item: item.updated_at)
    return PrequalificationProgress("reference_binding", "release-reference-manifest", boundary, "starting", _positive_seconds(values, (_STARTUP_STALL_ENV,), _DEFAULT_STARTUP_STALL_SECONDS), {})


def _public_stage(progress: PrequalificationProgress) -> str:
    return "reference_components" if progress.phase.startswith("reference") else "evidence_refresh"


def _publish_parent_progress(values: Mapping[str, str], *, progress: PrequalificationProgress) -> None:
    status = load_release_evidence_prequalification(values)
    if not isinstance(status, Mapping) or str(status.get("state") or "").lower() not in {"pending", "in_progress"}:
        return
    prequalification_id = str(status.get("prequalification_id") or "").strip()
    started_at = _aware(status.get("started_at"))
    if not prequalification_id or started_at is None:
        return
    metrics = _nonnegative_metrics(status.get("metrics"))
    metrics.update(progress.metrics)
    write_release_evidence_prequalification(values, state="in_progress", stage=_public_stage(progress), prequalification_id=prequalification_id, started_at=started_at, detail=(f"governed_prequalification_phase={progress.phase}; component={progress.component}; state={progress.state}")[:1000], metrics=metrics)


def _is_evidence_command(command: object) -> bool:
    if isinstance(command, (str, bytes)):
        return _EVIDENCE_SCRIPT in str(command)
    try:
        return any(str(item).endswith(_EVIDENCE_SCRIPT) for item in command)  # type: ignore[union-attr]
    except TypeError:
        return False


def _stop_process_group(process: _subprocess.Popen[object]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix" and process.pid is not None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            process.terminate()
    else:
        process.terminate()
    try:
        process.wait(timeout=_TERMINATION_GRACE_SECONDS)
    except _subprocess.TimeoutExpired:
        if os.name == "posix" and process.pid is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
        else:
            process.kill()
        process.wait(timeout=_TERMINATION_GRACE_SECONDS)


def _stall_failure_line(progress: PrequalificationProgress, *, stall_seconds: float) -> str:
    return json.dumps({"event": _FAILURE_EVENT, "error_type": "ParentStallTimeout", "failure_stage": "release_prequalification_parent_watchdog", "error_detail": ("release evidence prequalification made no durable progress; failure_type=ParentStallTimeout; " f"prequalification_phase={progress.phase}; component={progress.component}; " f"stall_seconds={int(max(0.0, stall_seconds))}; stall_limit_seconds={int(progress.stall_limit_seconds)}"), "credential_safe": True, "paper_only": True, "real_money_authorized": False}, sort_keys=True)


def _watched_run(command: object, *, original_run, **kwargs):
    env = dict(kwargs.get("env") or os.environ)
    status = load_release_evidence_prequalification(env)
    if not isinstance(status, Mapping) or _aware(status.get("started_at")) is None:
        return original_run(command, **kwargs)
    attempt_started_at = datetime.now(timezone.utc)
    poll_seconds = _positive_seconds(env, (_POLL_ENV,), _DEFAULT_POLL_SECONDS)
    popen_kwargs = dict(kwargs)
    popen_kwargs.pop("check", None)
    requested_stderr = popen_kwargs.pop("stderr", None)
    if popen_kwargs.pop("capture_output", False):
        popen_kwargs.pop("stdout", None)
    text_mode = bool(popen_kwargs.get("text") or popen_kwargs.get("universal_newlines"))
    mode = "w+t" if text_mode else "w+b"
    with tempfile.TemporaryFile(mode=mode) as error_stream:
        process = _subprocess.Popen(command, stderr=error_stream, start_new_session=(os.name == "posix"), **popen_kwargs)
        last_marker: tuple[str, str, str, str] | None = None
        last_progress_at = time.monotonic()
        last_progress: PrequalificationProgress | None = None
        while process.poll() is None:
            progress = observe_current_prequalification_progress(env, started_at=attempt_started_at)
            if progress.marker != last_marker:
                last_marker = progress.marker
                last_progress_at = time.monotonic()
                last_progress = progress
                _publish_parent_progress(env, progress=progress)
            stalled_for = time.monotonic() - last_progress_at
            if stalled_for >= progress.stall_limit_seconds:
                _stop_process_group(process)
                failure_line = _stall_failure_line(progress, stall_seconds=stalled_for)
                error_stream.write(("\n" + failure_line + "\n") if text_mode else ("\n" + failure_line + "\n").encode("utf-8"))
                error_stream.flush(); error_stream.seek(0)
                captured = error_stream.read()
                return _subprocess.CompletedProcess(command, 124, stdout=None, stderr=captured if requested_stderr == _subprocess.PIPE else None)
            time.sleep(min(poll_seconds, max(0.05, progress.stall_limit_seconds / 4.0)))
        if last_progress is not None:
            _publish_parent_progress(env, progress=last_progress)
        error_stream.flush(); error_stream.seek(0)
        captured = error_stream.read()
        completed = _subprocess.CompletedProcess(command, int(process.returncode or 0), stdout=None, stderr=captured if requested_stderr == _subprocess.PIPE else None)
        if kwargs.get("check") and completed.returncode:
            raise _subprocess.CalledProcessError(completed.returncode, command, output=completed.stdout, stderr=completed.stderr)
        return completed


class _SubprocessProxy:
    def __init__(self, module: ModuleType) -> None:
        self._module = module
        self._original_run = module.run

    def __getattr__(self, name: str):
        return getattr(self._module, name)

    def run(self, command, *args, **kwargs):
        if args or not _is_evidence_command(command):
            return self._original_run(command, *args, **kwargs)
        return _watched_run(command, original_run=self._original_run, **kwargs)


def install_release_prequalification_parent_watchdog(memory_safe_module: ModuleType) -> None:
    """Install once into the Render memory-safe bootstrap's local subprocess seam."""
    current = getattr(memory_safe_module, "subprocess", None)
    if isinstance(current, _SubprocessProxy):
        return
    if current is not _subprocess:
        raise RuntimeError("release prequalification watchdog requires the canonical subprocess module")
    memory_safe_module.subprocess = _SubprocessProxy(_subprocess)


__all__ = ["PrequalificationProgress", "install_release_prequalification_parent_watchdog", "observe_current_prequalification_progress"]
