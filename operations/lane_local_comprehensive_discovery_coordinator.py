"""Compact coordinator for lane-local comprehensive-discovery materialization.

Heavy catalog, publication, and terminal-screening work remains in finite subprocesses.
The coordinator retains descriptors and counts only; it never hydrates a complete market
catalog or provider-factor publication.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from operations import bounded_lane_comprehensive_discovery_worker_v2 as _worker
from operations import comprehensive_discovery_input_spool as _legacy
from operations import lane_local_comprehensive_discovery_spool as _lane_local


def _record_active_lane_stage(action: str, asset_class: str) -> None:
    from operations import manual_cio_diagnostic as diagnostic

    progress_stage = {
        "catalog-lane": "bounded_spool_catalog_lane",
        "publication-lane": "bounded_spool_publication_lane",
        "screening-lane": "bounded_spool_screening_lane",
    }[action]
    diagnostic.record_manual_cio_diagnostic_progress(f"{progress_stage}:{asset_class}")


def _run_stage(
    action: str,
    path: Path,
    values: Mapping[str, str],
    *,
    asset_class: str,
    index: int,
) -> None:
    _record_active_lane_stage(action, asset_class)
    # Keep a request-local logical start marker for the parent watchdog.  This state is
    # observability-only and fail-contained: inability to publish it must not change the
    # child stage's own result.  Re-entering the same lane/substage yields the same logical
    # token, so retries cannot manufacture indefinite liveness.
    try:
        from operations.lane_local_watchdog_progress import (
            record_active_lane_watchdog_progress,
        )

        record_active_lane_watchdog_progress(
            path,
            values,
            action=action,
            asset_class=asset_class,
            index=index,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    _worker.run_stage(
        action,
        path,
        values,
        asset_class=asset_class,
        index=index,
    )


def build_spool(
    request_path: str | Path,
    *,
    values: Mapping[str, str] | None = None,
) -> Path:
    resolved_values = dict(os.environ if values is None else values)
    path = Path(request_path).expanduser()
    try:
        request, policy = _lane_local._bounded._validate_request(path, resolved_values)
        if _legacy.manifest_available(path):
            return _legacy._manifest_path(path)

        states = []
        for index, asset_class in enumerate(_lane_local._candidate_lanes()):
            _run_stage(
                "catalog-lane",
                path,
                resolved_values,
                asset_class=asset_class.value,
                index=index,
            )
            _run_stage(
                "publication-lane",
                path,
                resolved_values,
                asset_class=asset_class.value,
                index=index,
            )
            state = _lane_local._bounded._load_stage_state(
                path, _lane_local._lane_state_name("publication-lane", index)
            )
            states.append((index, asset_class, state))

        node_bodies = []
        rebound_count = 0
        lane_peaks: dict[str, int] = {}
        merged_shards = []
        lane_paths = []
        catalog_count = 0
        for index, asset_class, state in states:
            if state.get("dynamic") is not True:
                continue
            merged_shards.append(
                {
                    "asset_class": asset_class.value,
                    "blob": _legacy._descriptor_dict(
                        _legacy._descriptor(state.get("blob"))
                    ),
                    "record_count": int(state.get("record_count", 0)),
                }
            )
            catalog_count += int(state.get("record_count", 0))
            publication_path = str(state.get("provider_preselection_path") or "")
            if publication_path:
                lane_paths.append((asset_class.value, publication_path))
            lane_peaks[asset_class.value] = int(state.get("peak_rss_bytes", 0))
            if state.get("scheduled") is not True:
                continue

            _run_stage(
                "screening-lane",
                path,
                resolved_values,
                asset_class=asset_class.value,
                index=index,
            )
            lane_state = _lane_local._bounded._load_stage_state(
                path, _lane_local._lane_state_name("lane-stage", index)
            )
            node = lane_state.get("node")
            if not isinstance(node, Mapping):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"lane-local screening produced no node for {asset_class.value}"
                )
            node_bodies.append(dict(node))
            rebound_count += int(bool(lane_state.get("compatibility_rebound")))
            lane_peaks[asset_class.value] = max(
                lane_peaks[asset_class.value],
                int(lane_state.get("peak_rss_bytes", 0)),
            )

        if not node_bodies:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "lane-local builder found no scheduled comprehensive-discovery lanes"
            )

        publication_index_path = path.parent / "lane-publication-index.json"
        _legacy._atomic_json(
            publication_index_path,
            {
                "schema_version": "lane-local-provider-publication-index.v1",
                "request_id": request.get("request_id"),
                "catalog_count": catalog_count,
                "lane_paths": [list(item) for item in lane_paths],
                **_legacy._authority_fields(),
            },
        )
        publication = _lane_local.LanePublicationIndex(
            path=str(publication_index_path),
            catalog_count=catalog_count,
            lane_paths=tuple(lane_paths),
        )
        publication_descriptor = _legacy._write_pickle_blob(
            path.parent,
            "finalizer-publication-index.pkl",
            publication,
        )
        request_policy = _legacy._descriptor(request.get("policy_blob"))
        material: dict[str, object] = {
            "schema_version": _legacy._SCHEMA,
            "request_id": str(request.get("request_id") or ""),
            "release": _legacy._release(resolved_values),
            "decision_epoch": str(request.get("decision_epoch") or ""),
            "policy_version": str(getattr(policy, "version", "")),
            "policy_blob": _legacy._descriptor_dict(request_policy),
            "raw_catalog_shards": merged_shards,
            "publication_blob": _legacy._descriptor_dict(publication_descriptor),
            "lane_publications": [list(item) for item in lane_paths],
            "compatibility_rebound_count": rebound_count,
            "bounded_memory_builder": True,
            "lane_local_catalogs": True,
            "second_level_lane_memory_bound": True,
            "bounded_provider_publication": True,
            "builder_peak_rss_bytes": {"lanes": lane_peaks},
            "nodes": node_bodies,
            **_legacy._authority_fields(),
        }
        body = dict(material)
        body["manifest_id"] = _legacy._digest(material)
        manifest_path = _legacy._manifest_path(path)
        _legacy._atomic_json(manifest_path, body)
        try:
            (path.parent / "failure.json").unlink()
        except FileNotFoundError:
            pass
        return manifest_path
    except BaseException as error:  # noqa: BLE001 - fail closed with durable attribution.
        try:
            _legacy._write_failure(
                path,
                stage="lane_local_bounded_coordinator",
                error=error,
                values=resolved_values,
            )
        except BaseException:
            pass
        raise


def install_lane_local_comprehensive_discovery_coordinator() -> None:
    """Make the compact coordinator authoritative for spawn-safe spool preparation."""

    from operations import spawn_safe_authoritative_acquisition as spawn_safe

    spawn_safe.build_spool = build_spool


__all__ = ["build_spool", "install_lane_local_comprehensive_discovery_coordinator"]
