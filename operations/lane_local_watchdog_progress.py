"""Bridge lane-local comprehensive-discovery work into the parent stall watchdog.

Telemetry #704 showed the release parent watchdog timing out while comprehensive discovery
was still running after the telemetry #698 memory repair. The memory-bounded coordinator
now persists one catalog, publication, and screening state per asset-class lane, while the
legacy watchdog reader still understands only the older aggregate catalog/publication
states. This module supplies a narrow compatibility projection from the current lane-local
state contract into the existing :class:`PrequalificationProgress` contract.

The projection is deliberately logical rather than timestamp-heartbeat based. Starting a
new lane/substage or durably completing a new lane/substage advances the progress token;
touching or replaying the same file does not. Existing watchdog stall budgets, fail-closed
termination, market/candidate scope, evidence rules, CIO authority, and paper-only boundaries
are unchanged.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


_SCHEMA_VERSION = "lane-local-watchdog-progress.v1"
_ACTIVE_STATE_NAME = "watchdog-active-lane-stage.json"
_INSTALLED_ATTR = "_lane_local_watchdog_progress_v1"
_ACTION_COMPONENTS = {
    "catalog-lane": "bounded-spool-catalog-lane",
    "publication-lane": "bounded-spool-publication-lane",
    "screening-lane": "bounded-spool-screening-lane",
}


def _authority_fields() -> dict[str, bool]:
    return {
        "credential_safe": True,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _active_state_path(request_path: str | Path) -> Path:
    return Path(request_path).expanduser().parent / _ACTIVE_STATE_NAME


def _load_request_identity(request_path: Path, spool) -> Mapping[str, object] | None:
    """Validate the small request envelope without deserializing the policy blob."""

    try:
        body = spool._load_json(request_path, schema=spool._REQUEST_SCHEMA)
        expected = spool._digest(
            {
                "schema_version": spool._REQUEST_SCHEMA,
                "release": body.get("release"),
                "decision_epoch": body.get("decision_epoch"),
                "held_symbols": body.get("held_symbols"),
                "tracked_symbols": body.get("tracked_symbols"),
                "excluded_symbols": body.get("excluded_symbols"),
                "policy_sha256": body.get("policy_sha256"),
            }
        )
        if str(body.get("request_id") or "") != expected:
            return None
        policy_descriptor = spool._descriptor(body.get("policy_blob"))
        if policy_descriptor.sha256 != str(body.get("policy_sha256") or ""):
            return None
        return body
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def record_active_lane_watchdog_progress(
    request_path: str | Path,
    values: Mapping[str, str],
    *,
    action: str,
    asset_class: str,
    index: int,
) -> None:
    """Persist one credential-safe logical marker before a lane child is launched.

    This state has no evidence or investment authority. Its only purpose is to tell the
    parent watchdog exactly which finite child unit is currently running. Re-entering the
    same action/lane produces the same logical progress token, so retries cannot fabricate
    indefinite liveness.
    """

    if action not in _ACTION_COMPONENTS:
        raise ValueError(f"unsupported lane-local watchdog action: {action}")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError("index must be a nonnegative integer")
    normalized_asset_class = str(asset_class or "").strip().lower()
    if not normalized_asset_class:
        raise ValueError("asset_class is required")

    from operations import comprehensive_discovery_input_spool as spool

    path = Path(request_path).expanduser()
    request = _load_request_identity(path, spool)
    if request is None:
        raise RuntimeError("lane-local watchdog request identity is invalid")
    request_id = str(request.get("request_id") or "").strip()
    release = spool._release(values)
    if not request_id or request.get("release") != release:
        raise RuntimeError("lane-local watchdog request release does not match runtime")

    payload: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "request_id": request_id,
        "release": release,
        "action": action,
        "asset_class": normalized_asset_class,
        "index": index,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **_authority_fields(),
    }
    spool._atomic_json(_active_state_path(path), payload)


def _load_active_state(
    request_path: Path,
    *,
    request_id: str,
    release: str,
    boundary: datetime,
):
    from operations import release_prequalification_parent_watchdog as watchdog

    path = _active_state_path(request_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(raw, Mapping):
        return None
    if raw.get("schema_version") != _SCHEMA_VERSION:
        return None
    if str(raw.get("request_id") or "").strip() != request_id:
        return None
    if str(raw.get("release") or "").strip() != release:
        return None
    if raw.get("credential_safe") is not True:
        return None
    if raw.get("paper_only") is not True or raw.get("real_money_authorized") is not False:
        return None
    for field in (
        "decision_authority",
        "candidate_authority",
        "sizing_authority",
        "construction_authority",
        "execution_authority",
    ):
        if raw.get(field) is not False:
            return None

    action = str(raw.get("action") or "").strip()
    asset_class = str(raw.get("asset_class") or "").strip().lower()
    try:
        index = int(raw.get("index"))
    except (TypeError, ValueError):
        return None
    updated_at = watchdog._aware(raw.get("updated_at"))
    if (
        action not in _ACTION_COMPONENTS
        or not asset_class
        or index < 0
        or updated_at is None
        or updated_at < boundary
    ):
        return None
    return action, asset_class, index, updated_at


def _valid_lane_state(
    state: object,
    *,
    request_id: str,
    asset_class: str,
) -> Mapping[str, object] | None:
    if not isinstance(state, Mapping):
        return None
    if str(state.get("request_id") or "").strip() != request_id:
        return None
    if str(state.get("asset_class") or "").strip().lower() != asset_class:
        return None
    return state


def _load_stage(bounded, request_path: Path, name: str) -> Mapping[str, object] | None:
    try:
        state = bounded._load_stage_state(request_path, name)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return state if isinstance(state, Mapping) else None


def _peak_metric(state: Mapping[str, object]) -> int:
    value = state.get("peak_rss_bytes")
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _progress(
    watchdog,
    *,
    component: str,
    updated_at: datetime,
    timeout: float,
    metrics: Mapping[str, int],
    token: str,
):
    return watchdog.PrequalificationProgress(
        "discovery_preparation",
        component,
        updated_at,
        "running",
        timeout,
        metrics,
        progress_token=token,
    )


def _lane_local_request_progress(
    request_path: Path,
    values: Mapping[str, str],
    *,
    boundary: datetime,
):
    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import comprehensive_discovery_input_spool as spool
    from operations import lane_local_comprehensive_discovery_spool as lane_local
    from operations import release_prequalification_parent_watchdog as watchdog

    request_mtime = watchdog._path_mtime(request_path)
    if request_mtime is None or request_mtime < boundary:
        return None
    request = _load_request_identity(request_path, spool)
    if request is None:
        return None
    request_id = str(request.get("request_id") or "").strip()
    release = spool._release(values)
    if not request_id or request.get("release") != release:
        return None

    timeout = watchdog._positive_seconds(
        values,
        (watchdog._PREPARATION_STALL_ENV, watchdog._STARTUP_STALL_ENV),
        watchdog._DEFAULT_STARTUP_STALL_SECONDS,
    )
    lanes = tuple(lane_local._candidate_lanes())
    candidates: list[tuple[int, object]] = []
    publication_states: list[tuple[int, str, Mapping[str, object]]] = []

    active = _load_active_state(
        request_path,
        request_id=request_id,
        release=release,
        boundary=boundary,
    )
    if active is not None:
        action, asset_class, index, updated_at = active
        try:
            lane_identity = lanes[index].value
        except IndexError:
            lane_identity = ""
        if lane_identity == asset_class and action != "screening-lane":
            rank = 10_000 + index * 20 + (10 if action == "publication-lane" else 0)
            candidates.append(
                (
                    rank,
                    _progress(
                        watchdog,
                        component=f"{_ACTION_COMPONENTS[action]}:{asset_class}",
                        updated_at=updated_at,
                        timeout=timeout,
                        metrics={"active_lane_index": index, "candidate_lanes": len(lanes)},
                        token=f"{request_id}:active:{action}:{index:03d}:{asset_class}",
                    ),
                )
            )

    all_publications_complete = True
    for index, lane in enumerate(lanes):
        asset_class = lane.value
        catalog_name = lane_local._lane_state_name("catalog-lane", index)
        catalog = _valid_lane_state(
            _load_stage(bounded, request_path, catalog_name),
            request_id=request_id,
            asset_class=asset_class,
        )
        if catalog is None:
            all_publications_complete = False
            break
        catalog_time = watchdog._path_mtime(request_path.parent / f"{catalog_name}.json") or request_mtime
        candidates.append(
            (
                10_000 + index * 20 + 5,
                _progress(
                    watchdog,
                    component=f"bounded-catalog-lane-complete:{asset_class}",
                    updated_at=catalog_time,
                    timeout=timeout,
                    metrics={
                        "candidate_lanes": len(lanes),
                        "completed_catalog_lanes": index + 1,
                        "catalog_records": int(catalog.get("record_count") or 0),
                        "peak_rss_bytes": _peak_metric(catalog),
                    },
                    token=f"{request_id}:catalog-lane:{index:03d}:{asset_class}:complete",
                ),
            )
        )

        publication_name = lane_local._lane_state_name("publication-lane", index)
        publication = _valid_lane_state(
            _load_stage(bounded, request_path, publication_name),
            request_id=request_id,
            asset_class=asset_class,
        )
        if publication is None:
            all_publications_complete = False
            break
        publication_states.append((index, asset_class, publication))
        publication_time = watchdog._path_mtime(
            request_path.parent / f"{publication_name}.json"
        ) or catalog_time
        candidates.append(
            (
                10_000 + index * 20 + 15,
                _progress(
                    watchdog,
                    component=f"bounded-publication-lane-complete:{asset_class}",
                    updated_at=publication_time,
                    timeout=timeout,
                    metrics={
                        "candidate_lanes": len(lanes),
                        "completed_publication_lanes": index + 1,
                        "catalog_records": int(publication.get("record_count") or 0),
                        "peak_rss_bytes": _peak_metric(publication),
                        "bounded_provider_publication": int(
                            publication.get("bounded_provider_publication") is True
                        ),
                    },
                    token=f"{request_id}:publication-lane:{index:03d}:{asset_class}:complete",
                ),
            )
        )

    if all_publications_complete and len(publication_states) == len(lanes):
        scheduled = [item for item in publication_states if item[2].get("scheduled") is True]
        scheduled_order = {index: order for order, (index, _asset, _state) in enumerate(scheduled)}

        if active is not None and active[0] == "screening-lane":
            _action, active_asset, active_index, updated_at = active
            order = scheduled_order.get(active_index)
            if order is not None and publication_states[active_index][1] == active_asset:
                candidates.append(
                    (
                        20_000 + order * 20,
                        _progress(
                            watchdog,
                            component=f"bounded-spool-screening-lane:{active_asset}",
                            updated_at=updated_at,
                            timeout=timeout,
                            metrics={
                                "scheduled_lanes": len(scheduled),
                                "completed_screening_lanes": order,
                                "active_lane_index": active_index,
                            },
                            token=(
                                f"{request_id}:active:screening-lane:{active_index:03d}:{active_asset}"
                            ),
                        ),
                    )
                )

        completed_screening = 0
        for order, (index, asset_class, _publication) in enumerate(scheduled):
            lane_name = lane_local._lane_state_name("lane-stage", index)
            lane_state = _load_stage(bounded, request_path, lane_name)
            if not isinstance(lane_state, Mapping) or str(lane_state.get("request_id") or "").strip() != request_id:
                break
            node = lane_state.get("node")
            if not isinstance(node, Mapping) or str(node.get("asset_class") or "").strip().lower() != asset_class:
                break
            completed_screening += 1
            lane_time = watchdog._path_mtime(request_path.parent / f"{lane_name}.json") or request_mtime
            candidates.append(
                (
                    20_000 + order * 20 + 10,
                    _progress(
                        watchdog,
                        component=f"bounded-screening-lane-complete:{asset_class}",
                        updated_at=lane_time,
                        timeout=timeout,
                        metrics={
                            "scheduled_lanes": len(scheduled),
                            "completed_screening_lanes": completed_screening,
                            "decision_eligible_records": int(node.get("decision_eligible_count") or 0),
                            "peak_rss_bytes": _peak_metric(lane_state),
                        },
                        token=f"{request_id}:screening-lane:{index:03d}:{asset_class}:complete",
                    ),
                )
            )

    manifest_path = request_path.parent / "manifest.json"
    try:
        manifest = spool.load_manifest(manifest_path)
    except (OSError, RuntimeError, TypeError, ValueError):
        manifest = None
    if (
        isinstance(manifest, Mapping)
        and manifest.get("request_id") == request_id
        and manifest.get("release") == release
        and manifest.get("decision_epoch") == request.get("decision_epoch")
    ):
        nodes = manifest.get("nodes")
        manifest_time = watchdog._path_mtime(manifest_path) or request_mtime
        candidates.append(
            (
                30_000,
                _progress(
                    watchdog,
                    component="bounded-discovery-manifest-complete",
                    updated_at=manifest_time,
                    timeout=timeout,
                    metrics={"scheduled_lanes": len(nodes) if isinstance(nodes, list) else 0},
                    token=f"{request_id}:manifest:complete",
                ),
            )
        )

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def lane_local_bounded_discovery_progress(
    values: Mapping[str, str], *, boundary: datetime
):
    """Return the newest logical per-lane progress for the current exact release."""

    from operations import comprehensive_discovery_input_spool as spool

    try:
        root = spool._root(values)
        request_paths = tuple(root.glob("*/*/request.json"))
    except (OSError, RuntimeError, ValueError):
        return None

    best = None
    best_request_time = None
    for request_path in request_paths:
        progress = _lane_local_request_progress(
            request_path,
            values,
            boundary=boundary,
        )
        if progress is None:
            continue
        try:
            request_time = request_path.stat().st_mtime
        except OSError:
            continue
        if best is None or best_request_time is None or request_time > best_request_time:
            best = progress
            best_request_time = request_time
    return best


def install_lane_local_watchdog_progress() -> None:
    """Overlay the legacy bounded reader with the current lane-local state contract."""

    from operations import release_prequalification_parent_watchdog as watchdog

    current = watchdog._bounded_discovery_progress
    if getattr(current, _INSTALLED_ATTR, False):
        return

    def combined(values: Mapping[str, str], *, boundary: datetime):
        lane_local = lane_local_bounded_discovery_progress(values, boundary=boundary)
        if lane_local is not None:
            return lane_local
        return current(values, boundary=boundary)

    setattr(combined, _INSTALLED_ATTR, True)
    setattr(combined, "_legacy_bounded_discovery_progress", current)
    watchdog._bounded_discovery_progress = combined


__all__ = [
    "install_lane_local_watchdog_progress",
    "lane_local_bounded_discovery_progress",
    "record_active_lane_watchdog_progress",
]
