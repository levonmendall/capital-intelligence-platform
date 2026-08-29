"""Advisory comprehensive-input prewarm during U.S. equity discovery.

Production certification has repeatedly exhausted the unchanged 900-second evidence epoch
inside ``comprehensive_discovery`` after reference, public-live, and U.S.-equity discovery
have already qualified. The expensive comprehensive transaction needs release/reference-
bound structural catalogs and exact-epoch provider-preselection publications before it can
perform terminal screening and market-evidence qualification.

This module moves those prerequisite operations earlier without moving any certification or
investment authority. A disposable sidecar may run while the independent U.S.-equity stage
is active. It creates the exact deterministic comprehensive request that the later canonical
stage will use, then delegates structural preparation and provider I/O to the existing
``epoch_scoped_provider_acquisition`` owner. That owner remains bounded by the unchanged
300-second acceleration ceiling, six-worker cap, evidence lifetime, and 480-second downstream
reserve. Provider children atomically promote only clean, limitation-free publications.

The later serialized comprehensive transaction still owns terminal screening,
certification-node construction, market-evidence qualification, durable transaction state,
and global certification. It may validate and consume an exact-epoch provider publication
but must never start a second late provider-network fallback.

The sidecar is advisory and bounded by the same provider-acquisition window that existed
before this overlap. The U.S.-equity stage may use otherwise idle time while the sidecar is
running, then waits only until that original absolute acceleration deadline and always
reaps the child before publishing its stage result. Neither this sidecar nor its provider
fanout has evidence, candidate, sizing, construction, execution, CIO, or real-money
authority.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from cio import CandidateAssetClass


_MODULE = "operations.comprehensive_discovery_structural_prewarm"
_STOP_GRACE_SECONDS = 1.0
_COMPLETION_CLEANUP_RESERVE_SECONDS = 2.0 * _STOP_GRACE_SECONDS
_REFERENCE_MANIFEST_ID_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"
_REFERENCE_MANIFEST_PATH_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH"


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _render_enabled(values: Mapping[str, str]) -> bool:
    return str(values.get("RENDER") or "").strip().lower() == "true"


def _eligible(values: Mapping[str, str]) -> bool:
    return bool(
        _render_enabled(values)
        and str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip()
        and str(values.get(_REFERENCE_MANIFEST_ID_ENV) or "").strip()
        and str(values.get(_REFERENCE_MANIFEST_PATH_ENV) or "").strip()
    )


@dataclass(slots=True)
class StructuralPrewarmHandle:
    """Own one disposable advisory overlap sidecar and guarantee bounded cleanup."""

    process: subprocess.Popen[bytes] | None = None
    deadline_monotonic: float | None = None

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
        except OSError:
            return
        deadline = time.monotonic() + _STOP_GRACE_SECONDS
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                return
        try:
            process.wait(timeout=_STOP_GRACE_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            # Advisory work has no authority. The sidecar remains in the stage process
            # group, so the existing stage supervisor is still the final kill wall.
            pass

    def finish(self) -> None:
        """Let the sidecar finish only inside its original absolute acceleration window."""

        process = self.process
        if process is None:
            return
        if process.poll() is not None:
            self.process = None
            return
        deadline = self.deadline_monotonic
        if deadline is not None:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining > 0.0:
                try:
                    process.wait(timeout=remaining)
                    self.process = None
                    return
                except (OSError, subprocess.TimeoutExpired):
                    pass
        self.stop()


def start_render_structural_prewarm(
    *,
    evidence_as_of: datetime,
    values: Mapping[str, str],
) -> StructuralPrewarmHandle:
    """Start the exact-epoch comprehensive prerequisite sidecar on Render."""

    resolved = dict(values)
    if not _eligible(resolved):
        return StructuralPrewarmHandle()
    try:
        timestamp = _aware(evidence_as_of, field_name="structural_prewarm_evidence_as_of")
    except ValueError:
        return StructuralPrewarmHandle()

    from operations.epoch_scoped_provider_acquisition import _fanout_budget_seconds

    try:
        budget = float(_fanout_budget_seconds(timestamp, resolved))
    except (OSError, RuntimeError, TypeError, ValueError):
        budget = 0.0
    # The child is the canonical owner of the provider budget and independently applies
    # the unchanged evidence lifetime, 300-second ceiling, and 480-second downstream
    # reserve before any provider I/O. Keep the launcher contract stable even when the
    # current epoch has no spare acquisition time: the subordinate child may still start,
    # observe a zero budget, and exit without provider work. The parent deadline never
    # extends that budget and reserves cleanup time only when spare budget actually exists.
    usable_budget = max(0.0, budget - _COMPLETION_CLEANUP_RESERVE_SECONDS)
    deadline = time.monotonic() + usable_budget

    environment = dict(os.environ)
    environment.update({str(key): str(value) for key, value in resolved.items()})
    command = (
        sys.executable,
        "-m",
        _MODULE,
        "--as-of",
        timestamp.isoformat(),
    )
    try:
        process = subprocess.Popen(
            command,
            cwd=str(Path(__file__).resolve().parents[1]),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # Keep the sidecar inside the existing stage process group. If freshness or
            # resource supervision terminates the stage, this child dies with it.
            start_new_session=False,
        )
    except (OSError, ValueError):
        return StructuralPrewarmHandle()
    return StructuralPrewarmHandle(process=process, deadline_monotonic=deadline)


def _same_lane_schedule(core, asset_class: CandidateAssetClass, source, requested) -> bool:
    source_active = asset_class in core._base.scheduled_discovery_lanes(source)
    requested_active = asset_class in core._base.scheduled_discovery_lanes(requested)
    return source_active is requested_active


def prewarm_structural_catalogs(
    *,
    evidence_as_of: datetime,
    values: Mapping[str, str] | None = None,
) -> int:
    """Populate only compatible merged structural catalogs, serially and non-authoritatively."""

    resolved = dict(os.environ if values is None else values)
    timestamp = _aware(evidence_as_of, field_name="structural_prewarm_evidence_as_of")
    if not _eligible(resolved):
        return 0

    from operations import bounded_lane_comprehensive_discovery_worker as bounded_lane
    from operations import comprehensive_discovery_structural_cache as structural
    from operations import lane_local_comprehensive_discovery_spool as lane_local
    from operations import transactional_comprehensive_discovery_lane as canonical
    from operations.evidence_file_cache_release import release_current_reference_file_cache
    from operations import comprehensive_market_discovery as facade

    try:
        structural.bind_reference_structural_fingerprint(resolved)
    except (OSError, RuntimeError, TypeError, ValueError):
        return 0

    core = facade._core
    policy = core.ComprehensiveMarketDiscoveryPolicy()
    policy_version = str(getattr(policy, "version", ""))
    active = frozenset(core._base.scheduled_discovery_lanes(timestamp))
    published = 0

    for asset_class in lane_local._candidate_lanes():
        if asset_class is CandidateAssetClass.OPTION or asset_class not in active:
            continue
        existing = structural.load_structural_catalog(
            resolved,
            asset_class=asset_class,
            policy_version=policy_version,
            requested_as_of=timestamp,
        )
        if existing is not None and _same_lane_schedule(
            core, asset_class, existing.source_as_of, timestamp
        ):
            continue

        try:
            raw = canonical._load_catalog_records(
                core=core,
                values=resolved,
                policy=policy,
                timestamp=timestamp,
                asset_class=asset_class,
            )
            merged = bounded_lane._merge_certified_lane(
                core,
                raw,
                asset_class=asset_class,
                timestamp=timestamp,
            )
            if structural.publish_structural_catalog(
                resolved,
                asset_class=asset_class,
                policy_version=policy_version,
                source_as_of=timestamp,
                raw_record_count=len(raw),
                records=merged,
            ):
                published += 1
        except (OSError, RuntimeError, TypeError, ValueError):
            # Cache warming is advisory only. The bounded epoch provider owner will treat
            # a missing structural input as a failed lane and cannot certify anything.
            pass
        finally:
            try:
                del raw
            except UnboundLocalError:
                pass
            try:
                del merged
            except UnboundLocalError:
                pass
            try:
                release_current_reference_file_cache(resolved)
            except (OSError, RuntimeError, TypeError, ValueError):
                pass

    return published


def prewarm_epoch_provider_inputs(
    *,
    evidence_as_of: datetime,
    values: Mapping[str, str] | None = None,
) -> Mapping[str, object]:
    """Acquire exact comprehensive provider prerequisites during the U.S.-equity window.

    ``prepare_request`` is deterministic over release, epoch, state scope, exclusions, and
    policy. Using the same default policy and empty comprehensive exclusions as the later
    evidence-owner call therefore creates the exact request directory that
    ``spawn_safe_acquire`` will reopen. No authority is transferred to this sidecar.
    """

    resolved = dict(os.environ if values is None else values)
    timestamp = _aware(evidence_as_of, field_name="provider_prewarm_evidence_as_of")
    if not _eligible(resolved):
        return {
            "attempted": False,
            "reason": "ineligible",
            "completed": 0,
            "failed": 0,
        }

    from operations import comprehensive_market_discovery as facade
    from operations.comprehensive_discovery_input_spool import prepare_request
    from operations.evidence_state_scope import load_evidence_state_scope
    from operations.epoch_scoped_provider_acquisition import (
        run_provider_acquisition_fanout,
    )

    scope = load_evidence_state_scope(as_of=timestamp, values=resolved)
    policy = facade._core.ComprehensiveMarketDiscoveryPolicy()
    request = prepare_request(
        values=resolved,
        decision_epoch=timestamp,
        held_symbols=scope.held_symbols,
        tracked_symbols=scope.tracked_symbols,
        excluded_symbols=(),
        policy=policy,
    )
    return run_provider_acquisition_fanout(
        request.path,
        values=resolved,
        decision_epoch=timestamp,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args(argv)
    try:
        timestamp = datetime.fromisoformat(str(args.as_of).replace("Z", "+00:00"))
        prewarm_epoch_provider_inputs(evidence_as_of=timestamp)
    except (OSError, RuntimeError, TypeError, ValueError):
        # The parent deliberately ignores this advisory process's status. Return nonzero
        # for local observability without changing evidence qualification.
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "StructuralPrewarmHandle",
    "prewarm_epoch_provider_inputs",
    "prewarm_structural_catalogs",
    "start_render_structural_prewarm",
]
