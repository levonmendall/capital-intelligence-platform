"""Transactional comprehensive lane with release-bound structural input reuse.

A warm evidence retry may reuse only the already-merged structural catalog produced by
the same software release, policy version, bound reference manifest, and lane scheduling
state. Provider preselection, terminal screening, certification-node construction,
exact-epoch market evidence, and durable transaction state all remain owned by the
unchanged canonical transaction and are rebuilt for the new evidence epoch.

This wrapper cannot certify evidence or authorize an investment action. Cache misses,
corruption, identity changes, schedule changes, and option catalogs fall through to the
unchanged canonical reconstruction and merge path.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cio import CandidateAssetClass
from operations import comprehensive_discovery_structural_cache as _structural
from operations import transactional_comprehensive_discovery_lane as _canonical


_ORIGINAL_LOAD_CATALOG_RECORDS = _canonical._load_catalog_records
_ORIGINAL_MERGE_CERTIFIED_LANE = _canonical._bounded_lane._merge_certified_lane
_ORIGINAL_RUN_LANE_TRANSACTION = _canonical.run_lane_transaction
_ORIGINAL_BUILD_DEEP_LANE = _canonical._build_deep_lane
_ORIGINAL_ENSURE_PROVIDER_PRESELECTION_PUBLICATION = (
    _canonical._publication.ensure_provider_preselection_publication
)
_RENDER_PUBLICATION_TERMINATION_GRACE_SECONDS = 1.0
_ACTIVE_POLICY_VERSION = ""
_ACTIVE_REQUEST_PATH: Path | None = None
_ACTIVE_VALUES: Mapping[str, str] | None = None
_ACTIVE_ASSET_CLASS = ""
_ACTIVE_INDEX = -1


@dataclass(frozen=True, slots=True)
class _CachedMergedRecords(Sequence[object]):
    records: tuple[object, ...]
    raw_record_count: int

    def __len__(self) -> int:
        # The canonical transaction records this before merge for operational telemetry.
        return self.raw_record_count

    def __getitem__(self, index):
        return self.records[index]

    def __iter__(self) -> Iterator[object]:
        return iter(self.records)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_lane_timing(**updates: object) -> None:
    """Persist advisory timing without affecting evidence or watchdog progress."""

    if (
        _ACTIVE_REQUEST_PATH is None
        or _ACTIVE_VALUES is None
        or not _ACTIVE_ASSET_CLASS
        or _ACTIVE_INDEX < 0
    ):
        return
    try:
        from operations.comprehensive_discovery_lane_telemetry import record_lane_phase

        record_lane_phase(
            _ACTIVE_REQUEST_PATH,
            _ACTIVE_VALUES,
            asset_class=_ACTIVE_ASSET_CLASS,
            index=_ACTIVE_INDEX,
            **updates,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        # Telemetry is fail-soft and cannot change the canonical lane outcome.
        pass


def _record_watchdog_phase(action: str) -> None:
    """Publish one advisory logical phase marker without affecting evidence authority."""

    if (
        _ACTIVE_REQUEST_PATH is None
        or _ACTIVE_VALUES is None
        or not _ACTIVE_ASSET_CLASS
        or _ACTIVE_INDEX < 0
    ):
        return
    try:
        from operations.lane_local_watchdog_progress import (
            record_active_lane_watchdog_progress,
        )

        record_active_lane_watchdog_progress(
            _ACTIVE_REQUEST_PATH,
            _ACTIVE_VALUES,
            action=action,
            asset_class=_ACTIVE_ASSET_CLASS,
            index=_ACTIVE_INDEX,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        # Watchdog projection is observability-only. Canonical evidence work remains the
        # authority and must not fail merely because a progress marker cannot be written.
        pass


def _same_lane_schedule(core, asset_class: CandidateAssetClass, source, requested) -> bool:
    source_active = asset_class in core._base.scheduled_discovery_lanes(source)
    requested_active = asset_class in core._base.scheduled_discovery_lanes(requested)
    return source_active is requested_active


def _render_enabled(values: Mapping[str, str]) -> bool:
    return str(values.get("RENDER") or "").strip().lower() == "true"


def _terminate_and_reap_provider_publication(process: subprocess.Popen[bytes]) -> int:
    return_code = process.poll()
    if return_code is not None:
        return int(return_code)
    process.terminate()
    try:
        return int(process.wait(timeout=_RENDER_PUBLICATION_TERMINATION_GRACE_SECONDS))
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            return int(process.wait(timeout=_RENDER_PUBLICATION_TERMINATION_GRACE_SECONDS))
        except subprocess.TimeoutExpired as error:
            raise _canonical._publication.ProviderPreselectionPublicationError(
                "transactional provider publication child remained live after bounded kill"
            ) from error


def _call_original_provider_publication(
    catalogs,
    *,
    as_of,
    policy,
    http_get,
    market_probe,
):
    return _ORIGINAL_ENSURE_PROVIDER_PRESELECTION_PUBLICATION(
        catalogs,
        as_of=as_of,
        policy=policy,
        http_get=http_get,
        market_probe=market_probe,
    )


def _ensure_provider_preselection_publication(
    catalogs,
    *,
    as_of,
    policy=None,
    http_get=_canonical._publication._core.requests.get,
    market_probe=None,
):
    """Keep cacheable Render lane provider acquisition inside the existing epoch budget."""

    values = _ACTIVE_VALUES
    request_path = _ACTIVE_REQUEST_PATH
    if values is None or request_path is None or not _render_enabled(values):
        return _call_original_provider_publication(
            catalogs,
            as_of=as_of,
            policy=policy,
            http_get=http_get,
            market_probe=market_probe,
        )
    if not _ACTIVE_ASSET_CLASS or _ACTIVE_INDEX < 0:
        raise _canonical._publication.ProviderPreselectionPublicationError(
            "transactional provider publication has no active lane identity"
        )

    asset_class = CandidateAssetClass(_ACTIVE_ASSET_CLASS)
    if asset_class is CandidateAssetClass.OPTION:
        # The existing provider-acquisition child deliberately excludes the timestamp-
        # constructed option catalog. Preserve that unchanged canonical path rather than
        # expanding this production-evidence repair beyond cacheable lanes.
        return _call_original_provider_publication(
            catalogs,
            as_of=as_of,
            policy=policy,
            http_get=http_get,
            market_probe=market_probe,
        )

    from operations import epoch_scoped_provider_acquisition as fanout

    timeout = float(fanout._fanout_budget_seconds(as_of, values))
    if timeout <= 0.0:
        raise _canonical._publication.ProviderPreselectionPublicationError(
            "transactional provider publication cannot start because the existing evidence "
            "epoch has no provider-acquisition time beyond the downstream reserve"
        )

    process = subprocess.Popen(
        fanout._publication_command(
            request_path=request_path,
            asset_class=asset_class,
            index=_ACTIVE_INDEX,
        ),
        cwd=str(Path(__file__).resolve().parents[1]),
        env=dict(values),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=False,
    )
    try:
        return_code = int(process.wait(timeout=timeout))
    except subprocess.TimeoutExpired as error:
        return_code = _terminate_and_reap_provider_publication(process)
        raise _canonical._publication.ProviderPreselectionPublicationError(
            "transactional provider publication exceeded the existing epoch-scoped provider "
            f"acquisition window; timeout_seconds={timeout:.3f}; "
            f"child_return_code={return_code}; downstream reserve preserved"
        ) from error
    if return_code != 0:
        raise _canonical._publication.ProviderPreselectionPublicationError(
            "transactional bounded provider publication child failed; "
            f"return_code={return_code}; downstream reserve preserved"
        )

    resolved_policy = policy or _canonical._publication.ComprehensiveMarketDiscoveryPolicy()
    records = _canonical._publication._records_for_lane(catalogs)
    fingerprint = _canonical._publication._streaming_catalog_fingerprint(records)
    publication_path = _canonical._publication._core._publication_path(resolved_policy)
    freshness_days = int(getattr(resolved_policy, "preselection_freshness_days", 3))
    result = _canonical._publication._existing_result_bounded(
        publication_path,
        as_of=as_of,
        fingerprint=fingerprint,
        catalog_count=len(records),
        freshness_days=freshness_days,
    )
    if result is None or tuple(getattr(result, "limitations", ())):
        raise _canonical._publication.ProviderPreselectionPublicationError(
            "transactional bounded provider publication child did not produce a clean, "
            "current canonical publication"
        )
    return result


def _load_catalog_records(
    *,
    core,
    values: Mapping[str, str],
    policy,
    timestamp,
    asset_class: CandidateAssetClass,
):
    global _ACTIVE_POLICY_VERSION
    policy_version = str(getattr(policy, "version", ""))
    _ACTIVE_POLICY_VERSION = policy_version
    _record_lane_timing(structural_started_at=_now())
    cached = _structural.load_structural_catalog(
        values,
        asset_class=asset_class,
        policy_version=policy_version,
        requested_as_of=timestamp,
    )
    if cached is not None and _same_lane_schedule(
        core, asset_class, cached.source_as_of, timestamp
    ):
        _record_lane_timing(structural_cache_hit=True)
        return _CachedMergedRecords(cached.records, cached.raw_record_count)

    _record_lane_timing(
        structural_cache_hit=None
        if asset_class is CandidateAssetClass.OPTION
        else False
    )
    return _ORIGINAL_LOAD_CATALOG_RECORDS(
        core=core,
        values=values,
        policy=policy,
        timestamp=timestamp,
        asset_class=asset_class,
    )


def _merge_certified_lane(core, raw: Sequence[object], *, asset_class, timestamp):
    if isinstance(raw, _CachedMergedRecords):
        # The cache identity proves this merged structure came from the exact release,
        # policy, currently bound reference manifest, and compatible lane schedule. Do not
        # reuse any publication/screening/market artifact from the source epoch.
        merged = raw.records
    else:
        merged = _ORIGINAL_MERGE_CERTIFIED_LANE(
            core,
            raw,
            asset_class=asset_class,
            timestamp=timestamp,
        )
        try:
            _structural.publish_structural_catalog(
                dict(_canonical.os.environ),
                asset_class=asset_class,
                policy_version=_ACTIVE_POLICY_VERSION,
                source_as_of=timestamp,
                raw_record_count=len(raw),
                records=merged,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            # Structural reuse is an operational acceleration only. Failure to persist it
            # must never change the canonical current-epoch evidence result.
            pass

    # The canonical transaction moves directly from merge into provider publication. The
    # old transactional coordinator published only the initial catalog-lane start, leaving
    # the parent watchdog pinned to the prior durable completion during long later phases.
    transition = _now()
    _record_lane_timing(
        structural_completed_at=transition,
        publication_started_at=transition,
    )
    _record_watchdog_phase("publication-lane")
    return merged


def _build_deep_lane(*args, **kwargs):
    """Mark and time the canonical publication-to-screening handoff."""

    # The canonical transaction persists publication-lane-### immediately before calling
    # this function. Publishing the marker here therefore cannot claim screening before
    # durable same-lane publication evidence exists.
    transition = _now()
    _record_lane_timing(
        publication_completed_at=transition,
        screening_started_at=transition,
    )
    _record_watchdog_phase("screening-lane")
    try:
        # Preserve the literal canonical delegation asserted by the structural-cache
        # contract: instrumentation surrounds the call but never substitutes its result.
        return _ORIGINAL_BUILD_DEEP_LANE(*args, **kwargs)
    finally:
        if sys.exc_info()[0] is None:
            _record_lane_timing(screening_completed_at=_now())


def _run_lane_transaction(
    request_path,
    values: Mapping[str, str],
    *,
    asset_class_value: str,
    index: int,
):
    """Bind advisory phase-marker and timing context to one finite lane transaction."""

    global _ACTIVE_REQUEST_PATH, _ACTIVE_VALUES, _ACTIVE_ASSET_CLASS, _ACTIVE_INDEX
    _ACTIVE_REQUEST_PATH = Path(request_path).expanduser()
    _ACTIVE_VALUES = values
    _ACTIVE_ASSET_CLASS = str(asset_class_value or "").strip().lower()
    _ACTIVE_INDEX = int(index)
    _record_lane_timing(lane_started_at=_now())
    try:
        result = _ORIGINAL_RUN_LANE_TRANSACTION(
            request_path,
            values,
            asset_class_value=asset_class_value,
            index=index,
        )
    except BaseException as error:
        _record_lane_timing(lane_failed_at=_now(), error_type=type(error).__name__)
        raise
    else:
        _record_lane_timing(lane_completed_at=_now())
        return result
    finally:
        _ACTIVE_REQUEST_PATH = None
        _ACTIVE_VALUES = None
        _ACTIVE_ASSET_CLASS = ""
        _ACTIVE_INDEX = -1


def install_cached_structural_lane_loader() -> None:
    """Install structural reuse, bounded Render publication, and advisory phase timing."""

    _canonical._load_catalog_records = _load_catalog_records
    _canonical._bounded_lane._merge_certified_lane = _merge_certified_lane
    _canonical._publication.ensure_provider_preselection_publication = (
        _ensure_provider_preselection_publication
    )
    _canonical._build_deep_lane = _build_deep_lane
    _canonical.run_lane_transaction = _run_lane_transaction


def _main() -> int:
    install_cached_structural_lane_loader()
    return _canonical._main()


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["install_cached_structural_lane_loader"]
