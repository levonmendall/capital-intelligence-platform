"""Run capability operating evidence in an isolated, resource-bounded child process."""

from __future__ import annotations

import argparse
import json
import os
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


def run_operating_once(values: Mapping[str, str] | None = None) -> int:
    resolved = dict(os.environ if values is None else values)
    return _run_isolated_once(
        _SPEC,
        values=resolved,
        lane_wait_seconds=_lane_wait_seconds(resolved),
    )


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
