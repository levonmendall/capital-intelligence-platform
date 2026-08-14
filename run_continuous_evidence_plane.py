"""Maintain the governed all-market evidence plane between CIO decisions."""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
from typing import Mapping, Sequence

from operations.composite_readiness import component_heartbeat_path
from operations.continuous_evidence_plane import refresh_continuous_evidence_plane
from operations.heartbeat import WorkerHeartbeatStore

_PREPARING_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING"


def _seconds(values: Mapping[str, str], name: str, default: float) -> float:
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def run_once(values: Mapping[str, str] | None = None) -> dict[str, object]:
    resolved = dict(os.environ if values is None else values)
    prior = os.environ.get(_PREPARING_ENV)
    os.environ[_PREPARING_ENV] = "true"
    try:
        generation = refresh_continuous_evidence_plane(
            as_of=datetime.now(timezone.utc),
            values=resolved,
        )
    finally:
        if prior is None:
            os.environ.pop(_PREPARING_ENV, None)
        else:
            os.environ[_PREPARING_ENV] = prior
    return {
        "state": "available",
        "generation_id": generation.generation_id,
        "as_of": generation.as_of.isoformat(),
        "completed_at": generation.completed_at.isoformat(),
        "reference_manifest_id": generation.reference_manifest_id,
        "scheduled_lanes": list(generation.scheduled_lanes),
        "historical_scope_count": generation.historical_scope_count,
        "historical_coverage_digest": generation.historical_coverage_digest,
        "public_live_state": generation.public_live_state,
        "investment_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def run_loop(values: Mapping[str, str] | None = None) -> int:
    resolved = dict(os.environ if values is None else values)
    interval = _seconds(
        resolved,
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_INTERVAL_SECONDS",
        300.0,
    )
    if interval < 60.0:
        raise ValueError("evidence-plane interval must be at least 60 seconds")
    state_root = Path(resolved.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    heartbeat = WorkerHeartbeatStore(
        component_heartbeat_path(state_root, "continuous-evidence-plane")
    )
    stopping = False

    def stop(signum: int, frame: FrameType | None) -> None:
        del signum, frame
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        heartbeat.write("starting", detail="continuous evidence preparation started")
        try:
            report = run_once(resolved)
        except Exception as error:
            heartbeat.write("degraded", detail=str(error)[:1000])
            print(
                json.dumps(
                    {
                        "event": "continuous_evidence_plane_failed",
                        "error_type": type(error).__name__,
                        "paper_only": True,
                        "real_money_authorized": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        else:
            heartbeat.write(
                "healthy",
                detail=(
                    "continuous evidence plane qualified generation="
                    + str(report["generation_id"])
                )[:1000],
            )
            print(
                json.dumps(
                    {
                        "event": "continuous_evidence_plane_completed",
                        "report": report,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        deadline = time.monotonic() + interval
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(30.0, max(0.1, deadline - time.monotonic())))
    heartbeat.write("stopped", detail="continuous evidence plane stopped")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.loop:
            return run_loop()
        report = run_once()
        print(json.dumps(report, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "event": "continuous_evidence_plane_start_failed",
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
