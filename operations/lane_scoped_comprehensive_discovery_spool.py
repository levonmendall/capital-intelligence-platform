"""Lane-scoped comprehensive-discovery spool with bounded finalizer hydration.

The canonical discovery algorithm still decides which markets are scheduled, how every
catalog record is screened, and which evidence reaches the CIO.  This module changes only
operational memory lifetime: certified catalog membership is indexed once, then each market
lane independently reconstructs its raw reference records, merges certified instruments,
builds provider-factor evidence, screens the complete lane, and exits.  The finalizer sees
an integrity-checked lazy Mapping whose values are loaded one lane at a time rather than a
single global catalog object graph.

No market, provider, candidate, threshold, evidence, construction, execution, or authority
rule is weakened.  The spool remains paper-only and fail-closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterator, Mapping as MappingABC
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping, Sequence

from cio import CandidateAssetClass
from operations import bounded_comprehensive_discovery_spool as _bounded
from operations import comprehensive_discovery_input_spool as _legacy


_MODULE = "operations.lane_scoped_comprehensive_discovery_spool"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _catalog_index_stage(request_path: str | Path, values: Mapping[str, str]) -> None:
    """Freeze only the provider-neutral certified catalog, partitioned by lane."""

    stage = "lane_scoped_certified_catalog_index"
    path = Path(request_path).expanduser()
    try:
        request, _policy = _bounded._validate_request(path, values)
        timestamp = _legacy._parse_timestamp(
            request.get("decision_epoch"), field_name="decision_epoch"
        )
        from operations import _comprehensive_market_discovery_v4_serial as serial
        from operations.certified_investable_catalog import (
            CertifiedInvestableCatalogError,
            load_certified_investable_catalog,
        )

        try:
            certified = load_certified_investable_catalog(as_of=timestamp)
        except CertifiedInvestableCatalogError as error:
            raise _legacy.ComprehensiveDiscoverySpoolError(str(error)) from error

        by_lane: dict[CandidateAssetClass, list[Mapping[str, object]]] = {}
        for payload in certified:
            if not isinstance(payload, Mapping):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    "certified catalog record must be an object"
                )
            try:
                lane = CandidateAssetClass(str(payload.get("asset_class") or ""))
            except ValueError as error:
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    "certified catalog contains an unsupported asset class"
                ) from error
            by_lane.setdefault(lane, []).append(dict(payload))

        dynamic = set(serial._DEFAULT_REQUIRED_DISCOVERY_LANES)
        dynamic.update(
            lane
            for lane, records in by_lane.items()
            if lane is not CandidateAssetClass.OTHER and bool(records)
        )
        catalog_keys = dynamic | set(by_lane)
        ordered = tuple(lane for lane in CandidateAssetClass if lane in catalog_keys)
        directory = path.parent
        lanes: list[dict[str, object]] = []
        for index, lane in enumerate(ordered):
            payloads = tuple(by_lane.pop(lane, ()))
            descriptor = _legacy._write_pickle_blob(
                directory,
                f"certified-{index:03d}-{_legacy._safe_release(lane.value)}.pkl",
                payloads,
            )
            discoverable = lane in dynamic
            lanes.append(
                {
                    "index": index,
                    "asset_class": lane.value,
                    "certified_blob": _legacy._descriptor_dict(descriptor),
                    "certified_count": len(payloads),
                    "discoverable": discoverable,
                    "scheduled": bool(
                        discoverable and serial._lane_is_scheduled(lane, timestamp)
                    ),
                }
            )
            del payloads
        by_lane.clear()
        del certified

        peak = _bounded._peak_rss_bytes()
        _bounded._write_stage_state(
            path,
            "lane-index",
            {
                "request_id": request.get("request_id"),
                "lanes": lanes,
                "peak_rss_bytes": peak,
            },
        )
    except BaseException as error:  # noqa: BLE001 - finite stage must fail closed.
        try:
            _legacy._write_failure(path, stage=stage, error=error, values=values)
        except BaseException:
            pass
        raise


def _reference_lane_records(
    *,
    values: Mapping[str, str],
    timestamp: datetime,
    policy: object,
    lane: CandidateAssetClass,
) -> tuple[object, ...]:
    """Load exactly the raw catalog membership canonical discovery would expose for lane."""

    from operations import _comprehensive_market_discovery_v4 as discovery
    from operations import generalized_reference_readiness as generalized
    from operations import reference_readiness as reference

    config = discovery._base.load_comprehensive_market_discovery_config()
    discovery._base._reject_evidence_only_eodhd_directories(config)
    active_defaults = discovery._base.scheduled_discovery_lanes(timestamp)
    if lane not in active_defaults:
        return ()

    if lane in generalized._EODHD_REFERENCE_LANES or lane is CandidateAssetClass.FUTURE:
        component = generalized.load_asset_reference_component(
            values,
            asset_class=lane,
            as_of=timestamp,
            config_fingerprint=generalized._lane_config_fingerprint(config, lane),
            coverage=generalized._lane_coverage(discovery, config, lane),
        )
        payloads = () if component is None else tuple(generalized._component_records(component))
        if not payloads:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"qualified lane reference is unavailable for {lane.value}"
            )
        return tuple(
            reference._record_from_payload(
                item,
                discovery._base._legacy.DiscoveryCatalogRecord,
            )
            for item in payloads
        )

    if lane is CandidateAssetClass.OPTION:
        return tuple(
            discovery._base._legacy._option_catalog(
                as_of=timestamp,
                config=config,
                policy=policy,
            )
        )

    # Direct crypto enters through the governed multi-venue certified catalog.  Dynamic
    # certified lanes likewise have no implicit raw-provider catalog in the canonical path.
    return ()


def _lane_stage(
    request_path: str | Path,
    values: Mapping[str, str],
    *,
    asset_class_value: str,
    index: int,
) -> None:
    stage = f"lane_scoped_catalog:{asset_class_value}"
    path = Path(request_path).expanduser()
    try:
        request, policy = _bounded._validate_request(path, values)
        timestamp = _legacy._parse_timestamp(
            request.get("decision_epoch"), field_name="decision_epoch"
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

        index_state = _bounded._load_stage_state(path, "lane-index")
        lane_rows = index_state.get("lanes")
        if not isinstance(lane_rows, list):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "lane-scoped catalog index is malformed"
            )
        selected = next(
            (
                item
                for item in lane_rows
                if isinstance(item, Mapping)
                and int(item.get("index", -1)) == index
                and str(item.get("asset_class") or "") == asset_class_value
            ),
            None,
        )
        if selected is None:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"lane-scoped index has no lane {asset_class_value}"
            )

        from operations import _comprehensive_market_discovery_v4_serial as serial
        from operations import authoritative_comprehensive_discovery as authoritative
        from operations import comprehensive_market_discovery as facade
        from operations import persistent_certification_scheduler as scheduler

        core = facade._core
        lane = CandidateAssetClass(asset_class_value)
        certified_payloads = _legacy._load_pickle_blob(
            path.parent, _legacy._descriptor(selected.get("certified_blob"))
        )
        if not isinstance(certified_payloads, Sequence) or isinstance(
            certified_payloads, (str, bytes, bytearray)
        ):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"{lane.value} certified lane shard is malformed"
            )
        certified_records = tuple(
            serial._certified_catalog_record(item)
            for item in certified_payloads
            if isinstance(item, Mapping)
        )
        if len(certified_records) != len(certified_payloads):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"{lane.value} certified lane shard contains a non-object record"
            )
        del certified_payloads

        raw_records = _reference_lane_records(
            values=values,
            timestamp=timestamp,
            policy=policy,
            lane=lane,
        )
        merged = serial._legacy._deduplicate((*raw_records, *certified_records))
        del raw_records
        del certified_records

        catalog_descriptor = _legacy._write_pickle_blob(
            path.parent,
            f"finalizer-catalog-{index:03d}-{_legacy._safe_release(lane.value)}.pkl",
            merged,
        )

        catalog_records = serial._legacy._deduplicate(tuple(merged))
        eligible: list[object] = []
        for item in catalog_records:
            if item.symbol in excluded:
                continue
            if item.expiration_at is not None and item.expiration_at <= timestamp + timedelta(days=7):
                continue
            eligible.append(item)
        eligible_records = tuple(eligible)
        del eligible
        continuity = tuple(item for item in eligible_records if item.symbol in state_symbols)
        ordinary = tuple(item for item in eligible_records if item.symbol not in state_symbols)
        del eligible_records

        publication_path = path.parent / (
            f"provider-preselection-{index:03d}-{_legacy._safe_release(lane.value)}.json"
        )
        publication = None
        publication_error: BaseException | None = None
        if catalog_records:
            lane_policy = replace(
                policy, provider_preselection_path=str(publication_path)
            )
            try:
                publication = core.ensure_provider_preselection_publication(
                    {lane: catalog_records},
                    as_of=timestamp,
                    policy=lane_policy,
                    market_probe=core.default_provider_preselection_market_probe,
                )
            except core.ProviderPreselectionPublicationError as error:
                publication_error = error
                if bool(selected.get("scheduled")) and ordinary:
                    raise _legacy.ComprehensiveDiscoverySpoolError(str(error)) from error

        node_body: Mapping[str, object] | None = None
        rebound = False
        if bool(selected.get("scheduled")):
            stage = f"lane_scoped_terminal_screening:{lane.value}"
            if ordinary:
                if publication is None:
                    detail = "provider publication unavailable"
                    if publication_error is not None:
                        detail = str(publication_error)
                    raise _legacy.ComprehensiveDiscoverySpoolError(
                        f"{lane.value} {detail}"
                    )
                lane_policy = replace(
                    policy, provider_preselection_path=str(publication.path)
                )
                try:
                    bounded = core.build_bounded_terminal_preselection(
                        ordinary,
                        as_of=timestamp,
                        policy=lane_policy,
                        progress_label=lane.value,
                        chunk_size=core._PRODUCTION_TERMINAL_SCREENING_CHUNK_SIZE,
                    )
                except core.BoundedTerminalScreeningError as error:
                    raise _legacy.ComprehensiveDiscoverySpoolError(str(error)) from error
                nominated = bounded.nominated
            else:
                nominated = ()

            deep_records = tuple(dict.fromkeys((*continuity, *nominated)))
            node_id = f"deep-market-evidence:{lane.value}"
            fingerprint = scheduler._digest(
                {
                    "record_fingerprint": scheduler._record_fingerprint(deep_records),
                    "policy_version": str(getattr(policy, "version", "")),
                    "asset_class": lane.value,
                    "decision_epoch": timestamp.isoformat(),
                }
            )
            node = scheduler.CertificationNode(
                node_id=node_id,
                asset_class=lane.value,
                provider_groups=scheduler._provider_groups(lane.value),
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
            deep_descriptor = _legacy._write_pickle_blob(
                path.parent,
                f"lane-{index:03d}-{_legacy._safe_release(node.node_id)}.pkl",
                deep_records,
            )
            node_body = _legacy._node_body(node, deep_descriptor)

        publication_body: Mapping[str, object] | None = None
        if publication is not None:
            publication_file = Path(publication.path).expanduser()
            publication_body = {
                "asset_class": lane.value,
                "path": str(publication_file),
                "sha256": _file_sha256(publication_file),
                "catalog_count": int(publication.catalog_count),
                "signal_count": int(publication.signal_count),
            }

        peak = _bounded._peak_rss_bytes()
        _bounded._write_stage_state(
            path,
            f"lane-scoped-stage-{index:03d}",
            {
                "request_id": request.get("request_id"),
                "asset_class": lane.value,
                "scheduled": bool(selected.get("scheduled")),
                "catalog_blob": _legacy._descriptor_dict(catalog_descriptor),
                "catalog_count": len(catalog_records),
                "publication": publication_body,
                "publication_failed_nonterminal": bool(publication_error is not None),
                "node": node_body,
                "compatibility_rebound": bool(rebound),
                "peak_rss_bytes": peak,
            },
        )
    except BaseException as error:  # noqa: BLE001 - finite stage must fail closed.
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
    asset_class: str | None = None,
    index: int | None = None,
) -> None:
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
    process = subprocess.Popen(
        tuple(command),
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
            f"lane-scoped comprehensive stage {action} exited without durable failure attribution; "
            f"return_code={return_code}"
        )
    raise _legacy.ComprehensiveDiscoverySpoolError(
        "lane-scoped comprehensive discovery stage failed; "
        f"stage={failure.get('failure_stage')}; "
        f"failure_type={failure.get('error_type')}; "
        f"detail={failure.get('error_detail')}"
    )


def build_spool(
    request_path: str | Path,
    *,
    values: Mapping[str, str] | None = None,
) -> Path:
    """Build a legacy-compatible scheduler manifest without global catalog hydration."""

    resolved_values = dict(os.environ if values is None else values)
    path = Path(request_path).expanduser()
    stage = "lane_scoped_coordinator"
    try:
        request, policy = _bounded._validate_request(path, resolved_values)
        if _legacy.manifest_available(path):
            return _legacy._manifest_path(path)

        _run_stage("index", path, resolved_values)
        index_state = _bounded._load_stage_state(path, "lane-index")
        lanes = index_state.get("lanes")
        if not isinstance(lanes, list) or not lanes:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "lane-scoped catalog index produced no market lanes"
            )

        nodes: list[Mapping[str, object]] = []
        finalizer_shards: list[Mapping[str, object]] = []
        publications: list[Mapping[str, object]] = []
        rebound_count = 0
        lane_peaks: dict[str, int] = {}
        total_catalog_records = 0
        total_signal_records = 0
        for item in lanes:
            if not isinstance(item, Mapping):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    "lane-scoped catalog descriptor is malformed"
                )
            index = int(item.get("index", -1))
            lane = str(item.get("asset_class") or "")
            if index < 0 or not lane:
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    "lane-scoped catalog identity is incomplete"
                )
            _run_stage(
                "lane",
                path,
                resolved_values,
                asset_class=lane,
                index=index,
            )
            state = _bounded._load_stage_state(
                path, f"lane-scoped-stage-{index:03d}"
            )
            catalog_blob = state.get("catalog_blob")
            if not isinstance(catalog_blob, Mapping):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"lane-scoped stage has no finalizer catalog for {lane}"
                )
            count = int(state.get("catalog_count", -1))
            if count < 0:
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"lane-scoped stage has invalid catalog count for {lane}"
                )
            total_catalog_records += count
            finalizer_shards.append(
                {
                    "asset_class": lane,
                    "blob": dict(catalog_blob),
                    "record_count": count,
                }
            )
            publication = state.get("publication")
            if isinstance(publication, Mapping):
                publications.append(dict(publication))
                total_signal_records += int(publication.get("signal_count", 0))
            node = state.get("node")
            if isinstance(node, Mapping):
                nodes.append(dict(node))
            rebound_count += int(bool(state.get("compatibility_rebound")))
            lane_peaks[lane] = int(state.get("peak_rss_bytes", 0))

        # The canonical global publication fails closed when no substantive provider
        # factor signal exists anywhere.  Lane-local publication generation preserves
        # that aggregate requirement without retaining the aggregate publication.
        if not publications or total_signal_records < 1:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "no substantive provider factor signal could be produced for the certified market catalog"
            )
        if not nodes:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "lane-scoped builder found no scheduled comprehensive-discovery lanes"
            )

        request_policy = _legacy._descriptor(request.get("policy_blob"))
        material: dict[str, object] = {
            "schema_version": _legacy._SCHEMA,
            "request_id": str(request.get("request_id") or ""),
            "release": _legacy._release(resolved_values),
            "decision_epoch": str(request.get("decision_epoch") or ""),
            "policy_version": str(getattr(policy, "version", "")),
            "policy_blob": _legacy._descriptor_dict(request_policy),
            "finalizer_catalog_shards": finalizer_shards,
            "provider_publications": publications,
            "finalizer_catalog_count": total_catalog_records,
            "provider_signal_count": total_signal_records,
            "compatibility_rebound_count": rebound_count,
            "bounded_memory_builder": True,
            "lane_scoped_memory_builder": True,
            "builder_peak_rss_bytes": {
                "index": int(index_state.get("peak_rss_bytes", 0)),
                "lanes": lane_peaks,
            },
            "nodes": nodes,
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


class LaneScopedCatalogMapping(MappingABC[CandidateAssetClass, Sequence[object]]):
    """Integrity-checked mapping that materializes at most one catalog lane per access."""

    def __init__(
        self,
        directory: Path,
        descriptors: Mapping[CandidateAssetClass, tuple[Mapping[str, object], int]],
    ) -> None:
        self._directory = Path(directory)
        self._descriptors = dict(descriptors)

    def __len__(self) -> int:
        return len(self._descriptors)

    def __iter__(self) -> Iterator[CandidateAssetClass]:
        return iter(self._descriptors)

    def __getitem__(self, key: CandidateAssetClass) -> Sequence[object]:
        lane = key if isinstance(key, CandidateAssetClass) else CandidateAssetClass(str(key))
        try:
            descriptor, expected_count = self._descriptors[lane]
        except KeyError:
            raise KeyError(key) from None
        records = _legacy._load_pickle_blob(
            self._directory, _legacy._descriptor(descriptor)
        )
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"{lane.value} lane-scoped finalizer catalog is malformed"
            )
        if len(records) != expected_count:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"{lane.value} lane-scoped finalizer catalog count changed"
            )
        return records


@dataclass(frozen=True, slots=True)
class LaneScopedPublicationIndex:
    """Small finalizer handle for integrity-bound per-lane provider publications."""

    directory: Path
    catalog_count: int
    signal_count: int
    publications: tuple[tuple[str, str, str], ...]

    def _entries(self) -> dict[str, tuple[str, str]]:
        return {lane: (path, digest) for lane, path, digest in self.publications}

    def path_for(self, asset_class: object, *, require_lane: bool) -> Path:
        lane = str(getattr(asset_class, "value", asset_class))
        entries = self._entries()
        selected = entries.get(lane)
        if selected is None:
            if require_lane:
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"lane-scoped provider publication is unavailable for {lane}"
                )
            if not self.publications:
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    "lane-scoped provider publication index is empty"
                )
            _fallback_lane, path, digest = self.publications[0]
            selected = (path, digest)
        raw_path, expected_digest = selected
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = self.directory / path
        if not path.is_file() or _file_sha256(path) != expected_digest:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"lane-scoped provider publication integrity changed for {lane}"
            )
        return path

    @property
    def path(self) -> Path:
        return self.path_for("__fallback__", require_lane=False)


def load_finalizer_inputs(
    manifest_path: str | Path,
) -> tuple[Mapping[CandidateAssetClass, Sequence[object]], object]:
    """Return lazy lane catalogs plus a compact publication index."""

    body = _legacy.load_manifest(manifest_path)
    if body.get("lane_scoped_memory_builder") is not True:
        return _bounded.load_finalizer_inputs(manifest_path)
    shards = body.get("finalizer_catalog_shards")
    publications = body.get("provider_publications")
    if not isinstance(shards, list) or not shards:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            "lane-scoped spool manifest has no finalizer catalog shards"
        )
    if not isinstance(publications, list) or not publications:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            "lane-scoped spool manifest has no provider publications"
        )

    descriptors: dict[CandidateAssetClass, tuple[Mapping[str, object], int]] = {}
    for item in shards:
        if not isinstance(item, Mapping):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "lane-scoped finalizer descriptor is malformed"
            )
        lane = CandidateAssetClass(str(item.get("asset_class") or ""))
        blob = item.get("blob")
        if not isinstance(blob, Mapping):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"lane-scoped finalizer blob is missing for {lane.value}"
            )
        count = int(item.get("record_count", -1))
        if count < 0 or lane in descriptors:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"lane-scoped finalizer descriptor is invalid for {lane.value}"
            )
        descriptors[lane] = (dict(blob), count)

    publication_entries: list[tuple[str, str, str]] = []
    for item in publications:
        if not isinstance(item, Mapping):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                "lane-scoped provider publication descriptor is malformed"
            )
        lane = CandidateAssetClass(str(item.get("asset_class") or ""))
        raw_path = str(item.get("path") or "").strip()
        digest = str(item.get("sha256") or "").strip()
        if not raw_path or not digest:
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"lane-scoped provider publication descriptor is incomplete for {lane.value}"
            )
        publication_entries.append((lane.value, raw_path, digest))

    directory = Path(manifest_path).expanduser().parent
    catalogs = LaneScopedCatalogMapping(directory, descriptors)
    publication = LaneScopedPublicationIndex(
        directory=directory,
        catalog_count=int(body.get("finalizer_catalog_count", -1)),
        signal_count=int(body.get("provider_signal_count", -1)),
        publications=tuple(publication_entries),
    )
    if publication.catalog_count < 0 or publication.signal_count < 1:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            "lane-scoped finalizer publication totals are invalid"
        )
    return catalogs, publication


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "index", "lane"))
    parser.add_argument("--request", required=True)
    parser.add_argument("--asset-class")
    parser.add_argument("--index", type=int)
    args = parser.parse_args(argv)
    values = dict(os.environ)
    try:
        if args.action == "build":
            output = build_spool(args.request, values=values)
            event = {
                "event": "lane_scoped_comprehensive_discovery_spool_ready",
                "manifest_path": str(output),
            }
        elif args.action == "index":
            _catalog_index_stage(args.request, values)
            event = {"event": "lane_scoped_catalog_index_ready"}
        else:
            if args.asset_class is None or args.index is None:
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    "lane-scoped lane stage requires --asset-class and --index"
                )
            _lane_stage(
                args.request,
                values,
                asset_class_value=args.asset_class,
                index=args.index,
            )
            event = {
                "event": "lane_scoped_comprehensive_lane_ready",
                "asset_class": args.asset_class,
                "index": args.index,
            }
    except BaseException as error:  # noqa: BLE001 - finite subprocess boundary is fail-closed.
        print(
            json.dumps(
                {
                    "event": "lane_scoped_comprehensive_discovery_spool_failed",
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
    "LaneScopedCatalogMapping",
    "LaneScopedPublicationIndex",
    "build_spool",
    "load_finalizer_inputs",
]
