"""Reap stale exact-epoch comprehensive DAG process groups before restart.

DAG nodes intentionally create their own POSIX sessions so the DAG supervisor can kill one
provider-facing lane without killing the stage coordinator.  If the stage owner itself dies,
those separate groups are no longer covered by the stage process group.  The parent-owned
runtime journal therefore records PID/start-time identity for every running node and this
lightweight recovery helper reaps only an exact matching stale process before a later stage
owner may restart the same epoch.

This module is operational cleanup only.  It cannot certify evidence or authorize candidate,
portfolio, execution, CIO, or real-money actions.
"""

from __future__ import annotations

import json
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

_RUNTIME_SCHEMA = "persistent-certification-runtime.v1"
_SCHEDULER_SCHEMA = "persistent-certification-dag.v1"
_TERMINATION_GRACE_SECONDS = 1.0


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evidence epoch must be timezone-aware")
    return value.astimezone(timezone.utc)


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _epoch_key(epoch: datetime) -> str:
    return _aware(epoch).strftime("%Y%m%dT%H%M%S%fZ")


def _runtime_path(values: Mapping[str, str], *, release: str, epoch: datetime) -> Path:
    root = Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "database").expanduser()
    return (
        root
        / "certification-dag"
        / _SCHEDULER_SCHEMA
        / release
        / _epoch_key(epoch)
        / "runtime-latest.json"
    )


def process_start_ticks(pid: int) -> int | None:
    """Return Linux /proc start ticks so PID reuse cannot authorize a kill."""

    try:
        raw = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8")
        tail = raw.rsplit(")", 1)[1].strip().split()
        # ``tail[0]`` is field 3 (state); Linux field 22 (starttime) is index 19.
        return int(tail[19])
    except (FileNotFoundError, OSError, IndexError, TypeError, ValueError):
        return None


def _identity_alive(pid: int, start_ticks: int) -> bool:
    return process_start_ticks(pid) == start_ticks


def _signal_exact_process(pid: int, *, process_group_ready: bool, sig: int) -> None:
    if process_group_ready:
        os.killpg(pid, sig)
    else:
        os.kill(pid, sig)


def _terminate_exact_process(
    pid: int,
    *,
    start_ticks: int,
    process_group_ready: bool,
) -> bool:
    if not _identity_alive(pid, start_ticks):
        return False
    try:
        _signal_exact_process(
            pid,
            process_group_ready=process_group_ready,
            sig=signal.SIGTERM,
        )
    except ProcessLookupError:
        return False
    deadline = time.monotonic() + _TERMINATION_GRACE_SECONDS
    while _identity_alive(pid, start_ticks) and time.monotonic() < deadline:
        time.sleep(0.02)
    if _identity_alive(pid, start_ticks):
        try:
            _signal_exact_process(
                pid,
                process_group_ready=process_group_ready,
                sig=signal.SIGKILL,
            )
        except ProcessLookupError:
            pass
        kill_deadline = time.monotonic() + _TERMINATION_GRACE_SECONDS
        while _identity_alive(pid, start_ticks) and time.monotonic() < kill_deadline:
            time.sleep(0.02)
    return not _identity_alive(pid, start_ticks)


def reap_stale_comprehensive_descendants(
    values: Mapping[str, str],
    *,
    evidence_as_of: datetime,
    release: str | None = None,
) -> dict[str, object]:
    """Reap only exact running nodes whose persisted Linux process identity still matches."""

    resolved_release = str(release or _release(values)).strip()
    epoch = _aware(evidence_as_of)
    report: dict[str, object] = {
        "attempted": False,
        "runtime_journal_found": False,
        "running_nodes_recorded": 0,
        "identity_matched": 0,
        "reaped": 0,
        "identity_mismatch_or_gone": 0,
        "credential_safe": True,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    if not resolved_release or resolved_release == "unknown" or os.name != "posix":
        return report

    path = _runtime_path(values, release=resolved_release, epoch=epoch)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return report
    if not isinstance(payload, Mapping):
        return report
    expected = {
        "schema_version": _RUNTIME_SCHEMA,
        "release_sha": resolved_release,
        "decision_epoch": epoch.isoformat(),
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        return report

    states = payload.get("node_states")
    if not isinstance(states, Mapping):
        return report
    report["attempted"] = True
    report["runtime_journal_found"] = True

    for raw in states.values():
        if not isinstance(raw, Mapping) or raw.get("state") != "running":
            continue
        report["running_nodes_recorded"] = int(report["running_nodes_recorded"]) + 1
        try:
            pid = int(raw.get("pid"))
            start_ticks = int(raw.get("process_start_ticks"))
        except (TypeError, ValueError):
            report["identity_mismatch_or_gone"] = int(report["identity_mismatch_or_gone"]) + 1
            continue
        if pid <= 1 or start_ticks <= 0 or not _identity_alive(pid, start_ticks):
            report["identity_mismatch_or_gone"] = int(report["identity_mismatch_or_gone"]) + 1
            continue
        report["identity_matched"] = int(report["identity_matched"]) + 1
        if _terminate_exact_process(
            pid,
            start_ticks=start_ticks,
            process_group_ready=raw.get("process_group_ready") is True,
        ):
            report["reaped"] = int(report["reaped"]) + 1

    return report


__all__ = ["process_start_ticks", "reap_stale_comprehensive_descendants"]
