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

The early owner may make one bounded replay when its first fanout leaves unresolved lanes.
The replay consumes only time left inside the first fanout's original absolute acquisition
window and reconstructs work in fresh finite children, so a transient provider or child
failure cannot strand an otherwise valid exact-epoch publication while no failed attempt's
heavy object graph is retained. On a full production acquisition window, a small suffix of
that same fixed window is reserved for the one replay so the first fanout cannot consume the
entire legal provider window before an absent exact-request publication can be retried. Short
windows preserve their existing first-pass budget instead of being fragmented. When an
exact-request publication is absent, replay targets that missing lane before already-
published lanes; if no file-level gap can be identified, it falls back to the complete
canonical lane schedule. The replay never extends or resets the provider budget.

The later serialized comprehensive transaction still owns terminal screening,
certification-node construction, market-evidence qualification, durable transaction state,
and global certification. It may validate and consume an exact-epoch provider publication
but must never start a second late provider-network fallback.

The sidecar is advisory and bounded inside the same provider-acquisition window. It
surrenders the window with a separate 30-second operational handoff margin, plus bounded
cleanup time, before the unchanged 480-second downstream reserve is reached. That margin is
for cache release, process exit, interpreter startup, and stage journal handoff only; it does
not extend the 900-second evidence lifetime, the 300-second acceleration ceiling, or weaken
the 480-second governed reserve. Neither this sidecar nor its provider fanout has evidence,
candidate, sizing, construction, execution, CIO, or real-money authority.
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
_OPERATIONAL_HANDOFF_MARGIN_SECONDS = 30.0
_EARLY_OWNER_RESERVE_SECONDS = (
    _OPERATIONAL_HANDOFF_MARGIN_SECONDS + _COMPLETION_CLEANUP_RESERVE_SECONDS
)
_PROVIDER_REPLAY_LIMIT = 1
_PROVIDER_REPLAY_MAX_RESERVE_SECONDS = 45.0
_PROVIDER_REPLAY_RESERVE_FRACTION = 0.25
_PROVIDER_REPLAY_MIN_WINDOW_SECONDS = (
    _PROVIDER_REPLAY_MAX_RESERVE_SECONDS / _PROVIDER_REPLAY_RESERVE_FRACTION
)
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


def _unresolved_provider_lanes(report: Mapping[str, object]) -> int:
    """Return conservative unresolved lane count from one advisory fanout report."""

    try:
        scheduled = max(0, int(report.get("scheduled_lanes", 0)))
        completed = max(0, int(report.get("completed", 0)))
        failed = max(0, int(report.get("failed", 0)))
        skipped = max(0, int(report.get("provider_skipped_lanes", 0)))
    except (TypeError, ValueError):
        return 1
    return max(failed, skipped, max(0, scheduled - completed))


def _provider_replay_lane_items(
    request_path: str | Path,
    *,
    acquisition,
    decision_epoch: datetime,
) -> tuple[tuple[int, CandidateAssetClass], ...]:
    """Prioritize absent exact-request publications without weakening later validation.

    This is only a replay scheduling hint. A regular non-symlink file at the canonical
    exact-request path is not treated as evidence or as a validated publication; the
    provider child and later transactional lane still perform the existing integrity,
    fingerprint, limitation, and epoch checks. If every canonical path exists even though
    the previous fanout reported unresolved work, replay falls back to the complete lane
    schedule so an invalid existing artifact can still be rebuilt inside the original
    legal provider window.
    """

    lane_items = tuple(acquisition._scheduled_lane_items(decision_epoch))
    directory = Path(request_path).expanduser().parent
    missing: list[tuple[int, CandidateAssetClass]] = []
    for index, asset_class in lane_items:
        publication_path = directory / (
            f"provider-preselection-{index:03d}-{asset_class.value}.json"
        )
        try:
            ready_hint = (
                publication_path.is_file()
                and not publication_path.is_symlink()
                and publication_path.stat().st_size > 0
            )
        except OSError:
            ready_hint = False
        if not ready_hint:
            missing.append((index, asset_class))
    return tuple(missing or lane_items)


def _provider_replay_reserve_seconds(initial_budget: float) -> float:
    """Reserve replay time only when the legal window is large enough to preserve first pass."""

    budget = max(0.0, float(initial_budget))
    if (
        _PROVIDER_REPLAY_LIMIT < 1
        or budget < _PROVIDER_REPLAY_MIN_WINDOW_SECONDS
    ):
        return 0.0
    return min(
        _PROVIDER_REPLAY_MAX_RESERVE_SECONDS,
        budget * _PROVIDER_REPLAY_RESERVE_FRACTION,
    )


