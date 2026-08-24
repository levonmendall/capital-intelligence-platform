"""Memory-bounded comprehensive-discovery lane worker for telemetry #698 repair.

This revision retains the second-level lane isolation and low-lifetime screening from
``bounded_lane_comprehensive_discovery_worker`` while also replacing the remaining
in-memory provider-publication writer with the SQLite-spooled bounded publisher.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from cio import CandidateAssetClass
from operations import bounded_comprehensive_discovery_spool as _bounded
from operations import bounded_lane_comprehensive_discovery_worker as _base
from operations import bounded_provider_preselection_publication as _publication
from operations import comprehensive_discovery_input_spool as _legacy
from operations import lane_local_comprehensive_discovery_spool as _lane_local
from operations import reclaimable_memory_guard as _memory_guard
from operations.evidence_file_cache_release import release_current_reference_file_cache

_MODULE = "operations.bounded_lane_comprehensive_discovery_worker_v2"
_MEMORY_HIGH_WATER_ENV = (
    "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_HIGH_WATER_FRACTION"
)
_MEMORY_RESERVE_ENV = "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_RESERVE_MB"
_DEFAULT_MEMORY_HIGH_WATER_FRACTION = 0.70
_DEFAULT_MEMORY_RESERVE_MB = 640.0
_CATALOG_HANDOFF_RECLAIM_MARGIN_KIB = 32 * 1024


def _memory_high_water_fraction(values: Mapping[str, str]) -> float:
    """Mirror the existing bounded-worker working-set configuration without changing it."""

    raw = str(values.get(_MEMORY_HIGH_WATER_ENV) or "").strip()
    if not raw:
        return _DEFAULT_MEMORY_HIGH_WATER_FRACTION
    value = float(raw)
    if not 0.5 <= value < 0.9:
        raise ValueError(f"{_MEMORY_HIGH_WATER_ENV} must be at least 0.5 and below 0.9")
    return value


def _memory_reserve_kib(values: Mapping[str, str]) -> int:
    """Mirror the existing bounded-worker service reserve without changing it."""

    raw = str(values.get(_MEMORY_RESERVE_ENV) or "").strip()
    value = _DEFAULT_MEMORY_RESERVE_MB if not raw else float(raw)
    if value < 256.0:
        raise ValueError(f"{_MEMORY_RESERVE_ENV} must be at least 256")
    return int(value * 1024)


def _safe_reclaim_log(event: str, **details: object) -> None:
    try:
        _memory_guard._safe_log(event, **details)
    except (OSError, TypeError, ValueError):
        pass


def _release_catalog_lane_reference_cache(
    values: Mapping[str, str],
    *,
    phase: str,
) -> tuple[object, ...]:
    """Make completed reference files reclaimable without affecting evidence authority."""

    try:
        released = tuple(release_current_reference_file_cache(values))
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        _safe_reclaim_log(
            "catalog_lane_reference_cache_release_failed",
            catalog_reclaim_phase=phase,
            cache_release_error_type=type(error).__name__,
            advisory_only=True,
        )
        return ()
    _safe_reclaim_log(
        "catalog_lane_reference_cache_release",
        catalog_reclaim_phase=phase,
        cache_release_file_count=len(released),
        advisory_only=True,
    )
    return released


def _reclaim_catalog_lane_cgroup_cache(
    values: Mapping[str, str],
    *,
    phase: str = "handoff",
):
    """Preempt raw-only cgroup pressure around durable catalog persistence.

    This is deliberately advisory. The outer reclaimable-memory guard retains exclusive
    authority to terminate an unsafe child and still uses the unchanged working-set and raw
    boundaries. At the catalog persistence seam we begin reclaim one existing reclaim
    margin before the raw hard ceiling, reuse the guard's capped cgroup-v2 implementation,
    and remeasure immediately. Failure is fail-soft and cannot change evidence state.
    """

    try:
        snapshot = _memory_guard.memory_snapshot(values)
        if snapshot.limit_kib is None:
            _safe_reclaim_log(
                "catalog_lane_reclaim_checkpoint",
                catalog_reclaim_phase=phase,
                memory_accounting_source=snapshot.source,
                memory_reclaim_attempted=False,
                reclaim_skip_reason="memory_limit_unavailable",
                advisory_only=True,
            )
            return None
        boundaries = _memory_guard.memory_boundaries(
            snapshot.limit_kib,
            working_set_fraction=_memory_high_water_fraction(values),
            working_set_reserve_kib=_memory_reserve_kib(values),
            values=values,
        )
        reason = _memory_guard.limit_reason(snapshot, boundaries)
        # Never let an operational cache advisory obscure genuine working-set pressure.
        if reason == "working_set":
            _safe_reclaim_log(
                "catalog_lane_reclaim_checkpoint",
                catalog_reclaim_phase=phase,
                memory_accounting_source=snapshot.source,
                container_memory_current_kib=snapshot.raw_current_kib,
                container_memory_working_set_kib=snapshot.working_set_kib,
                container_memory_inactive_file_kib=snapshot.inactive_file_kib,
                container_memory_active_file_kib=snapshot.active_file_kib,
                working_set_boundary_kib=boundaries.working_set_kib,
                raw_hard_boundary_kib=boundaries.raw_hard_kib,
                memory_reclaim_attempted=False,
                reclaim_skip_reason="working_set_pressure",
                advisory_only=True,
            )
            return None
        reclaim_boundary = max(
            boundaries.working_set_kib + 1,
            boundaries.raw_hard_kib - _CATALOG_HANDOFF_RECLAIM_MARGIN_KIB,
        )
        raw = snapshot.raw_current_kib
        if raw is None or raw < reclaim_boundary:
            _safe_reclaim_log(
                "catalog_lane_reclaim_checkpoint",
                catalog_reclaim_phase=phase,
                memory_accounting_source=snapshot.source,
                container_memory_current_kib=raw,
                container_memory_working_set_kib=snapshot.working_set_kib,
                container_memory_inactive_file_kib=snapshot.inactive_file_kib,
                container_memory_active_file_kib=snapshot.active_file_kib,
                working_set_boundary_kib=boundaries.working_set_kib,
                raw_hard_boundary_kib=boundaries.raw_hard_kib,
                catalog_handoff_reclaim_boundary_kib=reclaim_boundary,
                memory_reclaim_attempted=False,
                reclaim_skip_reason="below_preemptive_margin",
                advisory_only=True,
            )
            return None
        proactive_boundaries = _memory_guard.MemoryBoundaries(
            working_set_kib=boundaries.working_set_kib,
            raw_hard_kib=reclaim_boundary,
        )
        result, after = _memory_guard._attempt_cgroup_v2_reclaim(
            snapshot,
            proactive_boundaries,
            values=values,
        )
        _safe_reclaim_log(
            "catalog_lane_reclaim_checkpoint",
            catalog_reclaim_phase=phase,
            memory_accounting_source=snapshot.source,
            memory_reclaim_attempted=result.attempted,
            memory_reclaim_supported=result.supported,
            memory_reclaim_requested_kib=result.requested_kib,
            memory_reclaim_raw_before_kib=result.raw_before_kib,
            memory_reclaim_raw_after_kib=result.raw_after_kib,
            memory_reclaim_working_set_before_kib=result.working_set_before_kib,
            memory_reclaim_working_set_after_kib=result.working_set_after_kib,
            memory_reclaim_inactive_file_before_kib=snapshot.inactive_file_kib,
            memory_reclaim_inactive_file_after_kib=after.inactive_file_kib,
            memory_reclaim_active_file_before_kib=snapshot.active_file_kib,
            memory_reclaim_active_file_after_kib=after.active_file_kib,
            memory_reclaim_delta_kib=result.reclaimed_kib,
            memory_reclaim_effective=result.effective,
            memory_reclaim_error_type=result.error_type,
            catalog_handoff_reclaim_boundary_kib=reclaim_boundary,
            working_set_boundary_kib=boundaries.working_set_kib,
            raw_hard_boundary_kib=boundaries.raw_hard_kib,
            post_reclaim_guard_reason=_memory_guard.limit_reason(after, boundaries),
            advisory_only=True,
        )
        return result
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        _safe_reclaim_log(
            "catalog_lane_reclaim_checkpoint_failed",
            catalog_reclaim_phase=phase,
            memory_reclaim_error_type=type(error).__name__,
            advisory_only=True,
        )
        return None


def _catalog_lane_stage(
    request_path: str | Path,
    values: Mapping[str, str],
    *,
    asset_class_value: str,
    index: int,
) -> None:
    """Reclaim source/cache pressure immediately around raw-catalog persistence.

    The lane-local catalog algorithm reconstructs a complete lane and then persists one
    integrity-checked raw-catalog pickle before writing durable stage state and publishing
    completion. The outer cgroup guard samples continuously, so waiting until completion to
    reclaim can lose the race. This wrapper therefore intercepts only that raw-catalog
    pickle write in the finite child: source reference cache is released and bounded cgroup
    reclaim is attempted immediately before persistence, then one second bounded reclaim is
    attempted after the durable pickle write. The canonical lane algorithm is unchanged.
    """

    expected_blob = (
        f"raw-catalog-{index:03d}-{_legacy._safe_release(asset_class_value)}.pkl"
    )
    original_write_pickle_blob = _legacy._write_pickle_blob

    def write_pickle_with_catalog_reclaim(directory, name, value):
        if str(name) != expected_blob:
            return original_write_pickle_blob(directory, name, value)
        _release_catalog_lane_reference_cache(values, phase="pre_persist")
        _reclaim_catalog_lane_cgroup_cache(values, phase="pre_persist")
        descriptor = original_write_pickle_blob(directory, name, value)
        _reclaim_catalog_lane_cgroup_cache(values, phase="post_persist")
        return descriptor

    _legacy._write_pickle_blob = write_pickle_with_catalog_reclaim
    try:
        _lane_local._catalog_lane_stage(
            request_path,
            values,
            asset_class_value=asset_class_value,
            index=index,
        )
    finally:
        _legacy._write_pickle_blob = original_write_pickle_blob


def _publication_lane_stage(
    request_path: str | Path,
    values: Mapping[str, str],
    *,
    asset_class_value: str,
    index: int,
) -> None:
    stage = f"bounded_publication_lane:{asset_class_value}"
    path = Path(request_path).expanduser()
    try:
        request, policy = _bounded._validate_request(path, values)
        timestamp = _legacy._parse_timestamp(
            request.get("decision_epoch"), field_name="decision_epoch"
        )
        catalog_state = _bounded._load_stage_state(
            path, _lane_local._lane_state_name("catalog-lane", index)
        )
        asset_class = CandidateAssetClass(asset_class_value)
        if str(catalog_state.get("asset_class") or "") != asset_class.value:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "lane-local catalog identity changed before provider publication"
            )
        raw = _legacy._load_pickle_blob(
            path.parent, _legacy._descriptor(catalog_state.get("blob"))
        )
        if not isinstance(raw, Sequence) or isinstance(
            raw, (str, bytes, bytearray)
        ):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"{asset_class.value} lane-local raw catalog shard is malformed"
            )

        from operations import comprehensive_market_discovery as facade

        core = facade._core
        merged = _base._merge_certified_lane(
            core, raw, asset_class=asset_class, timestamp=timestamp
        )
        del raw

        required = asset_class in core._base._DEFAULT_REQUIRED_DISCOVERY_LANES
        dynamic = bool(required or merged)
        scheduled = bool(
            dynamic and core._base._lane_is_scheduled(asset_class, timestamp)
        )

        descriptor = _legacy._write_pickle_blob(
            path.parent,
            f"merged-catalog-{index:03d}-{_legacy._safe_release(asset_class.value)}.pkl",
            merged,
        )
        publication_path: str | None = None
        if scheduled:
            publication_path = str(
                path.parent
                / (
                    "provider-preselection-"
                    f"{index:03d}-{_legacy._safe_release(asset_class.value)}.json"
                )
            )
            lane_policy = replace(
                policy, provider_preselection_path=publication_path
            )
            try:
                publication = _publication.ensure_provider_preselection_publication(
                    {asset_class: merged},
                    as_of=timestamp,
                    policy=lane_policy,
                    market_probe=core.default_provider_preselection_market_probe,
                )
            except _publication.ProviderPreselectionPublicationError as error:
                raise _legacy.ComprehensiveDiscoverySpoolError(str(error)) from error
            if int(getattr(publication, "catalog_count", -1)) != len(merged):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"{asset_class.value} lane-local provider publication count changed"
                )
            del publication

        peak = _bounded._peak_rss_bytes()
        _bounded._write_stage_state(
            path,
            _lane_local._lane_state_name("publication-lane", index),
            {
                "request_id": request.get("request_id"),
                "asset_class": asset_class.value,
                "blob": _legacy._descriptor_dict(descriptor),
                "record_count": len(merged),
                "dynamic": dynamic,
                "scheduled": scheduled,
                "provider_preselection_path": publication_path,
                "peak_rss_bytes": peak,
                "bounded_provider_publication": True,
            },
        )
        core.record_manual_cio_diagnostic_progress(
            f"bounded_spool_publication_lane_complete:{asset_class.value}",
            metrics={"catalog_records": len(merged), "peak_rss_bytes": peak},
        )
    except BaseException as error:  # noqa: BLE001 - durable fail-closed attribution.
        try:
            _legacy._write_failure(path, stage=stage, error=error, values=values)
        except BaseException:
            pass
        raise


def run_stage(
    action: str,
    request_path: Path,
    values: Mapping[str, str],
    *,
    asset_class: str,
    index: int,
) -> None:
    command = (
        sys.executable,
        "-m",
        _MODULE,
        action,
        "--request",
        str(request_path),
        "--asset-class",
        asset_class,
        "--index",
        str(index),
    )
    process = subprocess.Popen(
        command,
        cwd=str(Path(__file__).resolve().parents[1]),
        env=dict(values),
        start_new_session=False,
    )
    return_code = int(process.wait())
    if return_code == 0:
        return

    failure = _legacy.load_failure(request_path)
    if failure is None:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            "bounded lane comprehensive discovery stage exited without attribution; "
            f"action={action}; asset_class={asset_class}; return_code={return_code}"
        )
    raise _legacy.ComprehensiveDiscoverySpoolError(
        "bounded lane comprehensive discovery stage failed; "
        f"asset_class={asset_class}; "
        f"stage={failure.get('failure_stage')}; "
        f"failure_type={failure.get('error_type')}; "
        f"detail={failure.get('error_detail')}"
    )


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("catalog-lane", "publication-lane", "screening-lane")
    )
    parser.add_argument("--request", required=True)
    parser.add_argument("--asset-class", required=True)
    parser.add_argument("--index", required=True, type=int)
    args = parser.parse_args(argv)
    values = dict(os.environ)
    try:
        if args.action == "catalog-lane":
            _catalog_lane_stage(
                args.request,
                values,
                asset_class_value=args.asset_class,
                index=args.index,
            )
        elif args.action == "publication-lane":
            _publication_lane_stage(
                args.request,
                values,
                asset_class_value=args.asset_class,
                index=args.index,
            )
        else:
            _base._screening_lane_stage(
                args.request,
                values,
                asset_class_value=args.asset_class,
                index=args.index,
            )
    except BaseException as error:  # noqa: BLE001 - finite subprocess stays fail-closed.
        print(
            f"bounded lane comprehensive discovery failed: {type(error).__name__}",
            file=sys.stderr,
            flush=True,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "_catalog_lane_stage",
    "_publication_lane_stage",
    "_reclaim_catalog_lane_cgroup_cache",
    "run_stage",
]
