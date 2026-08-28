"""Project valid in-flight transactional screening into the release parent watchdog.

The transactional comprehensive-discovery lane owns catalog reconstruction, provider
publication, and terminal screening inside one finite child. The legacy lane-local watchdog
projection intentionally exposed screening only after every market lane had completed
publication. That ordering became stale once publication and screening moved into the same
per-lane transaction: a lane can be legitimately screening while later lanes have not yet
published, leaving the parent pinned to the last publication completion until its unchanged
stall budget expires.

This adapter changes only credential-safe liveness observation. It accepts an active
``screening-lane`` marker only when the exact request/release/lane identity is current and
the same lane already has a durable valid publication checkpoint. It does not change stall
budgets, evidence freshness/completeness, screening rules, market scope, CIO authority,
construction, execution, or paper-only controls.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping


_INSTALLED_MARKER = "_transactional_screening_watchdog_progress_v1"


def _screening_progress(values: Mapping[str, str], *, boundary: datetime):
    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import comprehensive_discovery_input_spool as spool
    from operations import lane_local_comprehensive_discovery_spool as lane_local
    from operations import lane_local_watchdog_progress as lane_progress
    from operations import release_prequalification_parent_watchdog as watchdog

    try:
        root = spool._root(values)
        request_paths = tuple(root.glob("*/*/request.json"))
    except (OSError, RuntimeError, ValueError):
        return None

    best = None
    best_request_time: float | None = None
    release = spool._release(values)
    lanes = tuple(lane_local._candidate_lanes())
    timeout = watchdog._positive_seconds(
        values,
        (watchdog._PREPARATION_STALL_ENV, watchdog._STARTUP_STALL_ENV),
        watchdog._DEFAULT_STARTUP_STALL_SECONDS,
    )

    for request_path in request_paths:
        request_mtime = watchdog._path_mtime(request_path)
        if request_mtime is None or request_mtime < boundary:
            continue
        request = lane_progress._load_request_identity(request_path, spool)
        if not isinstance(request, Mapping):
            continue
        request_id = str(request.get("request_id") or "").strip()
        if not request_id or request.get("release") != release:
            continue

        active = lane_progress._load_active_state(
            request_path,
            request_id=request_id,
            release=release,
            boundary=boundary,
        )
        if active is None or active[0] != "screening-lane":
            continue
        _action, asset_class, index, updated_at = active
        if index >= len(lanes) or lanes[index].value != asset_class:
            continue

        publication_name = lane_local._lane_state_name("publication-lane", index)
        publication = lane_progress._valid_lane_state(
            lane_progress._load_stage(bounded, request_path, publication_name),
            request_id=request_id,
            asset_class=asset_class,
        )
        # A screening marker cannot advance liveness unless canonical durable publication
        # for that exact lane already exists and says the lane is actually scheduled.
        if publication is None or publication.get("scheduled") is not True:
            continue

        try:
            request_stat_time = request_path.stat().st_mtime
        except OSError:
            continue
        progress = watchdog.PrequalificationProgress(
            phase="discovery_preparation",
            component=f"bounded-spool-screening-lane:{asset_class}",
            updated_at=updated_at,
            state="running",
            stall_limit_seconds=timeout,
            metrics={
                "candidate_lanes": len(lanes),
                "active_lane_index": index,
                "catalog_records": int(publication.get("record_count") or 0),
                "peak_rss_bytes": lane_progress._peak_metric(publication),
                "bounded_provider_publication": int(
                    publication.get("bounded_provider_publication") is True
                ),
            },
            progress_token=(
                f"{request_id}:active:screening-lane:{index:03d}:{asset_class}"
            ),
        )
        if best is None or best_request_time is None or request_stat_time > best_request_time:
            best = progress
            best_request_time = request_stat_time

    return best


def install_transactional_screening_watchdog_progress() -> None:
    """Overlay valid in-flight screening after the lane-local watchdog projection."""

    from operations import release_prequalification_parent_watchdog as watchdog

    current = watchdog._bounded_discovery_progress
    if bool(getattr(current, _INSTALLED_MARKER, False)):
        return

    def bounded_discovery_progress(values: Mapping[str, str], *, boundary: datetime):
        observed = current(values, boundary=boundary)
        screening = _screening_progress(values, boundary=boundary)
        if screening is None:
            return observed
        # The marker is written after the same-lane publication state is durable. Prefer it
        # only when it is at least as new as the current projection so stale markers cannot
        # overwrite later manifest or completion evidence.
        if observed is not None and screening.updated_at < observed.updated_at:
            return observed
        return screening

    setattr(bounded_discovery_progress, _INSTALLED_MARKER, True)
    setattr(bounded_discovery_progress, "_prior_bounded_discovery_progress", current)
    watchdog._bounded_discovery_progress = bounded_discovery_progress


__all__ = [
    "install_transactional_screening_watchdog_progress",
]
