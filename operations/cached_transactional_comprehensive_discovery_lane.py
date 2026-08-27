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

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from cio import CandidateAssetClass
from operations import comprehensive_discovery_structural_cache as _structural
from operations import transactional_comprehensive_discovery_lane as _canonical


_ORIGINAL_LOAD_CATALOG_RECORDS = _canonical._load_catalog_records
_ORIGINAL_MERGE_CERTIFIED_LANE = _canonical._bounded_lane._merge_certified_lane
_ORIGINAL_RUN_LANE_TRANSACTION = _canonical.run_lane_transaction
_ORIGINAL_BUILD_DEEP_LANE = _canonical._build_deep_lane
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
    cached = _structural.load_structural_catalog(
        values,
        asset_class=asset_class,
        policy_version=policy_version,
        requested_as_of=timestamp,
    )
    if cached is not None and _same_lane_schedule(
        core, asset_class, cached.source_as_of, timestamp
    ):
        return _CachedMergedRecords(cached.records, cached.raw_record_count)

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
    _record_watchdog_phase("publication-lane")
    return merged


def _build_deep_lane(*args, **kwargs):
    """Mark screening active only at the canonical publication-to-screening handoff."""

    # The canonical transaction persists publication-lane-### immediately before calling
    # this function. Publishing the marker here therefore cannot claim screening before
    # durable same-lane publication evidence exists.
    _record_watchdog_phase("screening-lane")
    return _ORIGINAL_BUILD_DEEP_LANE(*args, **kwargs)


def _run_lane_transaction(
    request_path,
    values: Mapping[str, str],
    *,
    asset_class_value: str,
    index: int,
):
    """Bind advisory phase-marker context to this one finite lane transaction."""

    global _ACTIVE_REQUEST_PATH, _ACTIVE_VALUES, _ACTIVE_ASSET_CLASS, _ACTIVE_INDEX
    _ACTIVE_REQUEST_PATH = Path(request_path).expanduser()
    _ACTIVE_VALUES = values
    _ACTIVE_ASSET_CLASS = str(asset_class_value or "").strip().lower()
    _ACTIVE_INDEX = int(index)
    try:
        return _ORIGINAL_RUN_LANE_TRANSACTION(
            request_path,
            values,
            asset_class_value=asset_class_value,
            index=index,
        )
    finally:
        _ACTIVE_REQUEST_PATH = None
        _ACTIVE_VALUES = None
        _ACTIVE_ASSET_CLASS = ""
        _ACTIVE_INDEX = -1


def install_cached_structural_lane_loader() -> None:
    """Install structural-only reuse and exact advisory phase transitions in this child."""

    _canonical._load_catalog_records = _load_catalog_records
    _canonical._bounded_lane._merge_certified_lane = _merge_certified_lane
    _canonical._build_deep_lane = _build_deep_lane
    _canonical.run_lane_transaction = _run_lane_transaction


def _main() -> int:
    install_cached_structural_lane_loader()
    return _canonical._main()


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["install_cached_structural_lane_loader"]
