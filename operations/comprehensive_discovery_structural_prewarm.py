"""Advisory structural-only prewarm for comprehensive discovery during U.S. equity work.

Production certification has repeatedly exhausted the unchanged 900-second evidence epoch
inside ``comprehensive_discovery`` after reference, public-live, and U.S.-equity discovery
have already qualified.  The expensive comprehensive transaction begins by reconstructing
and merging release/reference-bound catalog structure before it performs any exact-epoch
provider publication, terminal screening, or market-evidence qualification.

This module moves only that structural reconstruction earlier.  A disposable sidecar may
run while the independent U.S.-equity provider acquisition is active and populate the
existing structural cache.  The sidecar never creates provider-preselection publication,
terminal-screening results, certification nodes, market evidence, candidates, sizing,
construction, execution, or investment authority.  The canonical comprehensive stage must
still rebuild every exact-epoch artifact and qualify every required lane fail-closed.

The sidecar is advisory and bounded by the U.S.-equity stage lifetime.  The caller always
stops/reaps it before publishing the U.S.-equity stage result, so no structural-prewarm
process can overlap the subsequent comprehensive publication/evidence lane or outlive the
stage that launched it.
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
    """Own one disposable advisory sidecar and guarantee bounded cleanup."""

    process: subprocess.Popen[bytes] | None = None

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
            # Advisory cache work has no authority.  The sidecar remains in the stage's
            # process group, so the existing stage supervisor is still the final kill wall.
            pass


def start_render_structural_prewarm(
    *,
    evidence_as_of: datetime,
    values: Mapping[str, str],
) -> StructuralPrewarmHandle:
    """Start one structural-only sidecar on Render; all failures are fail-soft."""

    resolved = dict(values)
    if not _eligible(resolved):
        return StructuralPrewarmHandle()
    try:
        timestamp = _aware(evidence_as_of, field_name="structural_prewarm_evidence_as_of")
    except ValueError:
        return StructuralPrewarmHandle()

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
            # Keep the sidecar inside the existing stage process group.  If the unchanged
            # freshness/resource supervisor terminates the stage, this child dies with it.
            start_new_session=False,
        )
    except (OSError, ValueError):
        return StructuralPrewarmHandle()
    return StructuralPrewarmHandle(process=process)


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
        # Options are timestamp-constructed and explicitly excluded by the structural cache.
        # Unscheduled lanes cannot contribute to this exact comprehensive attempt.
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
            # Cache warming is acceleration only.  A miss/failure leaves the unchanged
            # comprehensive transaction responsible for canonical reconstruction.
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args(argv)
    try:
        timestamp = datetime.fromisoformat(str(args.as_of).replace("Z", "+00:00"))
        prewarm_structural_catalogs(evidence_as_of=timestamp)
    except (OSError, RuntimeError, TypeError, ValueError):
        # The parent deliberately ignores this advisory process's status.  Return a
        # nonzero code for local observability without changing evidence qualification.
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "StructuralPrewarmHandle",
    "prewarm_structural_catalogs",
    "start_render_structural_prewarm",
]
