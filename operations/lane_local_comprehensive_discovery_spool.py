"""Lane-local bounded-memory comprehensive-discovery spool overlay.

The canonical discovery engine remains unchanged. This module changes only operational
materialization: reference catalogs, certified-catalog merges, provider-factor
publications, and terminal-screening inputs are materialized one asset-class lane at a
time in finite child interpreters. The provider-free finalizer receives a lazy mapping
of already-merged lane shards and therefore never needs a global catalog object graph.

No market, provider, exchange, candidate, evidence, threshold, screening, CIO,
construction, execution, or paper-only rule is relaxed by this module.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

from cio import CandidateAssetClass
from operations import bounded_comprehensive_discovery_spool as _bounded
from operations import comprehensive_discovery_input_spool as _legacy


_MODULE = "operations.lane_local_comprehensive_discovery_spool"


@dataclass(frozen=True, slots=True)
class LanePublicationIndex:
    """Small compatibility handle for lane-local provider publications."""

    path: str
    catalog_count: int
    lane_paths: tuple[tuple[str, str], ...]

    def path_for(self, asset_class: str) -> str | None:
        return dict(self.lane_paths).get(str(asset_class))


class LaneShardCatalogs(Mapping[CandidateAssetClass, Sequence[object]]):
    """Integrity-checked mapping that retains at most one catalog shard at a time."""

    def __init__(
        self,
        manifest_path: str | Path,
        shards: Sequence[Mapping[str, object]],
    ) -> None:
        self._directory = Path(manifest_path).expanduser().parent
        self._shards: dict[CandidateAssetClass, Mapping[str, object]] = {}
        for item in shards:
            asset_class = CandidateAssetClass(str(item.get("asset_class") or ""))
            self._shards[asset_class] = dict(item)
        self._cached_key: CandidateAssetClass | None = None
        self._cached_value: Sequence[object] | None = None

    def __iter__(self) -> Iterator[CandidateAssetClass]:
        return iter(self._shards)

    def __len__(self) -> int:
        return len(self._shards)

    def __getitem__(self, key: CandidateAssetClass) -> Sequence[object]:
        if key == self._cached_key and self._cached_value is not None:
            return self._cached_value
        item = self._shards[key]
        records = _legacy._load_pickle_blob(
            self._directory,
            _legacy._descriptor(item.get("blob")),
        )
        if not isinstance(records, Sequence) or isinstance(
            records, (str, bytes, bytearray)
        ):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"{key.value} lane-local finalizer catalog shard is malformed"
            )
        self._cached_key = key
        self._cached_value = records
        return records


def _serialized_blob_descriptor(value: object) -> dict[str, object]:
    """Normalize a validated slotted blob descriptor for JSON manifest publication."""

    return _legacy._descriptor_dict(_legacy._descriptor(value))


def _lane_state_name(prefix: str, index: int) -> str:
    return f"{prefix}-{index:03d}"


def _candidate_lanes() -> tuple[CandidateAssetClass, ...]:
    return tuple(item for item in CandidateAssetClass if item is not CandidateAssetClass.OTHER)


def _reconstruct_component_records(
    payload: Mapping[str, object],
    *,
    record_type,
) -> tuple[object, ...]:
    from operations import generalized_reference_readiness as generalized
    from operations import reference_readiness as reference

    return tuple(
        reference._record_from_payload(item, record_type)
        for item in generalized._component_records(payload)
    )


def _catalog_lane_stage(
    request_path: str | Path,
    values: Mapping[str, str],
    *,
    asset_class_value: str,
    index: int,
) -> None:
    stage = f"bounded_catalog_lane:{asset_class_value}"
    path = Path(request_path).expanduser()
    try:
        request, policy = _bounded._validate_request(path, values)
        timestamp = _legacy._parse_timestamp(
            request.get("decision_epoch"), field_name="decision_epoch"
        )
        asset_class = CandidateAssetClass(asset_class_value)

        from operations import comprehensive_market_discovery as facade
        from operations import generalized_reference_readiness as generalized
        from operations import supervised_reference_prequalification as supervised

        core = facade._core
        config = core._base.load_comprehensive_market_discovery_config()
        active = core._base.scheduled_discovery_lanes(timestamp)
        records: tuple[object, ...] = ()

        reference_lanes = frozenset(
            (*generalized._EODHD_REFERENCE_LANES, CandidateAssetClass.FUTURE)
        )
        if asset_class in active and asset_class in reference_lanes:
            component = supervised._load_asset_component(
                values,
                discovery=core,
                config=config,
                lane=asset_class,
                timestamp=timestamp,
            )
            if component is None:
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    "qualified lane-scoped reference component is unavailable; "
                    f"lane={asset_class.value}"
                )
            records = _reconstruct_component_records(
                component,
                record_type=core._base._legacy.DiscoveryCatalogRecord,
            )
        elif asset_class is CandidateAssetClass.OPTION and asset_class in active:
            records = tuple(
                core._base._legacy._option_catalog(
                    as_of=timestamp,
                    config=config,
                    policy=policy,
                )
            )

        descriptor = _legacy._write_pickle_blob(
            path.parent,
            f"raw-catalog-{index:03d}-{_legacy._safe_release(asset_class.value)}.pkl",
            records,
        )
        peak = _bounded._peak_rss_bytes()
        _bounded._write_stage_state(
            path,
            _lane_state_name("catalog-lane", index),
            {
                "request_id": request.get("request_id"),
                "asset_class": asset_class.value,
                "blob": _legacy._descriptor_dict(descriptor),
                "record_count": len(records),
                "peak_rss_bytes": peak,
            },
        )
        core.record_manual_cio_diagnostic_progress(
            f"bounded_spool_catalog_lane_complete:{asset_class.value}",
            metrics={"catalog_records": len(records), "peak_rss_bytes": peak},
        )
    except BaseException as error:  # noqa: BLE001 - persist exact finite-stage failure.
        try:
            _legacy._write_failure(path, stage=stage, error=error, values=values)
        except BaseException:
            pass
        raise


def _merge_certified_lane(core: Any, raw: Sequence[object], *, asset_class, timestamp):
    try:
        external = core._base.load_certified_investable_catalog(as_of=timestamp)
    except core._base.CertifiedInvestableCatalogError as error:
        raise _legacy.ComprehensiveDiscoverySpoolError(str(error)) from error

    merged = list(raw)
    for payload in external:
        record = core._base._certified_catalog_record(payload)
        if record.asset_class is asset_class:
            merged.append(record)
    return core._base._legacy._deduplicate(tuple(merged))


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
            path, _lane_state_name("catalog-lane", index)
        )
        asset_class = CandidateAssetClass(asset_class_value)
        if str(catalog_state.get("asset_class") or "") != asset_class.value:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "lane-local catalog identity changed before provider publication"
            )
        raw = _legacy._load_pickle_blob(
            path.parent, _legacy._descriptor(catalog_state.get("blob"))
        )
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"{asset_class.value} lane-local raw catalog shard is malformed"
            )

        from operations import comprehensive_market_discovery as facade

        core = facade._core
        merged = _merge_certified_lane(
            core, raw, asset_class=asset_class, timestamp=timestamp
        )
        del raw
        required = asset_class in core._base._DEFAULT_REQUIRED_DISCOVERY_LANES
        dynamic = bool(required or merged)
        scheduled = bool(dynamic and core._base._lane_is_scheduled(asset_class, timestamp))

        descriptor = _legacy._write_pickle_blob(
            path.parent,
            f"merged-catalog-{index:03d}-{_legacy._safe_release(asset_class.value)}.pkl",
            merged,
        )
        publication_path: str | None = None
        if scheduled:
            publication_path = str(
                path.parent
                / f"provider-preselection-{index:03d}-{_legacy._safe_release(asset_class.value)}.json"
            )
            lane_policy = replace(policy, provider_preselection_path=publication_path)
            try:
                publication = core.ensure_provider_preselection_publication(
                    {asset_class: merged},
                    as_of=timestamp,
                    policy=lane_policy,
                    market_probe=core.default_provider_preselection_market_probe,
                )
            except core.ProviderPreselectionPublicationError as error:
                raise _legacy.ComprehensiveDiscoverySpoolError(str(error)) from error
            if int(getattr(publication, "catalog_count", -1)) != len(merged):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"{asset_class.value} lane-local provider publication count changed"
                )

        peak = _bounded._peak_rss_bytes()
        _bounded._write_stage_state(
            path,
            _lane_state_name("publication-lane", index),
            {
                "request_id": request.get("request_id"),
                "asset_class": asset_class.value,
                "blob": _legacy._descriptor_dict(descriptor),
                "record_count": len(merged),
                "dynamic": dynamic,
                "scheduled": scheduled,
                "provider_preselection_path": publication_path,
                "peak_rss_bytes": peak,
            },
        )
        core.record_manual_cio_diagnostic_progress(
            f"bounded_spool_publication_lane_complete:{asset_class.value}",
            metrics={"catalog_records": len(merged), "peak_rss_bytes": peak},
        )
    except BaseException as error:  # noqa: BLE001 - persist exact finite-stage failure.
        try:
            _legacy._write_failure(path, stage=stage, error=error, values=values)
        except BaseException:
            pass
        raise


def _screening_lane_stage(
    request_path: str | Path,
    values: Mapping[str, str],
    *,
    asset_class_value: str,
    index: int,
) -> None:
    stage = f"bounded_lane_descriptor:{asset_class_value}"
    path = Path(request_path).expanduser()
    try:
        request, policy = _bounded._validate_request(path, values)
        timestamp = _legacy._parse_timestamp(
            request.get("decision_epoch"), field_name="decision_epoch"
        )
        state = _bounded._load_stage_state(
            path, _lane_state_name("publication-lane", index)
        )
        if state.get("scheduled") is not True:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"{asset_class_value} lane-local screening was not scheduled"
            )
        publication_path = str(state.get("provider_preselection_path") or "")
        if not publication_path:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"{asset_class_value} lane-local provider publication is missing"
            )

        held = {
            str(item).strip().upper()
            for item in request.get("held_symbols", ())
            if str(item).strip()
        }
        tracked = {
            str(item).strip().upper()
            for item in request.get("tracked_symbols", ())
            if str(item).strip()
        }
        excluded = {
            str(item).strip().upper()
            for item in request.get("excluded_symbols", ())
            if str(item).strip()
        }
        state_symbols = held | tracked

        from operations import authoritative_comprehensive_discovery as authoritative
        from operations import comprehensive_market_discovery as facade
        from operations import persistent_certification_scheduler as scheduler

        core = facade._core
        asset_class = CandidateAssetClass(asset_class_value)
        records = _legacy._load_pickle_blob(
            path.parent, _legacy._descriptor(state.get("blob"))
        )
        if not isinstance(records, Sequence) or isinstance(
            records, (str, bytes, bytearray)
        ):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"{asset_class.value} lane-local merged catalog shard is malformed"
            )

        catalog_records = core._base._legacy._deduplicate(tuple(records))
        eligible = tuple(
            item
            for item in catalog_records
            if item.symbol not in excluded
            and not (
                item.expiration_at is not None
                and item.expiration_at <= timestamp + timedelta(days=7)
            )
        )
        continuity = tuple(item for item in eligible if item.symbol in state_symbols)
        ordinary = tuple(item for item in eligible if item.symbol not in state_symbols)
        lane_policy = replace(policy, provider_preselection_path=publication_path)
        try:
            bounded = core.build_bounded_terminal_preselection(
                ordinary,
                as_of=timestamp,
                policy=lane_policy,
                progress_label=asset_class.value,
                chunk_size=core._PRODUCTION_TERMINAL_SCREENING_CHUNK_SIZE,
            )
        except core.BoundedTerminalScreeningError as error:
            raise _legacy.ComprehensiveDiscoverySpoolError(str(error)) from error

        deep_records = tuple(dict.fromkeys((*continuity, *bounded.nominated)))
        node_id = f"deep-market-evidence:{asset_class.value}"
        fingerprint = scheduler._digest(
            {
                "record_fingerprint": scheduler._record_fingerprint(deep_records),
                "policy_version": str(getattr(policy, "version", "")),
                "asset_class": asset_class.value,
                "decision_epoch": timestamp.isoformat(),
            }
        )
        node = scheduler.CertificationNode(
            node_id=node_id,
            asset_class=asset_class.value,
            provider_groups=scheduler._provider_groups(asset_class.value),
            input_fingerprint=fingerprint,
            deadline=timestamp
            + timedelta(seconds=scheduler._market_node_valid_seconds(values)),
            decision_eligible_count=len(deep_records),
            priority=len(continuity),
        )
        rebound = authoritative._rebind_compatible_checkpoint(
            values,
            release_sha=scheduler._release(values),
            node=node,
            records=deep_records,
            epoch=timestamp,
            policy_version=str(getattr(policy, "version", "")),
        )
        descriptor = _legacy._write_pickle_blob(
            path.parent,
            f"lane-{index:03d}-{_legacy._safe_release(node.node_id)}.pkl",
            deep_records,
        )
        peak = _bounded._peak_rss_bytes()
        _bounded._write_stage_state(
            path,
            _lane_state_name("lane-stage", index),
            {
                "request_id": request.get("request_id"),
                "node": _legacy._node_body(node, descriptor),
                "compatibility_rebound": bool(rebound),
                "peak_rss_bytes": peak,
            },
        )
    except BaseException as error:  # noqa: BLE001 - persist exact finite-stage failure.
        try:
            _legacy._write_failure(path, stage=stage, error=error, values=values)
        except BaseException:
            pass
        raise


def _run_stage(
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
            f"lane-local comprehensive discovery stage {action} exited without attribution; "
            f"return_code={return_code}"
        )
    raise _legacy.ComprehensiveDiscoverySpoolError(
        "lane-local comprehensive discovery stage failed; "
        f"stage={failure.get('failure_stage')}; "
        f"failure_type={failure.get('error_type')}; "
        f"detail={failure.get('error_detail')}"
    )


def build_spool(
    request_path: str | Path,
    *,
    values: Mapping[str, str] | None = None,
) -> Path:
    resolved_values = dict(os.environ if values is None else values)
    path = Path(request_path).expanduser()
    try:
        request, policy = _bounded._validate_request(path, resolved_values)
        if _legacy.manifest_available(path):
            return _legacy._manifest_path(path)

        states: list[tuple[int, CandidateAssetClass, Mapping[str, object]]] = []
        for index, asset_class in enumerate(_candidate_lanes()):
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
            state = _bounded._load_stage_state(
                path, _lane_state_name("publication-lane", index)
            )
            states.append((index, asset_class, state))

        node_bodies: list[Mapping[str, object]] = []
        rebound_count = 0
        lane_peaks: dict[str, int] = {}
        merged_shards: list[dict[str, object]] = []
        lane_paths: list[tuple[str, str]] = []
        catalog_count = 0
        for index, asset_class, state in states:
            if state.get("dynamic") is not True:
                continue
            merged_shards.append(
                {
                    "asset_class": asset_class.value,
                    "blob": _serialized_blob_descriptor(state.get("blob")),
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
            lane_state = _bounded._load_stage_state(
                path, _lane_state_name("lane-stage", index)
            )
            node = lane_state.get("node")
            if not isinstance(node, Mapping):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"lane-local screening produced no node for {asset_class.value}"
                )
            node_bodies.append(dict(node))
            rebound_count += int(bool(lane_state.get("compatibility_rebound")))
            lane_peaks[asset_class.value] = max(
                lane_peaks[asset_class.value], int(lane_state.get("peak_rss_bytes", 0))
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
        publication = LanePublicationIndex(
            path=str(publication_index_path),
            catalog_count=catalog_count,
            lane_paths=tuple(lane_paths),
        )
        publication_descriptor = _legacy._write_pickle_blob(
            path.parent, "finalizer-publication-index.pkl", publication
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
    except BaseException as error:  # noqa: BLE001 - coordinator remains fail-closed.
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


def load_finalizer_inputs(
    manifest_path: str | Path,
) -> tuple[Mapping[CandidateAssetClass, Sequence[object]], object]:
    body = _legacy.load_manifest(manifest_path)
    if body.get("lane_local_catalogs") is not True:
        return _bounded.load_finalizer_inputs(manifest_path)
    shards = body.get("raw_catalog_shards")
    if not isinstance(shards, list) or not shards:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            "lane-local spool manifest has no catalog shards"
        )
    publication = _legacy._load_pickle_blob(
        Path(manifest_path).expanduser().parent,
        _legacy._descriptor(body.get("publication_blob")),
    )
    if not isinstance(publication, LanePublicationIndex):
        raise _legacy.ComprehensiveDiscoverySpoolError(
            "lane-local provider publication index is malformed"
        )
    return LaneShardCatalogs(manifest_path, shards), publication


def _install_lane_local_finalizer() -> None:
    from operations import authoritative_comprehensive_discovery as authoritative
    from operations import spawn_safe_authoritative_acquisition as spawn_safe

    spawn_safe.build_spool = build_spool
    spawn_safe.load_finalizer_inputs = load_finalizer_inputs
    current = authoritative._provider_free_finalize
    if getattr(current, "_lane_local_comprehensive_finalizer", False):
        return

    def provider_free_finalize(core, delegate, acquisition, **kwargs):
        raw_reference = acquisition.raw_catalogs
        publication_reference = acquisition.publication
        if not (
            isinstance(raw_reference, _legacy.SpoolReference)
            and isinstance(publication_reference, _legacy.SpoolReference)
            and raw_reference.manifest_path == publication_reference.manifest_path
        ):
            return current(core, delegate, acquisition, **kwargs)
        body = _legacy.load_manifest(raw_reference.manifest_path)
        if body.get("lane_local_catalogs") is not True:
            return current(core, delegate, acquisition, **kwargs)
        lane_paths = {
            str(item[0]): str(item[1])
            for item in body.get("lane_publications", ())
            if isinstance(item, Sequence)
            and not isinstance(item, (str, bytes, bytearray))
            and len(item) == 2
        }
        original_merge = core._base._merge_certified_catalog
        original_screen = core.build_bounded_terminal_preselection

        def merged_identity(catalogs, *, as_of):
            if isinstance(catalogs, LaneShardCatalogs):
                return catalogs
            return original_merge(catalogs, as_of=as_of)

        def lane_screen(records, *, as_of, policy, progress_label, chunk_size):
            publication_path = lane_paths.get(str(progress_label))
            if not publication_path:
                raise core.BoundedTerminalScreeningError(
                    f"{progress_label} lane-local provider publication is unavailable"
                )
            lane_policy = replace(
                policy, provider_preselection_path=publication_path
            )
            return original_screen(
                records,
                as_of=as_of,
                policy=lane_policy,
                progress_label=progress_label,
                chunk_size=chunk_size,
            )

        with authoritative._FINALIZER_LOCK:
            core._base._merge_certified_catalog = merged_identity
            core.build_bounded_terminal_preselection = lane_screen
            try:
                return current(core, delegate, acquisition, **kwargs)
            finally:
                core._base._merge_certified_catalog = original_merge
                core.build_bounded_terminal_preselection = original_screen

    provider_free_finalize._lane_local_comprehensive_finalizer = True  # type: ignore[attr-defined]
    if getattr(current, "_comprehensive_discovery_failure_boundary", False):
        provider_free_finalize._comprehensive_discovery_failure_boundary = True  # type: ignore[attr-defined]
    authoritative._provider_free_finalize = provider_free_finalize


def install_lane_local_comprehensive_discovery_spool() -> None:
    """Install lane-local spool construction after the spawn-safe runtime boundary."""

    _install_lane_local_finalizer()


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
            _screening_lane_stage(
                args.request,
                values,
                asset_class_value=args.asset_class,
                index=args.index,
            )
    except BaseException as error:  # noqa: BLE001 - finite subprocess stays fail-closed.
        print(
            f"lane-local comprehensive discovery failed: {type(error).__name__}",
            file=sys.stderr,
            flush=True,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "LanePublicationIndex",
    "LaneShardCatalogs",
    "build_spool",
    "install_lane_local_comprehensive_discovery_spool",
    "load_finalizer_inputs",
]
