"""One finite transaction per comprehensive-discovery market lane.

The historical lane-local spool persisted a raw catalog shard, re-opened it in a second
child, persisted a merged shard, and deferred screening until every catalog/publication
lane had finished.  On Render those finite children still share one cgroup, so clean page
cache from earlier lane artifacts could accumulate even though process RSS stayed small.

This worker keeps one lane's raw catalog in memory only.  It reconstructs the governed
catalog, merges the certified lane, produces the provider-preselection publication,
performs terminal screening, writes only the durable artifacts needed by the downstream
provider-facing lane and provider-free finalizer, retires any obsolete raw scratch, and
then exits.  A restart may reuse a complete integrity-checked transaction state.

This is operational transport only.  It does not change market membership, provider
requirements, screening thresholds, evidence completeness/freshness, CIO authority,
construction, execution, or paper-only governance.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cio import CandidateAssetClass
from operations import authoritative_comprehensive_discovery as _authoritative
from operations import bounded_comprehensive_discovery_spool as _bounded
from operations import bounded_lane_comprehensive_discovery_worker as _bounded_lane
from operations import bounded_provider_preselection_publication as _publication
from operations import comprehensive_discovery_input_spool as _legacy
from operations import lane_local_comprehensive_discovery_spool as _lane_local
from operations import persistent_certification_scheduler as _scheduler
from operations.evidence_file_cache_release import release_current_reference_file_cache

# Transaction state is stored through bounded_comprehensive_discovery_spool's existing
# integrity-protected stage envelope, so its schema must remain the bounded stage schema.
_TRANSACTION_SCHEMA = _bounded._STAGE_SCHEMA


def _transaction_state_name(index: int) -> str:
    return _lane_local._lane_state_name("lane-transaction", index)


def _raw_catalog_path(directory: Path, *, asset_class: str, index: int) -> Path:
    return directory / (
        f"raw-catalog-{index:03d}-{_legacy._safe_release(asset_class)}.pkl"
    )


def _merged_catalog_name(*, asset_class: str, index: int) -> str:
    return f"merged-catalog-{index:03d}-{_legacy._safe_release(asset_class)}.pkl"


def _publication_path(directory: Path, *, asset_class: str, index: int) -> Path:
    return directory / (
        "provider-preselection-"
        f"{index:03d}-{_legacy._safe_release(asset_class)}.json"
    )


def _advise_clean_path(path: Path) -> bool:
    """Best-effort DONTNEED for one completed regular file without modifying it."""

    fadvise = getattr(os, "posix_fadvise", None)
    dontneed = getattr(os, "POSIX_FADV_DONTNEED", None)
    if not callable(fadvise) or dontneed is None:
        return False
    try:
        if path.is_symlink() or not path.is_file():
            return False
        with path.open("rb") as handle:
            fadvise(handle.fileno(), 0, 0, dontneed)
    except (OSError, ValueError):
        return False
    return True


def _retire_obsolete_raw_catalog(directory: Path, *, asset_class: str, index: int) -> bool:
    """Delete only the legacy transaction-local raw catalog scratch file, if present."""

    path = _raw_catalog_path(directory, asset_class=asset_class, index=index)
    try:
        if path.is_symlink():
            return False
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


def _load_catalog_records(
    *,
    core,
    values: Mapping[str, str],
    policy,
    timestamp,
    asset_class: CandidateAssetClass,
) -> tuple[object, ...]:
    """Reconstruct one governed lane without persisting a raw catalog blob."""

    from operations import generalized_reference_readiness as generalized
    from operations import supervised_reference_prequalification as supervised

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
        records = _lane_local._reconstruct_component_records(
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
    return records


def _build_deep_lane(
    *,
    core,
    request: Mapping[str, object],
    policy,
    timestamp,
    asset_class: CandidateAssetClass,
    merged: Sequence[object],
    publication_path: str,
    values: Mapping[str, str],
    directory: Path,
    index: int,
) -> tuple[Mapping[str, object], bool, int]:
    """Screen the in-memory merged lane once and persist only its deep-record checkpoint."""

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
    continuity: list[object] = []
    ordinary: list[object] = []
    lifecycle_cutoff = timestamp + timedelta(days=7)
    for item in merged:
        if item.symbol in excluded:
            continue
        if item.expiration_at is not None and item.expiration_at <= lifecycle_cutoff:
            continue
        if item.symbol in state_symbols:
            continuity.append(item)
        else:
            ordinary.append(item)

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

    continuity_count = len(continuity)
    deep_records = continuity
    deep_records.extend(bounded.nominated)
    node_id = f"deep-market-evidence:{asset_class.value}"
    fingerprint = _scheduler._digest(
        {
            "record_fingerprint": _scheduler._record_fingerprint(deep_records),
            "policy_version": str(getattr(policy, "version", "")),
            "asset_class": asset_class.value,
            "decision_epoch": timestamp.isoformat(),
        }
    )
    node = _scheduler.CertificationNode(
        node_id=node_id,
        asset_class=asset_class.value,
        provider_groups=_scheduler._provider_groups(asset_class.value),
        input_fingerprint=fingerprint,
        deadline=timestamp
        + timedelta(seconds=_scheduler._market_node_valid_seconds(values)),
        decision_eligible_count=len(deep_records),
        priority=continuity_count,
    )
    rebound = _authoritative._rebind_compatible_checkpoint(
        values,
        release_sha=_scheduler._release(values),
        node=node,
        records=deep_records,
        epoch=timestamp,
        policy_version=str(getattr(policy, "version", "")),
    )
    lane_descriptor = _legacy._write_pickle_blob(
        directory,
        f"lane-{index:03d}-{_legacy._safe_release(node.node_id)}.pkl",
        deep_records,
    )
    node_body = _legacy._node_body(node, lane_descriptor)
    peak = _bounded._peak_rss_bytes()
    _bounded._write_stage_state(
        directory / "request.json",
        _lane_local._lane_state_name("lane-stage", index),
        {
            "request_id": request.get("request_id"),
            "node": node_body,
            "compatibility_rebound": bool(rebound),
            "peak_rss_bytes": peak,
            "transactional_lane_compaction": True,
        },
    )
    _advise_clean_path(directory / lane_descriptor.relative_path)
    return node_body, bool(rebound), peak


def _reusable_transaction_state(
    request_path: Path,
    *,
    request_id: str,
    asset_class: str,
    index: int,
    decision_epoch: datetime,
    freshness_days: int,
) -> Mapping[str, object] | None:
    """Return a prior complete lane transaction only when every retained artifact verifies."""

    try:
        state = _bounded._load_stage_state(request_path, _transaction_state_name(index))
    except (OSError, RuntimeError, TypeError, ValueError, _legacy.ComprehensiveDiscoverySpoolError):
        return None
    if state.get("schema_version") != _TRANSACTION_SCHEMA:
        return None
    if state.get("transactional_lane_compaction") is not True:
        return None
    if state.get("raw_catalog_persisted") is not False:
        return None
    if str(state.get("request_id") or "") != request_id:
        return None
    if str(state.get("asset_class") or "") != asset_class:
        return None
    try:
        merged = _legacy._descriptor(state.get("blob"))
        _legacy._verify_blob(request_path.parent, merged)
        if state.get("scheduled") is True:
            verify_transaction_publication_state(
                state,
                decision_epoch=decision_epoch,
                freshness_days=freshness_days,
            )
            node = state.get("node")
            if not isinstance(node, Mapping):
                return None
            lane_blob = _legacy._descriptor(node.get("lane_blob"))
            _legacy._verify_blob(request_path.parent, lane_blob)
    except (OSError, RuntimeError, TypeError, ValueError, _legacy.ComprehensiveDiscoverySpoolError):
        return None
    return state


def verify_transaction_publication_state(
    state: Mapping[str, object],
    *,
    decision_epoch: datetime,
    freshness_days: int,
) -> _publication.ProviderPreselectionPublicationResult:
    """Reopen the exact child publication from compact committed transaction proof."""

    if state.get("provider_publication_verified") is not True:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            "transactional scheduled lane lacks verified provider publication"
        )
    completed_at = _legacy._parse_timestamp(
        state.get("provider_publication_completed_at"),
        field_name="provider_publication_completed_at",
    )
    if completed_at < decision_epoch:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            "transactional provider publication completion predates its decision epoch"
        )
    path = Path(str(state.get("provider_preselection_path") or ""))
    fingerprint = str(state.get("provider_publication_fingerprint") or "").strip()
    if not fingerprint:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            "transactional provider publication fingerprint is unavailable"
        )
    try:
        catalog_count = int(state.get("provider_publication_catalog_count"))
        signal_count = int(state.get("provider_publication_signal_count"))
        available_at = _legacy._parse_timestamp(
            state.get("provider_publication_available_at"),
            field_name="provider_publication_available_at",
        )
        return _publication.verify_provider_preselection_artifact(
            path,
            as_of=decision_epoch,
            fingerprint=fingerprint,
            catalog_count=catalog_count,
            signal_count=signal_count,
            available_at=available_at,
            freshness_days=int(freshness_days),
        )
    except (
        OSError,
        TypeError,
        ValueError,
        _publication.ProviderPreselectionPublicationError,
    ) as error:
        raise _legacy.ComprehensiveDiscoverySpoolError(
            "transactional provider publication failed committed exact-path readback; "
            f"failure_type={type(error).__name__}; detail={error}"
        ) from error


def run_lane_transaction(
    request_path: str | Path,
    values: Mapping[str, str],
    *,
    asset_class_value: str,
    index: int,
) -> Mapping[str, object]:
    """Execute or reuse one complete compact lane transaction."""

    path = Path(request_path).expanduser()
    stage = f"transactional_comprehensive_lane:{asset_class_value}"
    try:
        request, policy = _bounded._validate_request(path, values)
        request_id = str(request.get("request_id") or "")
        timestamp = _legacy._parse_timestamp(
            request.get("decision_epoch"), field_name="decision_epoch"
        )
        reusable = _reusable_transaction_state(
            path,
            request_id=request_id,
            asset_class=asset_class_value,
            index=index,
            decision_epoch=timestamp,
            freshness_days=int(getattr(policy, "preselection_freshness_days", 3)),
        )
        if reusable is not None:
            return reusable
        asset_class = CandidateAssetClass(asset_class_value)
        directory = path.parent

        from operations import comprehensive_market_discovery as facade

        core = facade._core
        raw = _load_catalog_records(
            core=core,
            values=values,
            policy=policy,
            timestamp=timestamp,
            asset_class=asset_class,
        )
        raw_record_count = len(raw)

        merged = _bounded_lane._merge_certified_lane(
            core,
            raw,
            asset_class=asset_class,
            timestamp=timestamp,
        )
        del raw

        required = asset_class in core._base._DEFAULT_REQUIRED_DISCOVERY_LANES
        dynamic = bool(required or merged)
        scheduled = bool(
            dynamic and core._base._lane_is_scheduled(asset_class, timestamp)
        )
        merged_descriptor = _legacy._write_pickle_blob(
            directory,
            _merged_catalog_name(asset_class=asset_class.value, index=index),
            merged,
        )

        publication_path: str | None = None
        publication_verified = False
        publication_result: _publication.ProviderPreselectionPublicationResult | None = None
        publication_fingerprint: str | None = None
        publication_completed_at: str | None = None
        lane_policy = None
        if scheduled:
            publication_file = _publication_path(
                directory, asset_class=asset_class.value, index=index
            )
            publication_path = str(publication_file)
            lane_policy = replace(
                policy, provider_preselection_path=publication_path
            )
            try:
                publication_fingerprint = (
                    _publication.provider_preselection_catalog_fingerprint(
                        {asset_class: merged}
                    )
                )
                publication_result = _publication.ensure_provider_preselection_publication(
                    {asset_class: merged},
                    as_of=timestamp,
                    policy=lane_policy,
                    market_probe=core.default_provider_preselection_market_probe,
                )
                verified_publication = _publication.verify_provider_preselection_publication(
                    {asset_class: merged},
                    publication=publication_result,
                    as_of=timestamp,
                    policy=lane_policy,
                    expected_path=publication_file,
                )
            except _publication.ProviderPreselectionPublicationError as error:
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"{asset_class.value} transactional provider publication failed; "
                    f"failure_type={type(error).__name__}; detail={error}"
                ) from error
            if int(getattr(verified_publication, "catalog_count", -1)) != len(merged):
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"{asset_class.value} transactional provider publication count changed"
                )
            publication_verified = True

        peak = _bounded._peak_rss_bytes()
        publication_state: dict[str, object] = {
            "request_id": request_id,
            "asset_class": asset_class.value,
            "blob": _legacy._descriptor_dict(merged_descriptor),
            "record_count": len(merged),
            "dynamic": dynamic,
            "scheduled": scheduled,
            "provider_preselection_path": publication_path,
            "provider_publication_verified": publication_verified,
            "provider_publication_fingerprint": publication_fingerprint,
            "provider_publication_catalog_count": (
                None if publication_result is None else publication_result.catalog_count
            ),
            "provider_publication_signal_count": (
                None if publication_result is None else publication_result.signal_count
            ),
            "provider_publication_available_at": (
                None
                if publication_result is None
                else publication_result.available_at.isoformat()
            ),
            "provider_publication_freshness_days": int(
                getattr(policy, "preselection_freshness_days", 3)
            ),
            "peak_rss_bytes": peak,
            "bounded_provider_publication": True,
            "transactional_lane_compaction": True,
            "raw_catalog_persisted": False,
        }
        _bounded._write_stage_state(
            path,
            _lane_local._lane_state_name("catalog-lane", index),
            {
                "request_id": request_id,
                "asset_class": asset_class.value,
                "record_count": raw_record_count,
                "peak_rss_bytes": peak,
                "transactional_lane_compaction": True,
                "raw_catalog_persisted": False,
            },
        )
        _bounded._write_stage_state(
            path,
            _lane_local._lane_state_name("publication-lane", index),
            publication_state,
        )

        node_body: Mapping[str, object] | None = None
        rebound = False
        if scheduled:
            assert publication_path is not None
            node_body, rebound, screening_peak = _build_deep_lane(
                core=core,
                request=request,
                policy=policy,
                timestamp=timestamp,
                asset_class=asset_class,
                merged=merged,
                publication_path=publication_path,
                values=values,
                directory=directory,
                index=index,
            )
            peak = max(peak, screening_peak)
            if publication_result is None or lane_policy is None:
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"{asset_class.value} scheduled lane lost provider publication state"
                )
            try:
                _publication.verify_provider_preselection_publication(
                    {asset_class: merged},
                    publication=publication_result,
                    as_of=timestamp,
                    policy=lane_policy,
                    expected_path=publication_path,
                )
            except _publication.ProviderPreselectionPublicationError as error:
                raise _legacy.ComprehensiveDiscoverySpoolError(
                    f"{asset_class.value} provider publication failed pre-commit readback; "
                    f"failure_type={type(error).__name__}; detail={error}"
                ) from error
            publication_completed_at = datetime.now(timezone.utc).isoformat()

        transaction_state: dict[str, object] = {
            "request_id": request_id,
            "asset_class": asset_class.value,
            "raw_record_count": raw_record_count,
            "record_count": len(merged),
            "blob": _legacy._descriptor_dict(merged_descriptor),
            "dynamic": dynamic,
            "scheduled": scheduled,
            "provider_preselection_path": publication_path,
            "provider_publication_verified": publication_verified,
            "provider_publication_fingerprint": publication_fingerprint,
            "provider_publication_catalog_count": (
                None if publication_result is None else publication_result.catalog_count
            ),
            "provider_publication_signal_count": (
                None if publication_result is None else publication_result.signal_count
            ),
            "provider_publication_available_at": (
                None
                if publication_result is None
                else publication_result.available_at.isoformat()
            ),
            "provider_publication_completed_at": publication_completed_at,
            "provider_publication_freshness_days": int(
                getattr(policy, "preselection_freshness_days", 3)
            ),
            "node": dict(node_body) if isinstance(node_body, Mapping) else None,
            "compatibility_rebound": rebound,
            "peak_rss_bytes": peak,
            "transactional_lane_compaction": True,
            "raw_catalog_persisted": False,
            **_legacy._authority_fields(),
        }
        _bounded._write_stage_state(path, _transaction_state_name(index), transaction_state)

        _retire_obsolete_raw_catalog(
            directory, asset_class=asset_class.value, index=index
        )
        _advise_clean_path(directory / merged_descriptor.relative_path)
        if publication_path:
            _advise_clean_path(Path(publication_path))
        try:
            release_current_reference_file_cache(values)
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
        return transaction_state
    except BaseException as error:  # noqa: BLE001 - persist exact fail-closed attribution.
        try:
            _legacy._write_failure(path, stage=stage, error=error, values=values)
        except BaseException:
            pass
        raise


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--asset-class", required=True)
    parser.add_argument("--index", required=True, type=int)
    args = parser.parse_args()
    try:
        run_lane_transaction(
            args.request,
            dict(os.environ),
            asset_class_value=args.asset_class,
            index=args.index,
        )
    except BaseException as error:  # noqa: BLE001 - finite transaction child fails closed.
        print(
            f"transactional comprehensive discovery lane failed: {type(error).__name__}",
            flush=True,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "_TRANSACTION_SCHEMA",
    "_reusable_transaction_state",
    "_transaction_state_name",
    "run_lane_transaction",
]
