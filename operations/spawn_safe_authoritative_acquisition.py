"""Spawn-safe authoritative comprehensive-discovery acquisition.

The parent process owns catalog/preselection orchestration, provider leases, durable node
state, and diagnostic progress.  Each provider-facing lane child receives only its lane
records, exact decision epoch, and immutable policy object.  The child imports the
canonical market probe in a fresh interpreter so it never inherits Render thread locks,
HTTP pools, or other process state from the long-running service.

This module does not change market membership, evidence standards, screening, CIO
authority, construction, execution, or paper-only governance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from operations import authoritative_comprehensive_discovery as _authoritative
from operations import persistent_certification_scheduler as _scheduler


@dataclass(frozen=True, slots=True)
class SpawnSafeSingleLaneRunner:
    """Picklable callable containing exactly one lane's governed inputs."""

    records: tuple[object, ...]
    timestamp: datetime
    policy: object

    def __call__(self, node: _scheduler.CertificationNode) -> int:
        # Import only the canonical preserved core and install the exact-epoch checkpoint
        # seam in this fresh interpreter.  Do not import the service orchestration stack.
        from operations import _comprehensive_market_discovery_v6 as core
        from operations.all_market_lane_certification import install_checkpointed_market_probe

        install_checkpointed_market_probe(core)
        features = core.default_redundant_market_probe(
            self.records,
            self.timestamp,
            self.policy,
        )
        if not isinstance(features, Mapping):
            raise _scheduler.CertificationSchedulerError(
                f"{node.node_id} market evidence probe returned a non-mapping"
            )
        return len(features)


@dataclass(frozen=True, slots=True)
class SpawnSafeLaneRunner:
    """Parent-side runner factory that serializes only the selected lane to a child."""

    deep_records: Mapping[str, Sequence[object]]
    timestamp: datetime
    policy: object

    def for_node(self, node: _scheduler.CertificationNode) -> SpawnSafeSingleLaneRunner:
        records = self.deep_records.get(node.node_id)
        if records is None:
            raise _scheduler.CertificationSchedulerError(
                f"spawn-safe certification runner has no records for {node.node_id}"
            )
        return SpawnSafeSingleLaneRunner(
            records=tuple(records),
            timestamp=self.timestamp,
            policy=self.policy,
        )

    def __call__(self, node: _scheduler.CertificationNode) -> int:
        # Retained for compatibility with the unpatched scheduler in deterministic tests.
        return self.for_node(node)(node)


def spawn_safe_acquire(
    core: Any,
    *,
    as_of: datetime,
    held_symbols: Sequence[str],
    tracked_symbols: Sequence[str],
    excluded_symbols: Sequence[str],
    policy: object | None,
    values: Mapping[str, str],
):
    """Mirror authoritative acquisition while providing a spawn-safe lane runner."""

    timestamp = core._base._legacy._aware(
        as_of,
        field_name="authoritative_discovery_as_of",
    )
    resolved = policy or core.ComprehensiveMarketDiscoveryPolicy()
    release_sha = _scheduler._release(values)

    core.record_manual_cio_diagnostic_progress("certification_dag_catalog_dependency")
    raw_catalogs = core._base.default_catalog_probe(timestamp, policy=resolved)
    catalogs = core._base._merge_certified_catalog(raw_catalogs, as_of=timestamp)
    if not isinstance(raw_catalogs, Mapping) or not isinstance(catalogs, Mapping):
        raise _scheduler.CertificationSchedulerError(
            "certification DAG catalog dependency is not a mapping"
        )
    core.record_manual_cio_diagnostic_progress(
        "certification_dag_catalog_dependency_complete",
        metrics={
            "catalog_records": sum(
                len(items) for items in catalogs.values() if isinstance(items, Sequence)
            )
        },
    )

    core.record_manual_cio_diagnostic_progress(
        "certification_dag_provider_factor_dependency"
    )
    try:
        publication = core.ensure_provider_preselection_publication(
            catalogs,
            as_of=timestamp,
            policy=resolved,
            market_probe=core.default_provider_preselection_market_probe,
        )
    except core.ProviderPreselectionPublicationError as error:
        raise _scheduler.CertificationSchedulerError(str(error)) from error
    core.record_manual_cio_diagnostic_progress(
        "certification_dag_provider_factor_dependency_complete"
    )

    nodes, deep_records = _scheduler._build_lane_nodes(
        core,
        catalogs=catalogs,
        timestamp=timestamp,
        resolved=resolved,
        held_symbols=held_symbols,
        tracked_symbols=tracked_symbols,
        excluded_symbols=excluded_symbols,
        values=values,
    )
    if not nodes:
        raise _scheduler.CertificationSchedulerError(
            "certification DAG found no scheduled comprehensive-discovery lanes"
        )

    policy_version = str(getattr(resolved, "version", ""))
    rebound_count = 0
    for node in nodes:
        if _authoritative._rebind_compatible_checkpoint(
            values,
            release_sha=release_sha,
            node=node,
            records=deep_records[node.node_id],
            epoch=timestamp,
            policy_version=policy_version,
        ):
            rebound_count += 1
    if rebound_count:
        core.record_manual_cio_diagnostic_progress(
            "certification_dag_compatibility_rebind",
            metrics={"rebound_nodes": rebound_count},
        )

    scheduler = _scheduler.PersistentCertificationScheduler(
        values=values,
        release_sha=release_sha,
        epoch=timestamp,
        policy_version=policy_version,
    )
    lane_runner = SpawnSafeLaneRunner(
        deep_records=deep_records,
        timestamp=timestamp,
        policy=resolved,
    )

    manifest: _scheduler.CertificationRunResult | None = None
    try:
        manifest = scheduler.run(nodes, lane_runner)
    except _scheduler.CertificationSchedulerError as error:
        raise _scheduler.CertificationSchedulerError(
            _authoritative._failure_detail(
                values,
                release_sha=release_sha,
                epoch=timestamp,
                nodes=nodes,
                error=error,
            )
        ) from error
    finally:
        for node in nodes:
            _authoritative._publish_compatible_checkpoint(
                values,
                release_sha=release_sha,
                node=node,
                records=deep_records[node.node_id],
                epoch=timestamp,
                policy_version=policy_version,
            )

    assert manifest is not None
    core.record_manual_cio_diagnostic_progress(
        "certification_dag_ready",
        metrics={
            "required_nodes": len(manifest.required_nodes),
            "completed_nodes": len(manifest.completed_nodes),
            "reused_nodes": len(manifest.reused_nodes),
            "compatibility_rebound_nodes": rebound_count,
        },
    )
    return _authoritative._AcquisitionResult(
        timestamp=timestamp,
        policy=resolved,
        raw_catalogs=raw_catalogs,
        publication=publication,
        manifest=manifest,
    )


def install_spawn_safe_authoritative_acquisition() -> None:
    """Replace only the provider-facing acquisition function with spawn-safe orchestration."""

    current = _authoritative._acquire
    if getattr(current, "_spawn_safe_authoritative_acquisition", False):
        return
    spawn_safe_acquire._spawn_safe_authoritative_acquisition = True  # type: ignore[attr-defined]
    _authoritative._acquire = spawn_safe_acquire


__all__ = [
    "SpawnSafeLaneRunner",
    "SpawnSafeSingleLaneRunner",
    "install_spawn_safe_authoritative_acquisition",
]
