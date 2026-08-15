"""Maintain free global catalog, macro, positioning and research evidence.

This process is deliberately non-critical and provider-facing.  It runs beside,
not inside, CIO analysis.  All outputs remain supporting evidence until normal
point-in-time qualification/capability gates admit them.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
from pathlib import Path
from types import FrameType
from typing import Mapping, Sequence

from operations.composite_readiness import component_heartbeat_path
from operations.global_public_catalog_maintenance import maintain_global_public_catalogs
from operations.global_public_research_maintenance import maintain_global_public_research
from operations.heartbeat import WorkerHeartbeatStore
from providers.public_live_information_global_depth import (
    GlobalDecisionDepthInformationProvider,
)
from public_live_collection_runtime import collect_public_live_information_if_due


def _interval(values: Mapping[str, str]) -> float:
    raw = values.get(
        "CAPITAL_INTELLIGENCE_GLOBAL_PUBLIC_EVIDENCE_INTERVAL_SECONDS",
        "900",
    ).strip()
    try:
        seconds = float(raw)
    except ValueError as error:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_GLOBAL_PUBLIC_EVIDENCE_INTERVAL_SECONDS must be numeric"
        ) from error
    if not 300 <= seconds <= 86400:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_GLOBAL_PUBLIC_EVIDENCE_INTERVAL_SECONDS must be between 300 and 86400"
        )
    return seconds


def run_once(values: Mapping[str, str] | None = None) -> dict[str, object]:
    resolved = dict(os.environ if values is None else values)
    public_live = collect_public_live_information_if_due(
        force=False,
        provider_factory=GlobalDecisionDepthInformationProvider,
    )
    catalogs = maintain_global_public_catalogs(values=resolved)
    research = maintain_global_public_research(values=resolved)
    return {
        "schema_version": "global-public-evidence-maintenance.v1",
        "public_live": public_live.to_dict(),
        "catalogs": catalogs.to_dict(),
        "research": research.to_dict(),
        "decision_evidence_authority": False,
        "investment_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def run_loop(values: Mapping[str, str] | None = None) -> int:
    resolved = dict(os.environ if values is None else values)
    interval = _interval(resolved)
    state_root = Path(resolved.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    heartbeat = WorkerHeartbeatStore(
        component_heartbeat_path(state_root, "global-public-evidence")
    )
    stopping = False

    def stop(signum: int, frame: FrameType | None) -> None:
        del signum, frame
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        heartbeat.write("starting", detail="global public evidence maintenance started")
        try:
            report = run_once(resolved)
        except Exception as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            detail = f"{type(error).__name__}: {str(error)[:900]}"
            heartbeat.write("degraded", detail=detail)
            print(
                json.dumps(
                    {
                        "event": "global_public_evidence_failed",
                        "detail": detail,
                        "real_money_authorized": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        else:
            catalog_report = report.get("catalogs", {})
            research_report = report.get("research", {})
            detail = (
                "global public evidence completed; catalogs="
                + str(catalog_report.get("succeeded_count", 0))
                + "/"
                + str(catalog_report.get("source_count", 0))
                + " research_lanes="
                + str(len(research_report.get("lanes", [])))
            )
            heartbeat.write("healthy", detail=detail[:1000])
            print(
                json.dumps(
                    {"event": "global_public_evidence_completed", "report": report},
                    sort_keys=True,
                    default=str,
                ),
                flush=True,
            )
        deadline = time.monotonic() + interval
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(30.0, max(0.1, deadline - time.monotonic())))
    heartbeat.write("stopped", detail="global public evidence maintenance stopped")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args(argv)
    if args.loop:
        return run_loop()
    report = run_once()
    print(json.dumps(report, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
