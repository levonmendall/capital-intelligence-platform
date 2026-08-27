"""Transactional comprehensive lane with release-bound structural input reuse.

Only the raw reference-derived catalog reconstruction is reusable across evidence retry
epochs. The canonical transaction remains responsible for certified-catalog merge,
provider preselection, terminal screening, certification-node construction, exact-epoch
market evidence, and all durable transaction state.

This wrapper cannot certify evidence or authorize an investment action. Cache misses,
corruption, identity changes, and option catalogs fall through to the unchanged canonical
reconstruction path.
"""

from __future__ import annotations

from collections.abc import Mapping

from cio import CandidateAssetClass
from operations import comprehensive_discovery_structural_cache as _structural
from operations import transactional_comprehensive_discovery_lane as _canonical


_ORIGINAL_LOAD_CATALOG_RECORDS = _canonical._load_catalog_records


def _load_catalog_records(
    *,
    core,
    values: Mapping[str, str],
    policy,
    timestamp,
    asset_class: CandidateAssetClass,
):
    policy_version = str(getattr(policy, "version", ""))
    cached = _structural.load_structural_catalog(
        values,
        asset_class=asset_class,
        policy_version=policy_version,
        requested_as_of=timestamp,
    )
    if cached is not None:
        return cached.records

    records = _ORIGINAL_LOAD_CATALOG_RECORDS(
        core=core,
        values=values,
        policy=policy,
        timestamp=timestamp,
        asset_class=asset_class,
    )
    try:
        _structural.publish_structural_catalog(
            values,
            asset_class=asset_class,
            policy_version=policy_version,
            source_as_of=timestamp,
            raw_record_count=len(records),
            records=records,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        # Structural reuse is an operational acceleration only. Failure to persist it must
        # never change the canonical current-epoch evidence result.
        pass
    return records


def install_cached_structural_lane_loader() -> None:
    """Install the structural-only loader into the finite transaction interpreter."""

    _canonical._load_catalog_records = _load_catalog_records


def _main() -> int:
    install_cached_structural_lane_loader()
    return _canonical._main()


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["install_cached_structural_lane_loader"]
