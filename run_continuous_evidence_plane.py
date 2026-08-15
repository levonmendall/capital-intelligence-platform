"""Maintain the governed all-market evidence plane between CIO decisions."""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
from contextlib import contextmanager
from pathlib import Path
from types import FrameType
from typing import Iterator, Mapping, Sequence

from operations import component_qualified_evidence_maintenance as _component_maintenance
from operations import continuous_evidence_plane as _plane
from operations import qualified_evidence_maintenance as _legacy_maintenance
from operations.composite_readiness import component_heartbeat_path
from operations.comprehensive_discovery_snapshot import (
    publish_comprehensive_discovery_snapshot,
)
from operations.evidence_state_scope import load_evidence_state_scope
from operations.heartbeat import WorkerHeartbeatStore
from operations.qualified_comprehensive_discovery_snapshot import (
    ComprehensiveDiscoverySnapshotError,
    load_qualified_comprehensive_discovery_snapshot,
)

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


def _snapshot_matches_current_scope(
    generation,
    *,
    values: Mapping[str, str],
    cutoff,
) -> bool:
    if generation is None:
        return False
    try:
        snapshot = load_qualified_comprehensive_discovery_snapshot(
            evidence_as_of=generation.as_of,
            values=values,
        )
        scope = load_evidence_state_scope(as_of=cutoff, values=values)
    except (ComprehensiveDiscoverySnapshotError, OSError, TypeError, ValueError):
        return False
    return bool(
        snapshot.held_symbols == scope.held_symbols
        and snapshot.tracked_symbols == scope.tracked_symbols
    )


@contextmanager
def _install_global_snapshot_owner(
    values: Mapping[str, str],
) -> Iterator[None]:
    """Make the evidence worker own global discovery snapshot production.

    The hooks extend the existing qualification predicates rather than adding another
    scheduler or acquisition path. A generation that predates this component, or whose
    canonical holdings/learning scope changed, is no longer considered current. The
    existing evidence maintainer then performs its normal bounded refresh, and only that
    refresh is allowed to execute comprehensive provider discovery.
    """

    original_discovery = _plane._default_discovery
    original_legacy_qualified = _legacy_maintenance._generation_qualified
    original_component_qualified = _component_maintenance._generation_base_qualified

    def owned_discovery(as_of):
        from operations.comprehensive_market_discovery import discover_comprehensive_markets

        scope = load_evidence_state_scope(as_of=as_of, values=values)
        result = discover_comprehensive_markets(
            as_of=as_of,
            held_symbols=scope.held_symbols,
            tracked_symbols=scope.tracked_symbols,
        )
        publish_comprehensive_discovery_snapshot(
            result,
            held_symbols=scope.held_symbols,
            tracked_symbols=scope.tracked_symbols,
            values=values,
        )
        return result

    def legacy_qualified(
        generation,
        *,
        values,
        cutoff,
        reference_manifest_id,
    ):
        return bool(
            original_legacy_qualified(
                generation,
                values=values,
                cutoff=cutoff,
                reference_manifest_id=reference_manifest_id,
            )
            and _snapshot_matches_current_scope(
                generation,
                values=values,
                cutoff=cutoff,
            )
        )

    def component_qualified(
        generation,
        *,
        values,
        cutoff,
    ):
        return bool(
            original_component_qualified(
                generation,
                values=values,
                cutoff=cutoff,
            )
            and _snapshot_matches_current_scope(
                generation,
                values=values,
                cutoff=cutoff,
            )
        )

    _plane._default_discovery = owned_discovery
    _legacy_maintenance._generation_qualified = legacy_qualified
    _component_maintenance._generation_base_qualified = component_qualified
    try:
        yield
    finally:
        _plane._default_discovery = original_discovery
        _legacy_maintenance._generation_qualified = original_legacy_qualified
        _component_maintenance._generation_base_qualified = original_component_qualified


def run_once(values: Mapping[str, str] | None = None) -> dict[str, object]:
    resolved = dict(os.environ if values is None else values)
    prior = os.environ.get(_PREPARING_ENV)
    os.environ[_PREPARING_ENV] = "true"
    try:
        with _install_global_snapshot_owner(resolved):
            maintenance = (
                _component_maintenance.maintain_component_qualified_evidence_plane(
                    values=resolved
                )
            )
    finally:
        if prior is None:
            os.environ.pop(_PREPARING_ENV, None)
        else:
            os.environ[_PREPARING_ENV] = prior
    generation = maintenance.generation
    # Qualification is incomplete if the generation cannot be paired with the exact
    # release-independent comprehensive snapshot it claims to have prepared and restored
    # with the provider-factor/continuity metadata required by the qualified runtime.
    global_snapshot = load_qualified_comprehensive_discovery_snapshot(
        evidence_as_of=generation.as_of,
        values=resolved,
    )
    return {
        "state": "available",
        "maintenance_state": maintenance.state,
        "refreshed": maintenance.refreshed,
        "preparation_passes": maintenance.preparation_passes,
        "generation_id": generation.generation_id,
        "as_of": generation.as_of.isoformat(),
        "completed_at": generation.completed_at.isoformat(),
        "reference_manifest_id": generation.reference_manifest_id,
        "global_discovery_snapshot_id": global_snapshot.snapshot_id,
        "state_scope": {
            "held_symbols": list(global_snapshot.held_symbols),
            "tracked_symbols": list(global_snapshot.tracked_symbols),
        },
        "scheduled_lanes": list(generation.scheduled_lanes),
        "historical_scope_count": generation.historical_scope_count,
        "historical_coverage_digest": generation.historical_coverage_digest,
        "public_live_state": generation.public_live_state,
        "archived_generation_path": str(maintenance.archived_generation_path),
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
        heartbeat.write("starting", detail="continuous evidence qualification started")
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
                    + " global_snapshot="
                    + str(report["global_discovery_snapshot_id"])
                    + " maintenance_state="
                    + str(report["maintenance_state"])
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
