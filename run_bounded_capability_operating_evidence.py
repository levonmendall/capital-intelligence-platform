"""Run capability operating evidence in an isolated, resource-bounded child process."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Mapping, Sequence

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


def run_operating_once(values: Mapping[str, str] | None = None) -> int:
    resolved = dict(os.environ if values is None else values)
    current = _load_fresh_operating_evidence(resolved)
    if current is not None:
        _log_reuse(after_lane_busy=False)
        return 0

    return_code = _run_isolated_once(
        _SPEC,
        values=resolved,
        lane_wait_seconds=_lane_wait_seconds(resolved),
    )
    if return_code == 126 and _load_fresh_operating_evidence(resolved) is not None:
        # A background capability owner may have held the exclusive lane at entry and
        # finished during this bounded wait. Accept only its canonical fresh snapshot;
        # otherwise preserve the original resource-busy return code unchanged.
        _log_reuse(after_lane_busy=True)
        return 0
    return return_code


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
