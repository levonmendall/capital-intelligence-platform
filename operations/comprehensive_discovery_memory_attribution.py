"""Credential-safe memory attribution for stage-isolated comprehensive discovery.

The fail-closed resource guard intentionally treats the cgroup raw-memory hard ceiling as
an independent safety boundary.  Production telemetry has repeatedly shown that this raw
charge can be dominated by inactive/file-backed memory while process working sets remain
healthy.  This module therefore records *advisory-only* attribution snapshots at existing
stage and lane boundaries.  It never changes a memory boundary or evidence rule.

Snapshots combine selected cgroup ``memory.stat`` counters with bounded, stat-only disk
footprints for the persistent evidence stores.  Directory scans never follow symlinks and
stop after a fixed entry budget.  Failure to read cgroup or filesystem attribution is
fail-soft: the substantive evidence path and the outer memory guard remain authoritative.

The existing lane-progress projection remains integrity/release validated.  Only an
explicit allowlist of nonnegative integer metrics may flow into credential-safe terminal
failure telemetry.  This module has no decision, candidate, sizing, construction,
execution, or real-money authority.
"""

from __future__ import annotations

import os
import stat as stat_module
from datetime import datetime
from pathlib import Path
from typing import Mapping


_ACTIVE_COMPONENTS = {
    "bounded-spool-catalog-lane": "catalog-lane",
    "bounded-spool-publication-lane": "publication-lane",
    "bounded-spool-screening-lane": "screening-lane",
}
_COMPLETED_COMPONENTS = {
    "bounded-catalog-lane-complete": "catalog-lane",
    "bounded-publication-lane-complete": "publication-lane",
    "bounded-screening-lane-complete": "screening-lane",
}

_CGROUP_KEYS = {
    "anon": "memory_cgroup_anon_kib",
    "file": "memory_cgroup_file_kib",
    "shmem": "memory_cgroup_shmem_kib",
    "file_mapped": "memory_cgroup_file_mapped_kib",
    "file_dirty": "memory_cgroup_file_dirty_kib",
    "file_writeback": "memory_cgroup_file_writeback_kib",
    "inactive_file": "memory_cgroup_inactive_file_kib",
    "active_file": "memory_cgroup_active_file_kib",
    "kernel": "memory_cgroup_kernel_kib",
    "sock": "memory_cgroup_sock_kib",
    "pagetables": "memory_cgroup_pagetables_kib",
    "slab_reclaimable": "memory_cgroup_slab_reclaimable_kib",
    "slab_unreclaimable": "memory_cgroup_slab_unreclaimable_kib",
}
_V1_CGROUP_KEYS = {
    "total_rss": "memory_cgroup_anon_kib",
    "total_cache": "memory_cgroup_file_kib",
    "total_inactive_file": "memory_cgroup_inactive_file_kib",
    "total_active_file": "memory_cgroup_active_file_kib",
}
_STORE_TOP_LEVEL = {
    "historical_evidence": "historical",
    "comprehensive-discovery-spool": "discovery_spool",
    "continuous_evidence_plane": "continuous_evidence",
    "reference_readiness": "reference",
}
_STORE_SCAN_ENTRY_LIMIT = 20_000

_ATTRIBUTION_METRICS = frozenset(
    {
        "memory_raw_current_kib",
        "memory_working_set_current_kib",
        *_CGROUP_KEYS.values(),
        "memory_cgroup_file_unmapped_kib",
        "memory_store_data_total_kib",
        "memory_store_data_file_count",
        "memory_store_historical_kib",
        "memory_store_historical_file_count",
        "memory_store_historical_sqlite_kib",
        "memory_store_historical_wal_kib",
        "memory_store_historical_shm_kib",
        "memory_store_discovery_spool_kib",
        "memory_store_discovery_spool_file_count",
        "memory_store_reference_kib",
        "memory_store_reference_file_count",
        "memory_store_continuous_evidence_kib",
        "memory_store_continuous_evidence_file_count",
        "memory_store_other_kib",
        "memory_store_other_file_count",
        "memory_store_scan_truncated",
        "memory_store_scan_entries",
    }
)
_SAFE_METRICS = frozenset(
    {
        "active_lane_index",
        "candidate_lanes",
        "completed_catalog_lanes",
        "completed_publication_lanes",
        "completed_screening_lanes",
        "scheduled_lanes",
        "catalog_records",
        "decision_eligible_records",
        "peak_rss_bytes",
        "bounded_provider_publication",
        *_ATTRIBUTION_METRICS,
    }
)


