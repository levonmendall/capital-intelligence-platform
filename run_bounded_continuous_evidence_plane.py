"""Run continuous evidence preparation in the existing exclusive heavy-memory lane.

The coordinator itself imports no provider or discovery stack. Each preparation pass is
a short-lived child process, allowing Python/provider working sets to return to the OS
between refreshes and sharing the same cross-process memory lane as the other heavyweight
Render workers. Release startup can invoke one bounded pass before the CIO diagnostic;
the normal production coordinator continues to use loop mode afterward.

The isolated child enters through a DAG-native bootstrap that installs and verifies the
comprehensive-discovery runtime contract before the evidence owner is imported. This
prevents import ordering from silently restoring the obsolete aggregate discovery timeout.
On Render's fixed-memory service, the nested certification DAG is serialized so fresh lane
interpreters cannot defeat the outer exclusive-memory-lane guarantee by running in parallel.
This changes scheduling only: every required DAG node and market lane remains mandatory.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Mapping, Sequence

from run_bounded_render_worker import WorkerSpec, _run_isolated_once, run_loop


_SPEC = WorkerSpec(
    name="continuous-evidence-plane",
    script="run_dag_native_continuous_evidence_plane.py",
    arguments=("--once",),
    interval_env="CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_INTERVAL_SECONDS",
    default_interval_seconds=300.0,
    timeout_env="CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PASS_TIMEOUT_SECONDS",
    default_timeout_seconds=3600.0,
    default_initial_delay_seconds=30.0,
)
_DAG_WORKERS_ENV = "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS"


def _lane_wait_seconds(values: Mapping[str, str]) -> float:
    raw = values.get(
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MEMORY_LANE_WAIT_SECONDS",
        "300",
    ).strip()
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MEMORY_LANE_WAIT_SECONDS must be numeric"
        ) from error
    if value < 0:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MEMORY_LANE_WAIT_SECONDS cannot be negative"
        )
    return value


def _bounded_evidence_values(values: Mapping[str, str]) -> dict[str, str]:
    """Serialize nested DAG workers on Render while preserving complete certification."""

    resolved = dict(values)
    if str(resolved.get("RENDER") or "").strip().lower() == "true":
        # The outer evidence owner already has one exclusive heavy-memory lease. Allowing
        # the inner DAG scheduler to start its default three fresh Python interpreters at
        # once can cross the same 2 GiB service's governed high-water boundary before any
        # node commits. Serial nodes are durable/resumable, so this bounds peak RAM without
        # dropping a node, market, provider requirement, freshness rule, or fail-closed gate.
        resolved[_DAG_WORKERS_ENV] = "1"
    return resolved


def run_continuous_once(values: Mapping[str, str] | None = None) -> int:
    resolved = _bounded_evidence_values(os.environ if values is None else values)
    return _run_isolated_once(
        _SPEC,
        values=resolved,
        lane_wait_seconds=_lane_wait_seconds(resolved),
    )


def run_continuous_loop(
    *,
    values: Mapping[str, str] | None = None,
    initial_delay_seconds: float | None = None,
) -> int:
    resolved = _bounded_evidence_values(os.environ if values is None else values)
    return run_loop(
        _SPEC,
        values=resolved,
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
            return run_continuous_once()
        return run_continuous_loop()
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "event": "continuous_evidence_plane_coordinator_failed",
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
