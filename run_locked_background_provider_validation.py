"""Run provider validation through the shared Render heavyweight-memory lane.

The existing provider worker already keeps its expensive validation stack in a bounded
short-lived child and defers while a manual CIO diagnostic is active.  This production
entrypoint adds cross-process serialization with the CIO operator, historical replay, and
backup coordinators so two individually safe children cannot combine to exceed Render's
2 GB service limit.
"""

from __future__ import annotations

import os
from typing import Mapping, Sequence

import run_background_provider_validation as provider_worker
from render_memory_lane import acquire_memory_lane


_ORIGINAL_ISOLATED_VALIDATION = provider_worker._run_isolated_validation


def _run_locked_validation(
    *,
    values: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> int:
    resolved = dict(os.environ if values is None else values)
    lease = acquire_memory_lane(
        "provider-validation",
        values=resolved,
        timeout_seconds=30.0,
        poll_seconds=0.10,
    )
    if lease is None:
        provider_worker._log(
            "provider_validation_heavy_memory_lane_busy",
            provider_validation_deferred=True,
            child_started=False,
        )
        return 126
    try:
        return _ORIGINAL_ISOLATED_VALIDATION(
            values=resolved,
            timeout_seconds=timeout_seconds,
        )
    finally:
        lease.release()


def main(argv: Sequence[str] | None = None) -> int:
    provider_worker._run_isolated_validation = _run_locked_validation
    return provider_worker.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