def _component_identity(component: str) -> tuple[str, str | None, str]:
    normalized = str(component or "").strip().lower()
    if normalized == "bounded-discovery-manifest-complete":
        return "manifest", None, "completed"

    prefix, separator, asset_class = normalized.partition(":")
    if not separator or not asset_class:
        return "unknown", None, "unknown"
    if prefix in _ACTIVE_COMPONENTS:
        return _ACTIVE_COMPONENTS[prefix], asset_class, "active"
    if prefix in _COMPLETED_COMPONENTS:
        return _COMPLETED_COMPONENTS[prefix], asset_class, "completed"
    return "unknown", asset_class, "unknown"


def _safe_metrics(metrics: object) -> dict[str, int]:
    if not isinstance(metrics, Mapping):
        return {}
    safe: dict[str, int] = {}
    for name in _SAFE_METRICS:
        value = metrics.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            safe[name] = value
    return safe


def safe_persisted_attribution_metrics(metrics: object) -> dict[str, int]:
    """Return only persisted attribution integers approved for public failure telemetry."""

    safe = _safe_metrics(metrics)
    return {name: value for name, value in safe.items() if name in _ATTRIBUTION_METRICS}


def _context_from_progress(observed: object) -> dict[str, object] | None:
    component = str(getattr(observed, "component", "") or "").strip().lower()
    substage, asset_class, progress_kind = _component_identity(component)
    recorded_at = getattr(observed, "updated_at", None)
    if not isinstance(recorded_at, datetime):
        recorded_at = getattr(observed, "recorded_at", None)
    if not component or not isinstance(recorded_at, datetime):
        return None

    metrics = _safe_metrics(getattr(observed, "metrics", None))
    lane_index = metrics.get("active_lane_index") if progress_kind == "active" else None
    return {
        "component": component,
        "substage": substage,
        "asset_class": asset_class,
        "progress_kind": progress_kind,
        "active_lane_index": lane_index,
        "recorded_at": recorded_at.isoformat(),
        "metrics": metrics,
        "credential_safe": True,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _kib(value_bytes: object) -> int | None:
    if isinstance(value_bytes, bool) or not isinstance(value_bytes, int) or value_bytes < 0:
        return None
    return value_bytes // 1024


def _cgroup_stat_metrics() -> dict[str, int]:
    """Read selected cgroup composition counters without changing resource state."""

    from operations import reclaimable_memory_guard as memory_guard

    v2 = memory_guard._read_key_values(Path("/sys/fs/cgroup/memory.stat"))
    metrics: dict[str, int] = {}
    if v2:
        for source, target in _CGROUP_KEYS.items():
            value = _kib(v2.get(source))
            if value is not None:
                metrics[target] = value
        return metrics

    v1 = memory_guard._read_key_values(Path("/sys/fs/cgroup/memory/memory.stat"))
    for source, target in _V1_CGROUP_KEYS.items():
        value = _kib(v1.get(source))
        if value is not None:
            metrics[target] = value
    return metrics


def _store_bucket(top_level_name: str) -> str:
    return _STORE_TOP_LEVEL.get(top_level_name, "other")


def _bounded_data_store_metrics(values: Mapping[str, str]) -> dict[str, int]:
    """Measure persistent evidence footprints with stat-only, symlink-safe traversal."""

    raw = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip()
    if not raw:
        return {}
    root = Path(raw).expanduser()
    try:
        if not root.is_dir():
            return {}
    except OSError:
        return {}

    bytes_by_bucket = {
        "historical": 0,
        "discovery_spool": 0,
        "reference": 0,
        "continuous_evidence": 0,
        "other": 0,
    }
    files_by_bucket = {name: 0 for name in bytes_by_bucket}
    total_bytes = 0
    total_files = 0
    historical_sqlite = 0
    historical_wal = 0
    historical_shm = 0
    entries_seen = 0
    truncated = False
    stack: list[tuple[Path, str]] = []

    try:
        with os.scandir(root) as iterator:
            for entry in iterator:
                entries_seen += 1
                if entries_seen > _STORE_SCAN_ENTRY_LIMIT:
                    truncated = True
                    break
                if entry.is_symlink():
                    continue
                bucket = _store_bucket(entry.name)
                if entry.is_dir(follow_symlinks=False):
                    stack.append((Path(entry.path), bucket))
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if not stat_module.S_ISREG(info.st_mode):
                    continue
                size = max(0, int(info.st_size))
                total_bytes += size
                total_files += 1
                bytes_by_bucket[bucket] += size
                files_by_bucket[bucket] += 1
    except OSError:
        return {}

    while stack and not truncated:
        directory, bucket = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    entries_seen += 1
                    if entries_seen > _STORE_SCAN_ENTRY_LIMIT:
                        truncated = True
                        break
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append((Path(entry.path), bucket))
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if not stat_module.S_ISREG(info.st_mode):
                        continue
                    size = max(0, int(info.st_size))
                    total_bytes += size
                    total_files += 1
                    bytes_by_bucket[bucket] += size
                    files_by_bucket[bucket] += 1
                    if bucket == "historical":
                        if entry.name == "market_history.sqlite3":
                            historical_sqlite += size
                        elif entry.name == "market_history.sqlite3-wal":
                            historical_wal += size
                        elif entry.name == "market_history.sqlite3-shm":
                            historical_shm += size
        except OSError:
            continue

    return {
        "memory_store_data_total_kib": total_bytes // 1024,
        "memory_store_data_file_count": total_files,
        "memory_store_historical_kib": bytes_by_bucket["historical"] // 1024,
        "memory_store_historical_file_count": files_by_bucket["historical"],
        "memory_store_historical_sqlite_kib": historical_sqlite // 1024,
        "memory_store_historical_wal_kib": historical_wal // 1024,
        "memory_store_historical_shm_kib": historical_shm // 1024,
        "memory_store_discovery_spool_kib": bytes_by_bucket["discovery_spool"] // 1024,
        "memory_store_discovery_spool_file_count": files_by_bucket["discovery_spool"],
        "memory_store_reference_kib": bytes_by_bucket["reference"] // 1024,
        "memory_store_reference_file_count": files_by_bucket["reference"],
        "memory_store_continuous_evidence_kib": bytes_by_bucket["continuous_evidence"] // 1024,
        "memory_store_continuous_evidence_file_count": files_by_bucket["continuous_evidence"],
        "memory_store_other_kib": bytes_by_bucket["other"] // 1024,
        "memory_store_other_file_count": files_by_bucket["other"],
        "memory_store_scan_truncated": int(truncated),
        "memory_store_scan_entries": entries_seen,
    }


def capture_memory_attribution(
    values: Mapping[str, str],
    *,
    phase: str,
    stage: str,
    asset_class: str | None = None,
    lane_index: int | None = None,
    child_return_code: int | None = None,
    include_store_sizes: bool = True,
) -> dict[str, int]:
    """Capture one fail-soft, authority-free memory attribution snapshot."""

    from operations import reclaimable_memory_guard as memory_guard

    try:
        snapshot = memory_guard.memory_snapshot(values)
        metrics: dict[str, int] = {}
        for name, value in (
            ("memory_raw_current_kib", snapshot.raw_current_kib),
            ("memory_working_set_current_kib", snapshot.working_set_kib),
            ("memory_cgroup_anon_kib", snapshot.anon_kib),
            ("memory_cgroup_file_kib", snapshot.file_kib),
            ("memory_cgroup_inactive_file_kib", snapshot.inactive_file_kib),
            ("memory_cgroup_active_file_kib", snapshot.active_file_kib),
            ("memory_cgroup_kernel_kib", snapshot.kernel_kib),
        ):
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                metrics[name] = value
        metrics.update(_cgroup_stat_metrics())
        file_kib = metrics.get("memory_cgroup_file_kib")
        mapped_kib = metrics.get("memory_cgroup_file_mapped_kib")
        if file_kib is not None and mapped_kib is not None:
            metrics["memory_cgroup_file_unmapped_kib"] = max(0, file_kib - mapped_kib)
        if include_store_sizes:
            metrics.update(_bounded_data_store_metrics(values))

        details: dict[str, object] = {
            "memory_attribution_phase": str(phase)[:80],
            "memory_attribution_stage": str(stage)[:80],
            "memory_accounting_source": snapshot.source,
            **metrics,
            "credential_safe": True,
            "decision_authority": False,
            "candidate_authority": False,
            "sizing_authority": False,
            "construction_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
            "advisory_only": True,
        }
        if asset_class:
            details["memory_attribution_asset_class"] = str(asset_class)[:80]
        if isinstance(lane_index, int) and not isinstance(lane_index, bool) and lane_index >= 0:
            details["memory_attribution_lane_index"] = lane_index
        if isinstance(child_return_code, int) and not isinstance(child_return_code, bool):
            details["memory_attribution_child_return_code"] = child_return_code
        try:
            memory_guard._safe_log("cgroup_file_memory_attribution", **details)
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
        return safe_persisted_attribution_metrics(metrics)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        try:
            memory_guard._safe_log(
                "cgroup_file_memory_attribution_failed",
                memory_attribution_phase=str(phase)[:80],
                memory_attribution_stage=str(stage)[:80],
                memory_attribution_error_type=type(error).__name__,
                credential_safe=True,
                decision_authority=False,
                candidate_authority=False,
                sizing_authority=False,
                construction_authority=False,
                execution_authority=False,
                paper_only=True,
                real_money_authorized=False,
                advisory_only=True,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
        return {}


def _current_active_marker_context(
    values: Mapping[str, str],
    *,
    boundary: datetime,
) -> dict[str, object] | None:
    """Read only a current active marker when the reusable request itself is older."""

    from operations import comprehensive_discovery_input_spool as spool
    from operations import lane_local_comprehensive_discovery_spool as lane_local
    from operations import lane_local_watchdog_progress as lane_progress

    try:
        root = spool._root(values)
        request_paths = tuple(root.glob("*/*/request.json"))
        release = spool._release(values)
        lanes = tuple(lane_local._candidate_lanes())
    except (OSError, RuntimeError, TypeError, ValueError):
        return None

    best: tuple[datetime, dict[str, object]] | None = None
    for request_path in request_paths:
        request = lane_progress._load_request_identity(request_path, spool)
        if not isinstance(request, Mapping):
            continue
        request_id = str(request.get("request_id") or "").strip()
        if not request_id or str(request.get("release") or "").strip() != release:
            continue
        active = lane_progress._load_active_state(
            request_path,
            request_id=request_id,
            release=release,
            boundary=boundary,
        )
        if active is None:
            continue
        action, asset_class, index, updated_at = active
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            continue
        try:
            lane_identity = str(lanes[index].value).strip().lower()
        except IndexError:
            continue
        if lane_identity != asset_class or action not in lane_progress._ACTION_COMPONENTS:
            continue

        component = f"{lane_progress._ACTION_COMPONENTS[action]}:{asset_class}"
        context = _context_from_progress(
            type(
                "_ActiveLaneProgress",
                (),
                {
                    "component": component,
                    "updated_at": updated_at,
                    "metrics": {
                        "active_lane_index": index,
                        "candidate_lanes": len(lanes),
                    },
                },
            )()
        )
        if context is None:
            continue
        if best is None or updated_at > best[0]:
            best = (updated_at, context)
    return None if best is None else best[1]


def lane_local_memory_failure_context(
    values: Mapping[str, str],
    *,
    boundary: datetime,
) -> dict[str, object] | None:
    """Return the newest exact-release lane progress suitable for failure telemetry."""

    from operations.lane_local_watchdog_progress import (
        lane_local_bounded_discovery_progress,
    )

    observed = lane_local_bounded_discovery_progress(values, boundary=boundary)
    context = None if observed is None else _context_from_progress(observed)
    if context is not None:
        return context

    return _current_active_marker_context(values, boundary=boundary)


__all__ = [
    "_ATTRIBUTION_METRICS",
    "capture_memory_attribution",
    "lane_local_memory_failure_context",
    "safe_persisted_attribution_metrics",
]
