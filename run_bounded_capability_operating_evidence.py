"""Run capability operating evidence in an isolated, resource-bounded child process."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from typing import Mapping, Sequence

from render_memory_lane import (
    MEMORY_LANE_PRIORITY_BYPASS_ENV,
    acquire_memory_lane,
    acquire_memory_lane_priority,
)
from run_bounded_render_worker import WorkerSpec, _run_isolated_once, run_loop


_SPEC = WorkerSpec(
    name="capability-operating-evidence",
    script="run_capability_operating_evidence.py",
    arguments=("--once",),
    interval_env="CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_INTERVAL_SECONDS",
    default_interval_seconds=300.0,
    timeout_env="CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_PASS_TIMEOUT_SECONDS",
    default_timeout_seconds=480.0,
    default_initial_delay_seconds=5.0,
)
_PRIORITY_OWNER = "release-capability-operating-evidence"


def _lane_wait_seconds(values: Mapping[str, str]) -> float:
    raw = values.get(
        "CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_MEMORY_LANE_WAIT_SECONDS",
        "30",
    ).strip()
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_MEMORY_LANE_WAIT_SECONDS must be numeric"
        ) from error
    if value < 0:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_MEMORY_LANE_WAIT_SECONDS cannot be negative"
        )
    return value


def _one_shot_budget_seconds(values: Mapping[str, str]) -> float:
    raw = str(values.get(_SPEC.timeout_env) or "").strip()
    if not raw:
        return _SPEC.default_timeout_seconds
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{_SPEC.timeout_env} must be numeric") from error
    if value <= 0:
        raise ValueError(f"{_SPEC.timeout_env} must be positive")
    return value


def _load_fresh_operating_evidence(values: Mapping[str, str]):
    """Reuse an already-qualified immutable operating snapshot for release one-shots.

    The long-lived background owner can legitimately finish a fresh capability snapshot
    while comprehensive all-market prequalification is still running. A later release
    ``--once`` request should consume that same validated snapshot rather than launching a
    duplicate heavy child and racing the background owner for the exclusive memory lane.

    The canonical loader remains the sole freshness/integrity gate. Missing or stale state
    is not accepted and falls through to the unchanged bounded refresh path.
    """

    from operations.capability_operating_evidence import (
        CapabilityOperatingEvidenceError,
        load_capability_operating_evidence,
    )

    try:
        return load_capability_operating_evidence(
            cutoff=datetime.now(timezone.utc),
            values=values,
        )
    except CapabilityOperatingEvidenceError:
        return None


def _log_reuse(*, after_lane_busy: bool) -> None:
    print(
        json.dumps(
            {
                "event": "capability_operating_evidence_reused",
                "after_lane_busy": bool(after_lane_busy),
                "credential_safe": True,
                "decision_authority": False,
                "candidate_authority": False,
                "sizing_authority": False,
                "construction_authority": False,
                "execution_authority": False,
                "paper_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _log_priority(event: str, **details: object) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "owner": _PRIORITY_OWNER,
                "credential_safe": True,
                "decision_authority": False,
                "candidate_authority": False,
                "sizing_authority": False,
                "construction_authority": False,
                "execution_authority": False,
                "paper_only": True,
                "real_money_authorized": False,
                **details,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def run_operating_once(values: Mapping[str, str] | None = None) -> int:
    resolved = dict(os.environ if values is None else values)
    current = _load_fresh_operating_evidence(resolved)
    if current is not None:
        _log_reuse(after_lane_busy=False)
        return 0

    # Exact-release capability qualification must not lose the lane to another background
    # pass after a live owner finishes. The priority fence never evicts that owner; it only
    # prevents new background entrants while this one-shot waits. The one-shot then probes
    # the heavy lane, rechecks the canonical snapshot while the lane is held, and only
    # launches a duplicate capability build when no fresh snapshot appeared.
    priority = acquire_memory_lane_priority(
        _PRIORITY_OWNER,
        values=resolved,
        timeout_seconds=0.0,
        poll_seconds=0.10,
    )
    if priority is None:
        _log_priority(
            "capability_operating_evidence_priority_busy",
            retry_deferred=True,
        )
        return 126

    resolved[MEMORY_LANE_PRIORITY_BYPASS_ENV] = "true"
    started = time.monotonic()
    deadline = started + _one_shot_budget_seconds(resolved)
    observed_busy = False
    try:
        _log_priority(
            "capability_operating_evidence_priority_acquired",
            background_preemption=False,
        )
        while True:
            current = _load_fresh_operating_evidence(resolved)
            if current is not None:
                _log_reuse(after_lane_busy=observed_busy)
                return 0

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _log_priority(
                    "capability_operating_evidence_priority_budget_exhausted",
                    retry_deferred=True,
                )
                return 126

            probe_wait = min(_lane_wait_seconds(resolved), remaining)
            probe = acquire_memory_lane(
                _SPEC.name,
                values=resolved,
                timeout_seconds=probe_wait,
                poll_seconds=0.10,
            )
            if probe is None:
                observed_busy = True
                continue

            try:
                current = _load_fresh_operating_evidence(resolved)
                if current is not None:
                    _log_reuse(after_lane_busy=True)
                    return 0
            finally:
                probe.release()

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 126

            # The release-priority fence is still held, so a normal background worker
            # cannot acquire the lane between the probe release and this immediate bounded
            # reacquisition. This preserves the existing worker/watchdog implementation and
            # all of its memory limits while making the handoff deterministic.
            return_code = _run_isolated_once(
                _SPEC,
                values=resolved,
                timeout_seconds=remaining,
                lane_wait_seconds=0.0,
            )
            if return_code == 126:
                # A second priority-bypass release owner would be unexpected, but retain
                # fail-closed bounded behavior rather than assuming ownership.
                observed_busy = True
                continue
            return return_code
    finally:
        priority.release()


def run_operating_loop(
    *,
    values: Mapping[str, str] | None = None,
    initial_delay_seconds: float | None = None,
) -> int:
    return run_loop(
        _SPEC,
        values=os.environ if values is None else values,
        initial_delay_seconds=initial_delay_seconds,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.once:
            return run_operating_once()
        return run_operating_loop()
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "event": "capability_operating_evidence_coordinator_failed",
                    "error_type": type(error).__name__,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
