"""Maintain the governed all-market evidence plane between CIO decisions."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import FrameType
from typing import Iterator, Mapping, Sequence

from operations import component_qualified_evidence_maintenance as _component_maintenance
from operations import continuous_evidence_plane as _plane
from operations import qualified_evidence_maintenance as _legacy_maintenance
from operations.composite_readiness import component_heartbeat_path
from operations.comprehensive_discovery_snapshot import publish_comprehensive_discovery_snapshot
from operations.evidence_collection_universe import build_evidence_collection_universe
from operations.evidence_state_scope import load_evidence_state_scope
from operations.equity_discovery_snapshot import (
    EquityDiscoverySnapshotError,
    load_equity_discovery_snapshot,
    publish_equity_discovery_snapshot,
)
from operations.free_paper_pilot import DEFAULT_UNIVERSE_PATH, load_free_paper_pilot_universe
from operations.heartbeat import WorkerHeartbeatStore
from operations.owned_paper_evidence_collection import collect_owned_paper_evidence
from operations.paper_evidence_snapshot import (
    PaperEvidenceSnapshotError,
    load_paper_evidence_snapshot,
    publish_paper_evidence_snapshot,
)
from operations.paper_evidence_spool_concurrent import close_spooled_paper_evidence
from operations.qualified_comprehensive_discovery_snapshot import (
    ComprehensiveDiscoverySnapshotError,
    load_qualified_comprehensive_discovery_snapshot,
)

_PREPARING_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING"
_PAPER_HISTORY_DAYS = 365 * 10 + 20
_FAILURE_STAGE_ATTRIBUTE = "_capital_intelligence_evidence_failure_stage"
_FAILURE_CONTEXT_EVENT = "continuous_evidence_plane_failure_context"
_REDACTED = "[REDACTED]"
_SENSITIVE_ENV_MARKERS = (
    "API_KEY",
    "API_TOKEN",
    "ACCESS_TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "PRIVATE_KEY",
)


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


def _credential_safe_error_detail(
    error: BaseException,
    values: Mapping[str, str],
) -> str:
    """Return bounded failure provenance without disclosing configured credentials."""

    text = str(error).strip() or type(error).__name__
    secrets = {
        str(secret).strip()
        for name, secret in values.items()
        if any(marker in str(name).upper() for marker in _SENSITIVE_ENV_MARKERS)
        and len(str(secret).strip()) >= 4
    }
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, _REDACTED)
    text = re.sub(
        r"(?i)([?&](?:api[_-]?key|apikey|api_token|access_token|token|secret|password)=)[^&\s]+",
        rf"\1{_REDACTED}",
        text,
    )
    text = re.sub(
        r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]{8,}",
        rf"\1{_REDACTED}",
        text,
    )
    return text[:1600]


def _tag_failure_stage(error: BaseException, stage: str) -> None:
    try:
        setattr(error, _FAILURE_STAGE_ATTRIBUTE, stage)
    except (AttributeError, TypeError):
        return


def _failure_stage(error: BaseException) -> str:
    stage = str(getattr(error, _FAILURE_STAGE_ATTRIBUTE, "") or "").strip()
    return stage or "continuous_evidence_plane"


def _base_universe_symbols() -> tuple[str, ...]:
    universe = load_free_paper_pilot_universe(DEFAULT_UNIVERSE_PATH)
    return tuple(sorted(universe.symbol_map))


def _qualified_evidence_universe(generation, *, values: Mapping[str, str], cutoff):
    scope = load_evidence_state_scope(as_of=cutoff, values=values)
    universe, holding_only = build_evidence_collection_universe(
        evidence_as_of=generation.as_of,
        held_symbols=scope.held_symbols,
        tracked_symbols=scope.tracked_symbols,
        values=values,
    )
    return scope, universe, holding_only


def _snapshots_match_current_scope(
    generation,
    *,
    values: Mapping[str, str],
    cutoff,
) -> bool:
    if generation is None:
        return False
    try:
        global_snapshot = load_qualified_comprehensive_discovery_snapshot(
            evidence_as_of=generation.as_of,
            values=values,
        )
        equity_snapshot = load_equity_discovery_snapshot(
            evidence_as_of=generation.as_of,
            values=values,
        )
        scope, evidence_universe, _holding_only = _qualified_evidence_universe(
            generation,
            values=values,
            cutoff=cutoff,
        )
        paper_snapshot = load_paper_evidence_snapshot(
            evidence_as_of=generation.as_of,
            universe=evidence_universe,
            values=values,
        )
        base_symbols = _base_universe_symbols()
    except (
        ComprehensiveDiscoverySnapshotError,
        EquityDiscoverySnapshotError,
        PaperEvidenceSnapshotError,
        OSError,
        TypeError,
        ValueError,
    ):
        return False
    return bool(
        global_snapshot.held_symbols == scope.held_symbols
        and global_snapshot.tracked_symbols == scope.tracked_symbols
        and equity_snapshot.held_symbols == scope.held_symbols
        and equity_snapshot.tracked_symbols == scope.tracked_symbols
        and equity_snapshot.excluded_symbols == base_symbols
        and paper_snapshot.evidence_as_of == generation.as_of
    )


@contextmanager
def _install_global_snapshot_owner(
    values: Mapping[str, str],
) -> Iterator[None]:
    """Make the evidence worker the sole broad discovery/evidence acquisition owner."""

    original_discovery = _plane._default_discovery
    original_legacy_qualified = _legacy_maintenance._generation_qualified
    original_component_qualified = _component_maintenance._generation_base_qualified

    def owned_discovery(as_of):
        from operations.comprehensive_market_discovery import discover_comprehensive_markets
        from operations.equity_discovery import discover_us_equities

        scope = load_evidence_state_scope(as_of=as_of, values=values)
        base_symbols = _base_universe_symbols()

        equity_result = discover_us_equities(
            as_of=as_of,
            held_symbols=scope.held_symbols,
            tracked_symbols=scope.tracked_symbols,
            excluded_symbols=base_symbols,
        )
        publish_equity_discovery_snapshot(
            equity_result,
            held_symbols=scope.held_symbols,
            tracked_symbols=scope.tracked_symbols,
            excluded_symbols=base_symbols,
            values=values,
        )

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

        evidence_universe, _holding_only = build_evidence_collection_universe(
            evidence_as_of=as_of,
            held_symbols=scope.held_symbols,
            tracked_symbols=scope.tracked_symbols,
            values=values,
        )
        payload = collect_owned_paper_evidence(
            evidence_universe,
            as_of,
            required_holding_symbols=scope.held_symbols,
            values=values,
        )
        try:
            publish_paper_evidence_snapshot(
                payload,
                universe=evidence_universe,
                evidence_as_of=as_of,
                values=values,
                requested_history_days=_PAPER_HISTORY_DAYS,
            )
        finally:
            close_spooled_paper_evidence(payload)
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
            and _snapshots_match_current_scope(
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
            and _snapshots_match_current_scope(
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
    stage = "component_qualified_evidence_maintenance"
    try:
        prior = os.environ.get(_PREPARING_ENV)
        os.environ[_PREPARING_ENV] = "true"
        try:
            with _install_global_snapshot_owner(resolved):
                maintenance = _component_maintenance.maintain_component_qualified_evidence_plane(
                    values=resolved
                )
        finally:
            if prior is None:
                os.environ.pop(_PREPARING_ENV, None)
            else:
                os.environ[_PREPARING_ENV] = prior
        generation = maintenance.generation

        stage = "qualified_global_discovery_snapshot"
        global_snapshot = load_qualified_comprehensive_discovery_snapshot(
            evidence_as_of=generation.as_of,
            values=resolved,
        )
        stage = "qualified_us_equity_discovery_snapshot"
        equity_snapshot = load_equity_discovery_snapshot(
            evidence_as_of=generation.as_of,
            values=resolved,
        )
        stage = "qualified_evidence_universe"
        scope, evidence_universe, _holding_only = _qualified_evidence_universe(
            generation,
            values=resolved,
            cutoff=generation.as_of,
        )
        stage = "qualified_paper_evidence_snapshot"
        paper_snapshot = load_paper_evidence_snapshot(
            evidence_as_of=generation.as_of,
            universe=evidence_universe,
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
            "us_equity_discovery_snapshot_id": equity_snapshot.snapshot_id,
            "paper_evidence_snapshot_id": paper_snapshot.snapshot_id,
            "state_scope": {
                "held_symbols": list(scope.held_symbols),
                "tracked_symbols": list(scope.tracked_symbols),
                "base_universe_symbols": list(equity_snapshot.excluded_symbols),
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
    except Exception as error:
        _tag_failure_stage(error, stage)
        raise


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
            error_detail = _credential_safe_error_detail(error, resolved)
            heartbeat.write("degraded", detail=error_detail[:1000])
            print(
                json.dumps(
                    {
                        "event": "continuous_evidence_plane_failed",
                        "error_type": type(error).__name__,
                        "failure_stage": _failure_stage(error),
                        "error_detail": error_detail,
                        "credential_safe": True,
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
                    + " us_equity_snapshot="
                    + str(report["us_equity_discovery_snapshot_id"])
                    + " paper_evidence_snapshot="
                    + str(report["paper_evidence_snapshot_id"])
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
        error_detail = _credential_safe_error_detail(error, os.environ)
        failure_stage = _failure_stage(error)
        print(
            json.dumps(
                {
                    "event": "continuous_evidence_plane_start_failed",
                    "error_type": type(error).__name__,
                    "failure_stage": failure_stage,
                    "credential_safe": True,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        # The bounded release qualifier captures only this credential-safe structured
        # stderr record. Normal stdout remains live in Render, avoiding a multi-minute
        # logging blind spot while still making the exact child cause durable upstream.
        print(
            json.dumps(
                {
                    "event": _FAILURE_CONTEXT_EVENT,
                    "error_type": type(error).__name__,
                    "failure_stage": failure_stage,
                    "error_detail": error_detail,
                    "credential_safe": True,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
