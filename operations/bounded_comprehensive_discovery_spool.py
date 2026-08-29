"""Bounded-memory staged builder for comprehensive-discovery spool inputs.

This module preserves the canonical discovery rules while changing only memory lifetime.
The global raw catalog, merged provider-preselection catalog, and per-lane deep records are
never retained in one interpreter. A coordinator runs finite child stages:

1. collect raw catalogs and freeze them as per-asset-class shards;
2. reconstruct/merge catalogs, build the exact global provider-preselection publication,
   freeze one merged catalog shard per scheduled lane, then exit;
3. materialize, fingerprint, checkpoint-rebind, and freeze exactly one deep lane per child;
4. publish the legacy-compatible compact manifest consumed by the existing scheduler.

All artifacts remain integrity checked, operational-only, fail-closed, paper-only, and
carry no decision, candidate, sizing, construction, execution, or real-money authority.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Mapping, Sequence

from cio import CandidateAssetClass
from operations import comprehensive_discovery_input_spool as _legacy


_STAGE_SCHEMA = "bounded-comprehensive-discovery-stage.v1"
_MODULE = "operations.bounded_comprehensive_discovery_spool"
_PUBLICATION_TERMINATION_GRACE_SECONDS = 1.0


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _stage_path(request_path: str | Path, name: str) -> Path:
    return Path(request_path).expanduser().parent / f"{name}.json"


def _write_stage_state(
    request_path: str | Path,
    name: str,
    body: Mapping[str, object],
) -> Path:
    material = {
        "schema_version": _STAGE_SCHEMA,
        "stage": name,
        **dict(body),
        **_legacy._authority_fields(),
    }
    path = _stage_path(request_path, name)
    _legacy._atomic_json(path, material)
    return path


def _load_stage_state(request_path: str | Path, name: str) -> Mapping[str, object]:
    path = _stage_path(request_path, name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            f"bounded discovery stage state is unreadable: {name}"
        ) from error
    body = payload.get("body") if isinstance(payload, Mapping) else None
    if not isinstance(body, Mapping) or payload.get("sha256") != _legacy._digest(body):
        raise _legacy.ComprehensiveDiscoverySpoolError(
            f"bounded discovery stage state integrity mismatch: {name}"
        )
    if body.get("schema_version") != _STAGE_SCHEMA or body.get("stage") != name:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            f"bounded discovery stage state schema mismatch: {name}"
        )
    if body.get("paper_only") is not True or body.get("real_money_authorized") is not False:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            f"bounded discovery stage authority boundary is invalid: {name}"
        )
    for authority in (
        "decision_authority",
        "candidate_authority",
        "sizing_authority",
        "construction_authority",
        "execution_authority",
    ):
        if body.get(authority) is not False:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"bounded discovery stage contains forbidden authority: {name}"
            )
    return body


def _validate_request(
    request_path: str | Path,
    values: Mapping[str, str],
) -> tuple[Mapping[str, object], object]:
    request, policy = _legacy.load_request(request_path)
    if request.get("release") != _legacy._release(values):
        raise _legacy.ComprehensiveDiscoverySpoolError(
            "bounded spool builder release does not match runtime"
        )
    return request, policy


def _catalog_stage(request_path: str | Path, values: Mapping[str, str]) -> None:
    stage = "bounded_catalog_assembly"
    path = Path(request_path).expanduser()
    try:
        request, policy = _validate_request(path, values)
        timestamp = _legacy._parse_timestamp(
            request.get("decision_epoch"),
            field_name="decision_epoch",
        )
        from operations import comprehensive_market_discovery as facade

        core = facade._core
        core.record_manual_cio_diagnostic_progress("bounded_spool_catalog_stage")
        raw = core._base.default_catalog_probe(timestamp, policy=policy)
        if not isinstance(raw, Mapping):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "bounded catalog dependency is not a mapping"
            )

        raw_catalogs = dict(raw)
        keys = tuple(raw_catalogs.keys())
        shards: list[dict[str, object]] = []
        directory = path.parent
        catalog_records = 0
        for index, asset_class in enumerate(keys):
            if not isinstance(asset_class, CandidateAssetClass):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    "bounded raw catalog contains a non-canonical asset-class key"
                )
            records = raw_catalogs.pop(asset_class)
            if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"{asset_class.value} raw catalog must be a sequence"
                )
            frozen = tuple(records)
            catalog_records += len(frozen)
            descriptor = _legacy._write_pickle_blob(
                directory,
                f"raw-catalog-{index:03d}-{_legacy._safe_release(asset_class.value)}.pkl",
                frozen,
            )
            shards.append(
                {
                    "asset_class": asset_class.value,
                    "blob": _legacy._descriptor_dict(descriptor),
                    "record_count": len(frozen),
                }
            )
            del records
            del frozen
        raw_catalogs.clear()

        peak = _peak_rss_bytes()
        _write_stage_state(
            path,
            "catalog-stage",
            {
                "request_id": request.get("request_id"),
                "raw_catalog_shards": shards,
                "catalog_record_count": catalog_records,
                "peak_rss_bytes": peak,
            },
        )
        core.record_manual_cio_diagnostic_progress(
            "bounded_spool_catalog_stage_complete",
            metrics={
                "catalog_records": catalog_records,
                "catalog_shards": len(shards),
                "peak_rss_bytes": peak,
            },
        )
    except BaseException as error:  # noqa: BLE001 - persist exact bounded failure.
        try:
            _legacy._write_failure(path, stage=stage, error=error, values=values)
        except BaseException:
            pass
        raise


def _publication_stage(request_path: str | Path, values: Mapping[str, str]) -> None:
    stage = "bounded_catalog_merge"
    path = Path(request_path).expanduser()
    try:
        request, policy = _validate_request(path, values)
        timestamp = _legacy._parse_timestamp(
            request.get("decision_epoch"),
            field_name="decision_epoch",
        )
        catalog_state = _load_stage_state(path, "catalog-stage")
        raw_shards = catalog_state.get("raw_catalog_shards")
        if not isinstance(raw_shards, list) or not raw_shards:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "bounded catalog stage produced no raw catalog shards"
            )

        from operations import comprehensive_market_discovery as facade

        core = facade._core
        directory = path.parent
        raw_catalogs: dict[CandidateAssetClass, Sequence[object]] = {}
        for raw in raw_shards:
            if not isinstance(raw, Mapping):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    "bounded raw catalog shard descriptor is malformed"
                )
            asset_class = CandidateAssetClass(str(raw.get("asset_class") or ""))
            records = _legacy._load_pickle_blob(
                directory,
                _legacy._descriptor(raw.get("blob")),
            )
            if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"{asset_class.value} raw catalog shard is malformed"
                )
            raw_catalogs[asset_class] = records

        core.record_manual_cio_diagnostic_progress("bounded_spool_catalog_merge")
        catalogs = core._base._merge_certified_catalog(raw_catalogs, as_of=timestamp)
        if not isinstance(catalogs, Mapping):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "bounded merged catalog dependency is not a mapping"
            )
        raw_catalogs.clear()
        del raw_catalogs

        stage = "bounded_provider_preselection"
        core.record_manual_cio_diagnostic_progress("bounded_spool_provider_preselection")
        try:
            publication = core.ensure_provider_preselection_publication(
                catalogs,
                as_of=timestamp,
                policy=policy,
                market_probe=core.default_provider_preselection_market_probe,
            )
        except core.ProviderPreselectionPublicationError as error:
            raise _legacy.ComprehensiveDiscoverySpoolError(str(error)) from error
        publication_descriptor = _legacy._write_pickle_blob(
            directory,
            "finalizer-publication.pkl",
            publication,
        )
        del publication

        stage = "bounded_lane_catalog_spooling"
        mutable_catalogs = dict(catalogs)
        scheduled = tuple(
            asset_class
            for asset_class in core._base._dynamic_discovery_lanes(mutable_catalogs)
            if core._base._lane_is_scheduled(asset_class, timestamp)
        )
        lane_shards: list[dict[str, object]] = []
        total_records = 0
        for index, asset_class in enumerate(scheduled):
            records = mutable_catalogs.pop(asset_class, ())
            if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"{asset_class.value} merged catalog must be a sequence"
                )
            frozen = tuple(records)
            total_records += len(frozen)
            descriptor = _legacy._write_pickle_blob(
                directory,
                f"merged-catalog-{index:03d}-{_legacy._safe_release(asset_class.value)}.pkl",
                frozen,
            )
            lane_shards.append(
                {
                    "index": index,
                    "asset_class": asset_class.value,
                    "blob": _legacy._descriptor_dict(descriptor),
                    "record_count": len(frozen),
                }
            )
            del records
            del frozen
        mutable_catalogs.clear()
        del mutable_catalogs
        del catalogs

        if not lane_shards:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "bounded builder found no scheduled comprehensive-discovery lanes"
            )

        peak = _peak_rss_bytes()
        _write_stage_state(
            path,
            "publication-stage",
            {
                "request_id": request.get("request_id"),
                "publication_blob": _legacy._descriptor_dict(publication_descriptor),
                "lane_catalog_shards": lane_shards,
                "merged_catalog_record_count": total_records,
                "peak_rss_bytes": peak,
            },
        )
        core.record_manual_cio_diagnostic_progress(
            "bounded_spool_provider_preselection_complete",
            metrics={
                "scheduled_lanes": len(lane_shards),
                "catalog_records": total_records,
                "peak_rss_bytes": peak,
            },
        )
    except BaseException as error:  # noqa: BLE001 - persist exact bounded failure.
        try:
            _legacy._write_failure(path, stage=stage, error=error, values=values)
        except BaseException:
            pass
        raise


def _lane_stage(
    request_path: str | Path,
    values: Mapping[str, str],
    *,
    asset_class_value: str,
    index: int,
) -> None:
    stage = f"bounded_lane_descriptor:{asset_class_value}"
    path = Path(request_path).expanduser()
    try:
        request, policy = _validate_request(path, values)
        timestamp = _legacy._parse_timestamp(
            request.get("decision_epoch"),
            field_name="decision_epoch",
        )
        held = {str(item).strip().upper() for item in request.get("held_symbols", ()) if str(item).strip()}
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

        publication_state = _load_stage_state(path, "publication-stage")
        raw_lane_shards = publication_state.get("lane_catalog_shards")
        if not isinstance(raw_lane_shards, list):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "bounded publication stage lane descriptors are malformed"
            )
        selected = next(
            (
                item
                for item in raw_lane_shards
                if isinstance(item, Mapping)
                and int(item.get("index", -1)) == index
                and str(item.get("asset_class") or "") == asset_class_value
            ),
            None,
        )
        if selected is None:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"bounded publication stage has no lane shard for {asset_class_value}"
            )

        from operations import authoritative_comprehensive_discovery as authoritative
        from operations import comprehensive_market_discovery as facade
        from operations import persistent_certification_scheduler as scheduler

        core = facade._core
        asset_class = CandidateAssetClass(asset_class_value)
        records = _legacy._load_pickle_blob(
            path.parent,
            _legacy._descriptor(selected.get("blob")),
        )
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"{asset_class.value} bounded merged catalog shard is malformed"
            )

        catalog_records = core._base._legacy._deduplicate(tuple(records))
        del records
        eligible: list[object] = []
        for item in catalog_records:
            if item.symbol in excluded:
                continue
            if (
                item.expiration_at is not None
                and item.expiration_at <= timestamp + timedelta(days=7)
            ):
                continue
            eligible.append(item)
        eligible_records = tuple(eligible)
        del eligible
        continuity = tuple(item for item in eligible_records if item.symbol in state_symbols)
        ordinary = tuple(item for item in eligible_records if item.symbol not in state_symbols)
        del eligible_records

        core.record_manual_cio_diagnostic_progress(
            f"bounded_spool_lane:{asset_class.value}",
            metrics={
                "catalog_records": len(catalog_records),
                "continuity_records": len(continuity),
            },
        )
        try:
            bounded = core.build_bounded_terminal_preselection(
                ordinary,
                as_of=timestamp,
                policy=policy,
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
        policy_version = str(getattr(policy, "version", ""))
        rebound = authoritative._rebind_compatible_checkpoint(
            values,
            release_sha=scheduler._release(values),
            node=node,
            records=deep_records,
            epoch=timestamp,
            policy_version=policy_version,
        )

        stage = f"bounded_lane_spooling:{asset_class.value}"
        descriptor = _legacy._write_pickle_blob(
            path.parent,
            f"lane-{index:03d}-{_legacy._safe_release(node.node_id)}.pkl",
            deep_records,
        )
        node_body = _legacy._node_body(node, descriptor)
        peak = _peak_rss_bytes()
        _write_stage_state(
            path,
            f"lane-stage-{index:03d}",
            {
                "request_id": request.get("request_id"),
                "node": node_body,
                "compatibility_rebound": bool(rebound),
                "peak_rss_bytes": peak,
            },
        )
        core.record_manual_cio_diagnostic_progress(
            f"bounded_spool_lane_complete:{asset_class.value}",
            metrics={
                "decision_eligible_records": len(deep_records),
                "compatibility_rebound": int(bool(rebound)),
                "peak_rss_bytes": peak,
            },
        )
    except BaseException as error:  # noqa: BLE001 - persist exact bounded failure.
        try:
            _legacy._write_failure(path, stage=stage, error=error, values=values)
        except BaseException:
            pass
        raise


def _provider_publication_timeout_seconds(
    request_path: Path,
    values: Mapping[str, str],
) -> float:
    """Reuse the existing fanout epoch budget for the canonical publication fallback."""

    request, _policy = _validate_request(request_path, values)
    decision_epoch = _legacy._parse_timestamp(
        request.get("decision_epoch"),
        field_name="decision_epoch",
    )
    from operations.epoch_scoped_provider_acquisition import _fanout_budget_seconds

    return float(_fanout_budget_seconds(decision_epoch, values))


def _terminate_and_reap_publication(process: subprocess.Popen[bytes]) -> int:
    """Stop only the still-live canonical publication child after its existing epoch budget."""

    return_code = process.poll()
    if return_code is not None:
        return int(return_code)
    process.terminate()
    try:
        return int(process.wait(timeout=_PUBLICATION_TERMINATION_GRACE_SECONDS))
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            return int(process.wait(timeout=_PUBLICATION_TERMINATION_GRACE_SECONDS))
        except subprocess.TimeoutExpired as error:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "bounded provider publication child remained live after bounded kill"
            ) from error


def _run_stage(
    action: str,
    request_path: Path,
    values: Mapping[str, str],
    *,
    asset_class: str | None = None,
    index: int | None = None,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-m",
        _MODULE,
        action,
        "--request",
        str(request_path),
    ]
    if asset_class is not None:
        command.extend(("--asset-class", asset_class))
    if index is not None:
        command.extend(("--index", str(index)))

    publication_timeout: float | None = None
    if action == "publication":
        publication_timeout = _provider_publication_timeout_seconds(request_path, values)
        if publication_timeout <= 0.0:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "bounded provider publication cannot start because the existing evidence "
                "epoch has no provider-acquisition time beyond the downstream reserve"
            )

    process = subprocess.Popen(
        tuple(command),
        cwd=str(repository_root),
        env=dict(values),
        start_new_session=False,
    )
    try:
        return_code = int(
            process.wait(timeout=publication_timeout)
            if publication_timeout is not None
            else process.wait()
        )
    except subprocess.TimeoutExpired as error:
        return_code = _terminate_and_reap_publication(process)
        raise _legacy.ComprehensiveDiscoverySpoolError(
            "bounded provider publication exceeded the existing epoch-scoped provider "
            f"acquisition window; timeout_seconds={publication_timeout:.3f}; "
            f"child_return_code={return_code}; downstream reserve preserved"
        ) from error

    if return_code == 0:
        return
    failure = _legacy.load_failure(request_path)
    if failure is None:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            f"bounded comprehensive discovery stage {action} exited without durable failure attribution; "
            f"return_code={return_code}"
        )
    raise _legacy.ComprehensiveDiscoverySpoolError(
        "bounded comprehensive discovery stage failed; "
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
    stage = "bounded_coordinator"
    try:
        request, policy = _validate_request(path, resolved_values)
        if _legacy.manifest_available(path):
            return _legacy._manifest_path(path)

        _run_stage("catalog", path, resolved_values)
        _run_stage("publication", path, resolved_values)
        catalog_state = _load_stage_state(path, "catalog-stage")
        publication_state = _load_stage_state(path, "publication-stage")

        raw_lane_shards = publication_state.get("lane_catalog_shards")
        if not isinstance(raw_lane_shards, list) or not raw_lane_shards:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "bounded publication stage produced no lane catalog shards"
            )

        node_bodies: list[Mapping[str, object]] = []
        rebound_count = 0
        lane_peak_rss: dict[str, int] = {}
        for item in raw_lane_shards:
            if not isinstance(item, Mapping):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    "bounded lane catalog descriptor is malformed"
                )
            index = int(item.get("index", -1))
            asset_class = str(item.get("asset_class") or "")
            if index < 0 or not asset_class:
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    "bounded lane catalog identity is incomplete"
                )
            _run_stage(
                "lane",
                path,
                resolved_values,
                asset_class=asset_class,
                index=index,
            )
            lane_state = _load_stage_state(path, f"lane-stage-{index:03d}")
            node = lane_state.get("node")
            if not isinstance(node, Mapping):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"bounded lane stage produced no node for {asset_class}"
                )
            node_bodies.append(dict(node))
            rebound_count += int(bool(lane_state.get("compatibility_rebound")))
            lane_peak_rss[asset_class] = int(lane_state.get("peak_rss_bytes", 0))

        raw_catalog_shards = catalog_state.get("raw_catalog_shards")
        if not isinstance(raw_catalog_shards, list) or not raw_catalog_shards:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "bounded catalog stage produced no finalizer catalog shards"
            )
        publication_blob = publication_state.get("publication_blob")
        if not isinstance(publication_blob, Mapping):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "bounded publication stage produced no finalizer publication"
            )

        policy_version = str(getattr(policy, "version", ""))
        request_policy = _legacy._descriptor(request.get("policy_blob"))
        material: dict[str, object] = {
            "schema_version": _legacy._SCHEMA,
            "request_id": str(request.get("request_id") or ""),
            "release": _legacy._release(resolved_values),
            "decision_epoch": str(request.get("decision_epoch") or ""),
            "policy_version": policy_version,
            "policy_blob": _legacy._descriptor_dict(request_policy),
            "raw_catalog_shards": raw_catalog_shards,
            "publication_blob": dict(publication_blob),
            "compatibility_rebound_count": rebound_count,
            "bounded_memory_builder": True,
            "builder_peak_rss_bytes": {
                "catalog": int(catalog_state.get("peak_rss_bytes", 0)),
                "publication": int(publication_state.get("peak_rss_bytes", 0)),
                "lanes": lane_peak_rss,
            },
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
            _legacy._write_failure(path, stage=stage, error=error, values=resolved_values)
        except BaseException:
            pass
        raise


def load_finalizer_inputs(
    manifest_path: str | Path,
) -> tuple[Mapping[CandidateAssetClass, Sequence[object]], object]:
    body = _legacy.load_manifest(manifest_path)
    raw_shards = body.get("raw_catalog_shards")
    if not isinstance(raw_shards, list):
        return _legacy.load_finalizer_inputs(manifest_path)
    if not raw_shards:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            "bounded spool manifest has no raw catalog shards"
        )

    directory = Path(manifest_path).expanduser().parent
    raw_catalogs: dict[CandidateAssetClass, Sequence[object]] = {}
    for item in raw_shards:
        if not isinstance(item, Mapping):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "bounded finalizer catalog shard descriptor is malformed"
            )
        asset_class = CandidateAssetClass(str(item.get("asset_class") or ""))
        records = _legacy._load_pickle_blob(
            directory,
            _legacy._descriptor(item.get("blob")),
        )
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"{asset_class.value} bounded finalizer catalog shard is malformed"
            )
        raw_catalogs[asset_class] = records

    publication = _legacy._load_pickle_blob(
        directory,
        _legacy._descriptor(body.get("publication_blob")),
    )
    return raw_catalogs, publication


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "catalog", "publication", "lane"))
    parser.add_argument("--request", required=True)
    parser.add_argument("--asset-class")
    parser.add_argument("--index", type=int)
    args = parser.parse_args(argv)
    values = dict(os.environ)
    try:
        if args.action == "build":
            output = build_spool(args.request, values=values)
            event = {
                "event": "bounded_comprehensive_discovery_spool_ready",
                "manifest_path": str(output),
            }
        elif args.action == "catalog":
            _catalog_stage(args.request, values)
            event = {"event": "bounded_comprehensive_discovery_catalog_ready"}
        elif args.action == "publication":
            _publication_stage(args.request, values)
            event = {"event": "bounded_comprehensive_discovery_publication_ready"}
        else:
            if args.asset_class is None or args.index is None:
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    "bounded lane stage requires --asset-class and --index"
                )
            _lane_stage(
                args.request,
                values,
                asset_class_value=args.asset_class,
                index=args.index,
            )
            event = {
                "event": "bounded_comprehensive_discovery_lane_ready",
                "asset_class": args.asset_class,
                "index": args.index,
            }
    except BaseException as error:  # noqa: BLE001 - finite subprocess boundary is fail-closed.
        print(
            json.dumps(
                {
                    "event": "bounded_comprehensive_discovery_spool_failed",
                    "action": args.action,
                    "error_type": type(error).__name__,
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

    event.update(
        {
            "credential_safe": True,
            "paper_only": True,
            "real_money_authorized": False,
        }
    )
    print(json.dumps(event, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "build_spool",
    "load_finalizer_inputs",
]