"""Persist comprehensive-discovery progress below the asset-class lane boundary.

The existing persistent certification DAG makes each asset-class lane independently
resumable. Large lanes can still exceed one node execution budget, however, and a node
checkpoint is written only after its complete record set finishes. This module refines
that operational boundary without changing the governed universe or certification
criteria:

* large provider-facing lanes are partitioned deterministically by provider/venue/region
  metadata and then into bounded record-count shards;
* each shard remains an ordinary persistent certification node and therefore inherits
  provider budgets, killable process supervision, immutable exact-epoch checkpoints,
  retry metadata, and cross-release compatibility rebinding;
* the provider-free finalizer first accepts an existing full-lane checkpoint, otherwise
  reconstructs that lane exclusively from the exact shard checkpoints. A missing,
  corrupt, stale, or mismatched shard still fails closed and never causes provider I/O in
  the finalizer.

No market breadth, evidence completeness/freshness rule, screening threshold, CIO
authority, construction rule, execution rule, or paper-only control is changed.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from operations import all_market_lane_certification as _lane
from operations import persistent_certification_scheduler as _scheduler


_SHARD_SCHEMA_VERSION = "hierarchical-certification-shard.v1"
_SHARD_MAX_RECORDS_ENV = "CAPITAL_INTELLIGENCE_CERTIFICATION_SHARD_MAX_RECORDS"
_DEFAULT_SHARD_MAX_RECORDS = 64
_MAX_SHARD_MAX_RECORDS = 512


class _FullLaneCheckpointMissing(RuntimeError):
    """Internal sentinel used only to distinguish a cache miss from cache corruption."""


def _shard_max_records(values: Mapping[str, str]) -> int:
    raw = str(values.get(_SHARD_MAX_RECORDS_ENV) or "").strip()
    if not raw:
        return _DEFAULT_SHARD_MAX_RECORDS
    try:
        requested = int(raw)
    except ValueError as error:
        raise ValueError(f"{_SHARD_MAX_RECORDS_ENV} must be an integer") from error
    if requested < 1 or requested > _MAX_SHARD_MAX_RECORDS:
        raise ValueError(
            f"{_SHARD_MAX_RECORDS_ENV} must be between 1 and {_MAX_SHARD_MAX_RECORDS}"
        )
    return requested


def _metadata_token(value: object) -> str:
    raw = getattr(value, "value", value)
    token = str(raw or "").strip().lower()
    return token or "unknown"


def _partition_key(record: object) -> tuple[str, str, str]:
    provider = "unknown"
    for name in ("provider_kind", "provider", "provider_name", "source_provider"):
        candidate = getattr(record, name, None)
        if candidate not in (None, ""):
            provider = _metadata_token(candidate)
            break

    venue = _metadata_token(getattr(record, "venue", None))

    region = "unknown"
    for name in ("region", "country_code", "country", "market_region"):
        candidate = getattr(record, name, None)
        if candidate not in (None, ""):
            region = _metadata_token(candidate)
            break
    return provider, venue, region


def _partition_records(
    records: Sequence[object],
    *,
    values: Mapping[str, str],
) -> tuple[tuple[tuple[str, str, str], tuple[object, ...]], ...]:
    """Return deterministic bounded shards without dropping or duplicating records."""

    limit = _shard_max_records(values)
    groups: dict[tuple[str, str, str], list[object]] = defaultdict(list)
    for record in records:
        groups[_partition_key(record)].append(record)

    shards: list[tuple[tuple[str, str, str], tuple[object, ...]]] = []
    for key in sorted(groups):
        group = groups[key]
        for offset in range(0, len(group), limit):
            shards.append((key, tuple(group[offset : offset + limit])))

    flattened = tuple(record for _key, shard in shards for record in shard)
    if len(flattened) != len(records):
        raise _scheduler.CertificationSchedulerError(
            "hierarchical certification sharding changed record cardinality"
        )
    if len({id(record) for record in flattened}) != len(flattened):
        # The planner already deduplicates canonical records. Preserve that invariant
        # explicitly so a future partitioning change cannot multiply work silently.
        raise _scheduler.CertificationSchedulerError(
            "hierarchical certification sharding duplicated a record"
        )
    return tuple(shards)


def _shard_fingerprint(
    parent: _scheduler.CertificationNode,
    *,
    partition_key: tuple[str, str, str],
    records: Sequence[object],
    ordinal: int,
) -> str:
    return _scheduler._digest(
        {
            "schema_version": _SHARD_SCHEMA_VERSION,
            "parent_node_id": parent.node_id,
            "parent_input_fingerprint": parent.input_fingerprint,
            "partition_key": list(partition_key),
            "record_fingerprint": _scheduler._record_fingerprint(records),
            "ordinal": int(ordinal),
            "record_count": len(records),
        }
    )


def _sharded_lane_plan(
    original,
    core: Any,
    *,
    catalogs: Mapping[object, Sequence[object]],
    timestamp,
    resolved: object,
    held_symbols: Sequence[str],
    tracked_symbols: Sequence[str],
    excluded_symbols: Sequence[str],
    values: Mapping[str, str],
):
    lane_nodes, records_by_node = original(
        core,
        catalogs=catalogs,
        timestamp=timestamp,
        resolved=resolved,
        held_symbols=held_symbols,
        tracked_symbols=tracked_symbols,
        excluded_symbols=excluded_symbols,
        values=values,
    )

    nodes: list[_scheduler.CertificationNode] = []
    sharded_records: dict[str, tuple[object, ...]] = {}
    for parent in lane_nodes:
        records = tuple(records_by_node[parent.node_id])
        shards = _partition_records(records, values=values)
        if len(shards) <= 1:
            nodes.append(parent)
            sharded_records[parent.node_id] = records
            continue

        if parent.dependencies:
            raise _scheduler.CertificationSchedulerError(
                f"cannot shard dependency-bearing certification node {parent.node_id}"
            )
        for ordinal, (partition_key, shard_records) in enumerate(shards, start=1):
            node_id = f"{parent.node_id}.shard-{ordinal:04d}"
            node = _scheduler.CertificationNode(
                node_id=node_id,
                asset_class=parent.asset_class,
                provider_groups=parent.provider_groups,
                input_fingerprint=_shard_fingerprint(
                    parent,
                    partition_key=partition_key,
                    records=shard_records,
                    ordinal=ordinal,
                ),
                deadline=parent.deadline,
                decision_eligible_count=len(shard_records),
                priority=parent.priority,
                dependencies=(),
            )
            nodes.append(node)
            sharded_records[node_id] = shard_records

    return tuple(nodes), sharded_records


def _strict_shard_checkpoint_market_probe(core: Any, values: Mapping[str, str]):
    """Reconstruct a full lane only from already-qualified exact shard checkpoints."""

    feature_type = core._base._legacy.DiscoveryMarketFeatures

    def full_lane_missing(_records, _epoch, _policy):
        raise _FullLaneCheckpointMissing()

    def missing_shard(records, _epoch, _policy):
        lanes = sorted(
            {
                str(getattr(getattr(record, "asset_class", None), "value", "unknown"))
                for record in records
            }
        )
        raise core._base._legacy.ComprehensiveMarketDiscoveryError(
            "provider-free comprehensive finalizer is missing a qualified shard checkpoint: "
            + ",".join(lanes)
        )

    def probe(records, epoch, policy):
        normalized = tuple(records)
        if not normalized:
            return {}

        # Preserve compatibility with any already-qualified whole-lane checkpoint from a
        # prior run. Integrity/staleness errors propagate; only a genuine cache miss falls
        # through to shard reconstruction.
        try:
            return _lane.checkpointed_market_probe(
                full_lane_missing,
                feature_type,
                normalized,
                epoch,
                policy,
                values=values,
            )
        except _FullLaneCheckpointMissing:
            pass

        shards = _partition_records(normalized, values=values)
        if len(shards) <= 1:
            return _lane.checkpointed_market_probe(
                missing_shard,
                feature_type,
                normalized,
                epoch,
                policy,
                values=values,
            )

        combined: dict[str, object] = {}
        for _partition, shard_records in shards:
            restored = _lane.checkpointed_market_probe(
                missing_shard,
                feature_type,
                shard_records,
                epoch,
                policy,
                values=values,
            )
            if not isinstance(restored, Mapping):
                raise _lane.AllMarketLaneCertificationError(
                    "qualified shard checkpoint returned non-mapping evidence"
                )
            for symbol, feature in restored.items():
                key = str(symbol)
                if key in combined:
                    raise _lane.AllMarketLaneCertificationError(
                        f"qualified shard checkpoints overlap at symbol {key}"
                    )
                combined[key] = feature
        return combined

    return probe


def _install_lane_planner() -> None:
    current = _scheduler._build_lane_nodes
    if getattr(current, "_hierarchical_certification_sharding", False):
        return

    def build_lane_nodes(core: Any, **kwargs):
        return _sharded_lane_plan(current, core, **kwargs)

    build_lane_nodes._hierarchical_certification_sharding = True  # type: ignore[attr-defined]
    _scheduler._build_lane_nodes = build_lane_nodes


def _install_provider_free_reducer() -> None:
    from operations import authoritative_comprehensive_discovery as authoritative

    current = authoritative._strict_checkpoint_market_probe
    if getattr(current, "_hierarchical_certification_sharding", False):
        return

    def strict_checkpoint_market_probe(core: Any, values: Mapping[str, str]):
        return _strict_shard_checkpoint_market_probe(core, values)

    strict_checkpoint_market_probe._hierarchical_certification_sharding = True  # type: ignore[attr-defined]
    authoritative._strict_checkpoint_market_probe = strict_checkpoint_market_probe


def install_hierarchical_certification_sharding() -> None:
    """Install deterministic sub-lane persistence and provider-free shard reduction."""

    _install_lane_planner()
    _install_provider_free_reducer()


__all__ = [
    "install_hierarchical_certification_sharding",
]