def _run_epoch_provider_fanout_with_bounded_replay(
    request_path: str | Path,
    *,
    values: Mapping[str, str],
    decision_epoch: datetime,
) -> Mapping[str, object]:
    """Replay unresolved early provider work once without extending its first budget.

    The epoch-derived budget becomes one absolute monotonic window after the operational
    handoff/cleanup reserve is removed. A full production window leaves a bounded suffix for
    the already-governed single replay; a short window preserves its historical first-pass
    cap. Any replay temporarily narrows the acquisition module's existing 300-second ceiling
    to only the time left in that same window. The sidecar is a single-threaded finite
    process, and the original module constants and canonical lane schedule are restored
    around every call, including failures.
    """

    from operations import epoch_scoped_provider_acquisition as acquisition

    resolved = dict(values)
    try:
        governed_budget = max(
            0.0,
            float(acquisition._fanout_budget_seconds(decision_epoch, resolved)),
        )
        initial_budget = max(0.0, governed_budget - _EARLY_OWNER_RESERVE_SECONDS)
    except (OSError, RuntimeError, TypeError, ValueError):
        governed_budget = 0.0
        initial_budget = 0.0
    deadline = time.monotonic() + initial_budget
    replay_reserve = _provider_replay_reserve_seconds(initial_budget)
    original_ceiling = float(acquisition._MAX_FANOUT_SECONDS)
    original_schedule = acquisition._scheduled_lane_items
    reports: list[Mapping[str, object]] = []
    replay_targeted_lanes: int | None = None
    attempt_caps: list[float] = []

    for attempt in range(_PROVIDER_REPLAY_LIMIT + 1):
        remaining = max(0.0, deadline - time.monotonic())
        replay_lane_items: tuple[tuple[int, CandidateAssetClass], ...] | None = None
        if attempt > 0:
            if not reports or _unresolved_provider_lanes(reports[-1]) <= 0 or remaining <= 0.0:
                break
            replay_lane_items = _provider_replay_lane_items(
                request_path,
                acquisition=acquisition,
                decision_epoch=decision_epoch,
            )
            replay_targeted_lanes = len(replay_lane_items)

        if attempt == 0 and replay_reserve > 0.0:
            available = max(0.0, remaining - replay_reserve)
        else:
            available = remaining
        cap = min(original_ceiling, available)
        attempt_caps.append(cap)
        acquisition._MAX_FANOUT_SECONDS = cap
        if replay_lane_items is not None:
            acquisition._scheduled_lane_items = lambda _epoch: replay_lane_items
        try:
            report = acquisition.run_provider_acquisition_fanout(
                request_path,
                values=resolved,
                decision_epoch=decision_epoch,
            )
        finally:
            acquisition._MAX_FANOUT_SECONDS = original_ceiling
            acquisition._scheduled_lane_items = original_schedule
        reports.append(dict(report))

    if not reports:
        return {
            "attempted": False,
            "reason": "provider_acquisition_unavailable",
            "completed": 0,
            "failed": 0,
        }
    if len(reports) == 1:
        final = dict(reports[0])
        final.update(
            {
                "provider_replay_attempted": False,
                "provider_replay_bounded": True,
                "provider_replay_reserved_seconds": round(replay_reserve, 3),
                "provider_replay_first_attempt_cap_seconds": round(
                    attempt_caps[0] if attempt_caps else 0.0,
                    3,
                ),
                "provider_prewarm_governed_budget_seconds": round(governed_budget, 3),
                "provider_prewarm_initial_budget_seconds": round(initial_budget, 3),
            }
        )
        return final

    final = dict(reports[-1])
    final.update(
        {
            "provider_replay_attempted": True,
            "provider_replay_count": len(reports) - 1,
            "provider_replay_bounded": True,
            "provider_replay_targeted_lanes": replay_targeted_lanes,
            "provider_replay_initial_unresolved": _unresolved_provider_lanes(reports[0]),
            "provider_replay_final_unresolved": _unresolved_provider_lanes(reports[-1]),
            "provider_replay_initial_budget_seconds": round(initial_budget, 3),
            "provider_replay_reserved_seconds": round(replay_reserve, 3),
            "provider_replay_first_attempt_cap_seconds": round(
                attempt_caps[0] if attempt_caps else 0.0,
                3,
            ),
            "provider_replay_attempt_caps_seconds": [
                round(value, 3) for value in attempt_caps
            ],
            "provider_replay_remaining_budget_seconds": round(
                max(0.0, deadline - time.monotonic()),
                3,
            ),
            "provider_prewarm_governed_budget_seconds": round(governed_budget, 3),
            "provider_prewarm_handoff_margin_seconds": _OPERATIONAL_HANDOFF_MARGIN_SECONDS,
            "provider_prewarm_cleanup_reserve_seconds": _COMPLETION_CLEANUP_RESERVE_SECONDS,
        }
    )
    return final


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
            pass

    def finish(self) -> None:
        """Let the sidecar finish only inside its reduced absolute acceleration window."""

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
    usable_budget = max(0.0, budget - _EARLY_OWNER_RESERVE_SECONDS)
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
    """Acquire exact comprehensive provider prerequisites during the U.S.-equity window."""

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
    return _run_epoch_provider_fanout_with_bounded_replay(
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
