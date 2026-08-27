"""Transactional comprehensive lane with release-bound structural input reuse.

A warm evidence retry may reuse only the already-merged structural catalog produced by
the same software release, policy version, and bound reference manifest. Provider
preselection, terminal screening, certification-node construction, exact-epoch market
evidence, and durable transaction state all remain owned by the unchanged canonical
transaction and are rebuilt for the new evidence epoch.

This wrapper cannot certify evidence or authorize an investment action. Cache misses,
corruption, identity changes, and option catalogs fall through to the unchanged canonical
reconstruction and merge path.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from cio import CandidateAssetClass
from operations import comprehensive_discovery_structural_cache as _structural
from operations import transactional_comprehensive_discovery_lane as _canonical


_ORIGINAL_LOAD_CATALOG_RECORDS = _canonical._load_catalog_records
_ORIGINAL_MERGE_CERTIFIED_LANE = _canonical._bounded_lane._merge_certified_lane
_ACTIVE_POLICY_VERSION = ""


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
    if cached is not None:
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
        # policy, and currently bound reference manifest. Do not re-merge it, but also do
        # not reuse any publication/screening/market artifact from the source epoch.
        return raw.records

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
        # Structural reuse is an operational acceleration only. Failure to persist it must
        # never change the canonical current-epoch evidence result.
        pass
    return merged


def install_cached_structural_lane_loader() -> None:
    """Install structural-only reuse inside this finite transaction interpreter."""

    _canonical._load_catalog_records = _load_catalog_records
    _canonical._bounded_lane._merge_certified_lane = _merge_certified_lane


def _main() -> int:
    install_cached_structural_lane_loader()
    return _canonical._main()


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["install_cached_structural_lane_loader"]
