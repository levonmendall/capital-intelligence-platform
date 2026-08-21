"""Second-level bounded worker for comprehensive discovery after telemetry #698.

The coordinator already isolates asset classes into finite child interpreters. This worker
tightens the remaining child-local peak by keeping certified-catalog expansion lane scoped
and by partitioning terminal-screening inputs in one pass without retaining redundant
full-lane containers.

This is operational memory management only. It does not change catalog membership,
provider requirements, screening rules, thresholds, CIO authority, construction,
execution, or paper-only governance.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from cio import CandidateAssetClass
from operations import bounded_comprehensive_discovery_spool as _bounded
from operations import comprehensive_discovery_input_spool as _legacy
from operations import lane_local_comprehensive_discovery_spool as _lane_local

_MODULE = "operations.bounded_lane_comprehensive_discovery_worker"


def _record_identity(record: Mapping[str, object], *, index: int, source: str) -> str:
    identifier = str(
        record.get("instrument_identifier")
        or record.get("source_identifier")
        or ""
    ).strip()
    if not identifier:
        from operations import certified_investable_catalog as certified

        raise certified.CertifiedInvestableCatalogError(
            f"{source}[{index}] lacks a stable instrument/source identifier"
        )
    return identifier


def _load_certified_lane(
    *,
    timestamp,
    asset_class: CandidateAssetClass,
) -> tuple[Mapping[str, object], ...]:
    """Validate the complete configured catalog while retaining only one asset class."""

    from operations import certified_investable_catalog as certified

    target = asset_class.value
    identities: set[str] = set()
    selected: list[Mapping[str, object]] = []

    # Preserve global duplicate validation against the governed built-in crypto catalog,
    # but do not retain those records for unrelated lanes.
    crypto_records = certified._certified_crypto_records()
    for index, record in enumerate(crypto_records):
        identifier = _record_identity(record, index=index, source="crypto_records")
        if identifier in identities:
            raise certified.CertifiedInvestableCatalogError(
                f"duplicate certified instrument identity: {identifier}"
            )
        identities.add(identifier)
        if target == CandidateAssetClass.CRYPTO.value:
            selected.append(record)
    del crypto_records

    source = certified.configured_path()
    if source is None:
        return tuple(selected)

    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except OSError as error:
        raise certified.CertifiedInvestableCatalogError(
            f"configured certified catalog is unavailable at {source}"
        ) from error
    except json.JSONDecodeError as error:
        raise certified.CertifiedInvestableCatalogError(
            "configured certified catalog is invalid JSON"
        ) from error

    if not isinstance(payload, Mapping):
        raise certified.CertifiedInvestableCatalogError(
            "certified catalog must be a JSON object"
        )
    if payload.get("schema_version") != certified.SCHEMA_VERSION:
        raise certified.CertifiedInvestableCatalogError(
            "unsupported certified catalog schema"
        )
    if payload.get("complete") is not True:
        raise certified.CertifiedInvestableCatalogError(
            "certified catalog does not attest complete provider coverage"
        )

    catalog_as_of = certified._timestamp(payload.get("as_of"), field_name="as_of")
    available_at = certified._timestamp(
        payload.get("available_at"), field_name="available_at"
    )
    if catalog_as_of > timestamp or available_at > timestamp:
        raise certified.CertifiedInvestableCatalogError(
            "certified catalog contains future-known membership"
        )

    raw_records = payload.get("records")
    if not isinstance(raw_records, Sequence) or isinstance(
        raw_records, (str, bytes, bytearray)
    ):
        raise certified.CertifiedInvestableCatalogError(
            "catalog records must be a sequence"
        )

    for index, item in enumerate(raw_records):
        if not isinstance(item, Mapping):
            raise certified.CertifiedInvestableCatalogError(
                "every certified catalog record must be an object"
            )
        identifier = _record_identity(item, index=index, source="records")
        if identifier in identities:
            raise certified.CertifiedInvestableCatalogError(
                f"duplicate certified instrument identity: {identifier}"
            )
        identities.add(identifier)
        if str(item.get("asset_class") or "").strip().lower() == target:
            selected.append(item)

    return tuple(selected)


def _merge_certified_lane(core, raw: Sequence[object], *, asset_class, timestamp):
    try:
        external = _load_certified_lane(
            timestamp=timestamp,
            asset_class=asset_class,
        )
    except Exception as error:
        from operations import certified_investable_catalog as certified

        if isinstance(error, certified.CertifiedInvestableCatalogError):
            raise _legacy.ComprehensiveDiscoverySpoolError(str(error)) from error
        raise

    merged = list(raw)
    for payload in external:
        record = core._base._certified_catalog_record(payload)
        if record.asset_class is asset_class:
            merged.append(record)
    del external
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
        merged = _merge_certified_lane(
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
            path, _lane_local._lane_state_name("publication-lane", index)
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
        del held, tracked

        from operations import authoritative_comprehensive_discovery as authoritative
        from operations import comprehensive_market_discovery as facade
        from operations import persistent_certification_scheduler as scheduler

        core = facade._core
        asset_class = CandidateAssetClass(asset_class_value)
        catalog_records = _legacy._load_pickle_blob(
            path.parent, _legacy._descriptor(state.get("blob"))
        )
        if not isinstance(catalog_records, Sequence) or isinstance(
            catalog_records, (str, bytes, bytearray)
        ):
            raise _legacy.ComprehensiveDiscoverySpoolError(
                f"{asset_class.value} lane-local merged catalog shard is malformed"
            )

        # The publication-stage shard is already deduplicated and integrity checked.
        # Partition it once instead of retaining catalog_records + eligible +
        # continuity + ordinary as four overlapping full-lane containers.
        continuity: list[object] = []
        ordinary: list[object] = []
        lifecycle_cutoff = timestamp + timedelta(days=7)
        for item in catalog_records:
            if item.symbol in excluded:
                continue
            if (
                item.expiration_at is not None
                and item.expiration_at <= lifecycle_cutoff
            ):
                continue
            if item.symbol in state_symbols:
                continuity.append(item)
            else:
                ordinary.append(item)
        del catalog_records, excluded, state_symbols

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
        del ordinary

        # continuity and nominated originate from disjoint partitions of one
        # deduplicated lane. Reuse the continuity list as the final deep-record
        # container rather than constructing another tuple/dict pair.
        nominated = bounded.nominated
        del bounded
        continuity_count = len(continuity)
        deep_records = continuity
        deep_records.extend(nominated)
        del nominated

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
            priority=continuity_count,
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
            _lane_local._lane_state_name("lane-stage", index),
            {
                "request_id": request.get("request_id"),
                "node": _legacy._node_body(node, descriptor),
                "compatibility_rebound": bool(rebound),
                "peak_rss_bytes": peak,
            },
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
            _lane_local._catalog_lane_stage(
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
            f"bounded lane comprehensive discovery failed: {type(error).__name__}",
            file=sys.stderr,
            flush=True,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "_load_certified_lane",
    "_publication_lane_stage",
    "_screening_lane_stage",
    "run_stage",
]
