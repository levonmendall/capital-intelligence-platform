"""Spawn-safe, spool-backed authoritative comprehensive-discovery acquisition.

The comprehensive-discovery coordinator retains only compact certification-node metadata.
Catalog assembly and provider preselection run in a disposable builder interpreter that
freezes immutable inputs to an integrity-protected local spool and exits before any lane
worker starts. Each provider-facing lane then loads only its own records in a fresh spawn
interpreter. Frozen catalog/publication inputs are loaded only after every required lane
qualifies, immediately before the existing provider-free canonical finalizer.

This module changes only memory lifetime and operational transport. It does not change
market membership, evidence standards, screening, CIO authority, construction, execution,
or paper-only governance.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from operations import authoritative_comprehensive_discovery as _authoritative
from operations import persistent_certification_scheduler as _scheduler
from operations.comprehensive_discovery_input_spool import (
    ComprehensiveDiscoverySpoolError,
    SpoolReference,
    load_failure,
    load_finalizer_inputs,
    load_lane_inputs,
    load_manifest_for_request,
    manifest_available,
    nodes_from_manifest,
    prepare_request,
)


@dataclass(frozen=True, slots=True)
class SpawnSafeSingleLaneRunner:
    """Picklable child callable that carries no lane records in the parent."""

    manifest_path: str
    node_id: str
    timestamp: datetime
    policy_version: str

    def __call__(self, node: _scheduler.CertificationNode) -> int:
        if node.node_id != self.node_id:
            raise _scheduler.CertificationSchedulerError(
                "spool-backed lane runner node identity changed across spawn boundary"
            )

        # The complete byte stream is size/SHA verified before deserialization. Only this
        # selected lane and the small immutable policy are materialized in the child.
        records, policy, descriptor = load_lane_inputs(
            self.manifest_path,
            node_id=node.node_id,
        )
        if str(descriptor.get("input_fingerprint") or "") != node.input_fingerprint:
            raise _scheduler.CertificationSchedulerError(
                f"spooled certification input fingerprint changed for {node.node_id}"
            )
        if int(descriptor.get("decision_eligible_count", -1)) != node.decision_eligible_count:
            raise _scheduler.CertificationSchedulerError(
                f"spooled certification record count changed for {node.node_id}"
            )

        # Import only the canonical preserved core and install the exact-epoch checkpoint
        # seam in this fresh interpreter. Do not import the service orchestration stack.
        from operations import _comprehensive_market_discovery_v6 as core
        from operations.all_market_lane_certification import install_checkpointed_market_probe
        from operations.certification_work_progress import (
            install_spawn_child_transport_only_progress,
        )
        from operations.certification_work_unit_runner import (
            run_with_canonical_work_progress,
        )

        install_checkpointed_market_probe(core)
        install_spawn_child_transport_only_progress()
        values = os.environ
        release_sha = _scheduler._release(values)
        try:
            features = run_with_canonical_work_progress(
                core.default_redundant_market_probe,
                records=records,
                timestamp=self.timestamp,
                policy=policy,
                asset_class=node.asset_class,
            )
            if not isinstance(features, Mapping):
                raise _scheduler.CertificationSchedulerError(
                    f"{node.node_id} market evidence probe returned a non-mapping"
                )
            return len(features)
        finally:
            # Publish compatibility only after a canonical exact-epoch checkpoint exists;
            # the helper is a no-op when the lane failed before producing one.
            _authoritative._publish_compatible_checkpoint(
                values,
                release_sha=release_sha,
                node=node,
                records=records,
                epoch=self.timestamp,
                policy_version=self.policy_version,
            )


@dataclass(frozen=True, slots=True)
class SpawnSafeLaneRunner:
    """Compact parent-side factory; no deep-record mapping is retained here."""

    manifest_path: str
    timestamp: datetime
    policy_version: str

    def for_node(self, node: _scheduler.CertificationNode) -> SpawnSafeSingleLaneRunner:
        return SpawnSafeSingleLaneRunner(
            manifest_path=self.manifest_path,
            node_id=node.node_id,
            timestamp=self.timestamp,
            policy_version=self.policy_version,
        )

    def __call__(self, node: _scheduler.CertificationNode) -> int:
        # Retained for compatibility with the unpatched scheduler in deterministic tests.
        return self.for_node(node)(node)


def _prepare_spool_process(request_path: Path, values: Mapping[str, str]) -> None:
    if manifest_available(request_path):
        return
    repository_root = Path(__file__).resolve().parents[1]
    process = subprocess.Popen(
        (
            sys.executable,
            "-m",
            "operations.comprehensive_discovery_input_spool",
            "build",
            "--request",
            str(request_path),
        ),
        cwd=str(repository_root),
        env=dict(values),
        # Keep the disposable builder in the comprehensive stage process group so the
        # existing reclaimable-aware outer guard remains the authoritative hard boundary.
        start_new_session=False,
    )
    return_code = int(process.wait())
    if return_code == 0:
        return
    failure = load_failure(request_path)
    if failure is None:
        raise _scheduler.CertificationSchedulerError(
            "comprehensive discovery input spool builder exited without durable failure attribution; "
            f"return_code={return_code}"
        )
    raise _scheduler.CertificationSchedulerError(
        "comprehensive discovery input spool preparation failed; "
        f"stage={failure.get('failure_stage')}; "
        f"failure_type={failure.get('error_type')}; "
        f"detail={failure.get('error_detail')}"
    )


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
    """Acquire every required lane without retaining global deep inputs in the parent."""

    timestamp = core._base._legacy._aware(
        as_of,
        field_name="authoritative_discovery_as_of",
    )
    resolved = policy or core.ComprehensiveMarketDiscoveryPolicy()
    release_sha = _scheduler._release(values)

    request = prepare_request(
        values=values,
        decision_epoch=timestamp,
        held_symbols=held_symbols,
        tracked_symbols=tracked_symbols,
        excluded_symbols=excluded_symbols,
        policy=resolved,
    )
    try:
        _prepare_spool_process(request.path, values)
        manifest_path, spool = load_manifest_for_request(request.path)
        nodes = nodes_from_manifest(spool)
    except (ComprehensiveDiscoverySpoolError, OSError, ValueError) as error:
        raise _scheduler.CertificationSchedulerError(
            f"comprehensive discovery input spool is not ready: {type(error).__name__}: {error}"
        ) from error

    policy_version = str(spool.get("policy_version") or "")
    if policy_version != str(getattr(resolved, "version", "")):
        raise _scheduler.CertificationSchedulerError(
            "comprehensive discovery input spool policy version mismatch"
        )

    scheduler = _scheduler.PersistentCertificationScheduler(
        values=values,
        release_sha=release_sha,
        epoch=timestamp,
        policy_version=policy_version,
    )
    lane_runner = SpawnSafeLaneRunner(
        manifest_path=str(manifest_path),
        timestamp=timestamp,
        policy_version=policy_version,
    )

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

    rebound_count = int(spool.get("compatibility_rebound_count", 0))
    core.record_manual_cio_diagnostic_progress(
        "certification_dag_ready",
        metrics={
            "required_nodes": len(manifest.required_nodes),
            "completed_nodes": len(manifest.completed_nodes),
            "reused_nodes": len(manifest.reused_nodes),
            "compatibility_rebound_nodes": rebound_count,
        },
    )

    # The historical acquisition result is intentionally reused as the integration seam,
    # but the two heavyweight finalizer fields now contain only tiny spool references.
    return _authoritative._AcquisitionResult(
        timestamp=timestamp,
        policy=resolved,
        raw_catalogs=SpoolReference(str(manifest_path), "raw_catalogs"),
        publication=SpoolReference(str(manifest_path), "publication"),
        manifest=manifest,
    )


def _install_spool_aware_finalizer() -> None:
    current = _authoritative._provider_free_finalize
    if getattr(current, "_spool_aware_comprehensive_finalizer", False):
        return

    def provider_free_finalize(core, delegate, acquisition, **kwargs):
        raw_reference = acquisition.raw_catalogs
        publication_reference = acquisition.publication
        if not (
            isinstance(raw_reference, SpoolReference)
            and isinstance(publication_reference, SpoolReference)
            and raw_reference.manifest_path == publication_reference.manifest_path
        ):
            return current(core, delegate, acquisition, **kwargs)
        try:
            raw_catalogs, publication = load_finalizer_inputs(raw_reference.manifest_path)
        except ComprehensiveDiscoverySpoolError as error:
            raise _scheduler.CertificationSchedulerError(
                f"provider-free finalizer inputs are not ready: {error}"
            ) from error
        hydrated = _authoritative._AcquisitionResult(
            timestamp=acquisition.timestamp,
            policy=acquisition.policy,
            raw_catalogs=raw_catalogs,
            publication=publication,
            manifest=acquisition.manifest,
        )
        # This is deliberately the first point at which frozen global finalizer payloads
        # coexist in memory. Every provider-facing lane child has already exited.
        return current(core, delegate, hydrated, **kwargs)

    provider_free_finalize._spool_aware_comprehensive_finalizer = True  # type: ignore[attr-defined]
    if getattr(current, "_comprehensive_discovery_failure_boundary", False):
        provider_free_finalize._comprehensive_discovery_failure_boundary = True  # type: ignore[attr-defined]
    _authoritative._provider_free_finalize = provider_free_finalize


def install_spawn_safe_authoritative_acquisition() -> None:
    """Install spool-backed acquisition and delayed provider-free finalizer hydration."""

    current = _authoritative._acquire
    if not getattr(current, "_spawn_safe_authoritative_acquisition", False):
        spawn_safe_acquire._spawn_safe_authoritative_acquisition = True  # type: ignore[attr-defined]
        _authoritative._acquire = spawn_safe_acquire
    _install_spool_aware_finalizer()


__all__ = [
    "SpawnSafeLaneRunner",
    "SpawnSafeSingleLaneRunner",
    "install_spawn_safe_authoritative_acquisition",
]
