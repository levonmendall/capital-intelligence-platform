"""Run continuous evidence preparation in the existing exclusive heavy-memory lane.

The coordinator itself imports no provider or discovery stack.  Each preparation pass is
a short-lived child process, allowing Python/provider working sets to return to the OS
between refreshes and sharing the same cross-process memory lane as the other heavyweight
Render workers.
"""

from __future__ import annotations

import json
import os
from typing import Mapping, Sequence

from run_bounded_render_worker import WorkerSpec, run_loop


_SPEC = WorkerSpec(
    name="continuous-evidence-plane",
    script="run_continuous_evidence_plane.py",
    arguments=("--once",),
    interval_env="CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_INTERVAL_SECONDS",
    default_interval_seconds=300.0,
    timeout_env="CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PASS_TIMEOUT_SECONDS",
    default_timeout_seconds=3600.0,
    default_initial_delay_seconds=30.0,
)


def run_continuous_loop(
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
    if argv not in (None, (), []):
        raise ValueError(
            "run_bounded_continuous_evidence_plane.py does not accept arguments"
        )
    try:
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
