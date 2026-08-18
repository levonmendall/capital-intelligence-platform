"""Two-phase, resumable comprehensive-discovery acquisition and finalization.

The persistent certification DAG is the sole provider-facing acquisition layer for the
canonical evidence-owner path. Once every scheduled lane has qualified, the preserved
comprehensive-discovery core is replayed with frozen catalog/publication inputs and
strict exact-epoch market-evidence checkpoints. That second phase is therefore
provider-free and remains the final terminal-accounting/global-certification authority.

Successful lane evidence may be rebound across application releases only when the
policy, decision epoch, lane, and record fingerprint are identical. The compatibility
cache never relaxes freshness or completeness and cannot itself certify a lane.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from operations import all_market_lane_certification as _lane
from operations import persistent_certification_scheduler as _scheduler


_COMPATIBILITY_SCHEMA = "comprehensive-lane-evidence-compatibility.v1"
_COMPATIBILITY_CONTRACT = "comprehensive-lane-evidence.v1"
_FINALIZER_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class _AcquisitionResult:
    timestamp: datetime
    policy: object
    raw_catalogs: Mapping[object, Sequence[object]]
    publication: object
    manifest: _scheduler.CertificationRunResult


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _compatibility_id(*, policy_version: str) -> str:
    return _digest(
        {
            "schema_version": _COMPATIBILITY_SCHEMA,
            "contract": _COMPATIBILITY_CONTRACT,
            "policy_version": str(policy_version),
            "checkpoint_schema": _lane._CACHE_SCHEMA_VERSION,
        }
    )


def _compatibility_path(
    values: Mapping[str, str],
    *,
    node: _scheduler.CertificationNode,
    epoch: datetime,
    policy_version: str,
) -> Path:
    root = Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "database").expanduser()
    key = _digest(
        {
            "compatibility_id": _compatibility_id(policy_version=policy_version),
            "decision_epoch": epoch.isoformat(),
            "node_id": node.node_id,
            "input_fingerprint": node.input_fingerprint,
        }
    )
    return root / "certification-dag-compatibility" / f"{key}.json"


def _checkpoint_path(
    values: Mapping[str, str],
    *,
    release_sha: str,
    node: _scheduler.CertificationNode,
    records: Sequence[object],
    epoch: datetime,
) -> Path:
    return _lane._checkpoint_path(
        values,
        release_sha=release_sha,
        epoch=epoch,
        lane=node.asset_class,
        record_fingerprint=_lane._record_fingerprint(records),
    )


def _publish_compatible_checkpoint(
    values: Mapping[str, str],
    *,
    release_sha: str,
    node: _scheduler.CertificationNode,
    records: Sequence[object],
    epoch: datetime,
    policy_version: str,
) -> None:
    exact_path = _checkpoint_path(
        values,
        release_sha=release_sha,
        node=node,
        records=records,
        epoch=epoch,
    )
    try:
        exact_payload = json.loads(exact_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return
    body = exact_payload.get("body") if isinstance(exact_payload, Mapping) else None
    if not isinstance(body, Mapping) or exact_payload.get("sha256") != _lane._digest(body):
        return
    record_fingerprint = _lane._record_fingerprint(records)
    expected = {
        "schema_version": _lane._CACHE_SCHEMA_VERSION,
        "release_sha": release_sha,
        "decision_epoch": epoch.isoformat(),
        "lane": node.asset_class,
        "record_fingerprint": record_fingerprint,
    }
    if any(body.get(key) != value for key, value in expected.items()):
        return
    features = body.get("features")
    if not isinstance(features, Mapping):
        return
    compatible_body: dict[str, object] = {
        "schema_version": _COMPATIBILITY_SCHEMA,
        "compatibility_id": _compatibility_id(policy_version=policy_version),
        "decision_epoch": epoch.isoformat(),
        "policy_version": str(policy_version),
        "node_id": node.node_id,
        "lane": node.asset_class,
        "input_fingerprint": node.input_fingerprint,
        "record_fingerprint": record_fingerprint,
        "features": dict(features),
        "paper_only": True,
        "real_money_authorized": False,
    }
    path = _compatibility_path(
        values,
        node=node,
        epoch=epoch,
        policy_version=policy_version,
    )
    _lane._immutable_json(
        path,
        {"body": compatible_body, "sha256": _digest(compatible_body)},
    )


def _rebind_compatible_checkpoint(
    values: Mapping[str, str],
    *,
    release_sha: str,
    node: _scheduler.CertificationNode,
    records: Sequence[object],
    epoch: datetime,
    policy_version: str,
) -> bool:
    exact_path = _checkpoint_path(
        values,
        release_sha=release_sha,
        node=node,
        records=records,
        epoch=epoch,
    )
    if exact_path.exists():
        return False
    compatible_path = _compatibility_path(
        values,
        node=node,
        epoch=epoch,
        policy_version=policy_version,
    )
    try:
        payload = json.loads(compatible_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    body = payload.get("body") if isinstance(payload, Mapping) else None
    if not isinstance(body, Mapping) or payload.get("sha256") != _digest(body):
        return False
    record_fingerprint = _lane._record_fingerprint(records)
    expected = {
        "schema_version": _COMPATIBILITY_SCHEMA,
        "compatibility_id": _compatibility_id(policy_version=policy_version),
        "decision_epoch": epoch.isoformat(),
        "policy_version": str(policy_version),
        "node_id": node.node_id,
        "lane": node.asset_class,
        "input_fingerprint": node.input_fingerprint,
        "record_fingerprint": record_fingerprint,
    }
    if any(body.get(key) != value for key, value in expected.items()):
        return False
    features = body.get("features")
    if not isinstance(features, Mapping):
        return False
    exact_body: dict[str, object] = {
        "schema_version": _lane._CACHE_SCHEMA_VERSION,
        "release_sha": release_sha,
        "decision_epoch": epoch.isoformat(),
        "lane": node.asset_class,
        "record_fingerprint": record_fingerprint,
        "policy_version": str(policy_version),
        "features": dict(features),
        "paper_only": True,
        "real_money_authorized": False,
    }
    _lane._immutable_json(
        exact_path,
        {"body": exact_body, "sha256": _lane._digest(exact_body)},
    )
    return True


def _latest_scheduler_body(
    values: Mapping[str, str],
    *,
    release_sha: str,
    epoch: datetime,
) -> Mapping[str, object] | None:
    path = (
        _scheduler._root(values)
        / _scheduler._SCHEMA_VERSION
        / release_sha
        / _scheduler._epoch_key(epoch)
        / "latest.json"
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    body = payload.get("body") if isinstance(payload, Mapping) else None
    if not isinstance(body, Mapping) or payload.get("sha256") != _scheduler._digest(body):
        return None
    return body


def _failure_detail(
    values: Mapping[str, str],
    *,
    release_sha: str,
    epoch: datetime,
    nodes: Sequence[_scheduler.CertificationNode],
    error: BaseException,
) -> str:
    body = _latest_scheduler_body(values, release_sha=release_sha, epoch=epoch)
    node_by_id = {node.node_id: node for node in nodes}
    failed_nodes: tuple[str, ...] = ()
    completed_count = 0
    reused_count = 0
    node_results: Mapping[str, object] = {}
    if body is not None:
        failed_nodes = tuple(str(item) for item in body.get("failed_nodes", ()) or ())
        completed_count = len(tuple(body.get("completed_nodes", ()) or ()))
        reused_count = len(tuple(body.get("reused_nodes", ()) or ()))
        raw_results = body.get("node_results")
        if isinstance(raw_results, Mapping):
            node_results = raw_results
    if not failed_nodes:
        match = re.search(
            r"(deep-market-evidence:[A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+)",
            str(error),
        )
        if match is not None:
            failed_nodes = (match.group(1),)
    node_id = failed_nodes[0] if failed_nodes else "unknown"
    node = node_by_id.get(node_id)
    raw_result = node_results.get(node_id)
    result = raw_result if isinstance(raw_result, Mapping) else {}
    failure_type = str(result.get("failure_type") or type(error).__name__)
    retry_after = str(result.get("retry_after") or "none")
    asset_class = node.asset_class if node is not None else "unknown"
    decision_count = node.decision_eligible_count if node is not None else -1
    return (
        "comprehensive discovery lane acquisition failed; "
        f"node={node_id}; asset_class={asset_class}; failure_type={failure_type}; "
        f"decision_eligible_count={decision_count}; completed_nodes={completed_count}; "
        f"required_nodes={len(nodes)}; reused_nodes={reused_count}; retry_after={retry_after}"
    )


def _strict_checkpoint_market_probe(core: Any, values: Mapping[str, str]):
    feature_type = core._base._legacy.DiscoveryMarketFeatures

    def missing_provider_call(records, epoch, policy):
        del epoch, policy
        lanes = sorted(
            {
                str(getattr(getattr(record, "asset_class", None), "value", "unknown"))
                for record in records
            }
        )
        raise core._base._legacy.ComprehensiveMarketDiscoveryError(
            "provider-free comprehensive finalizer is missing a qualified lane checkpoint: "
            + ",".join(lanes)
        )

    def probe(records, epoch, policy):
        return _lane.checkpointed_market_probe(
            missing_provider_call,
            feature_type,
            records,
            epoch,
            policy,
            values=values,
        )

    return probe


def _acquire(
    core: Any,
    *,
    as_of: datetime,
    held_symbols: Sequence[str],
    tracked_symbols: Sequence[str],
    excluded_symbols: Sequence[str],
    policy: object | None,
    values: Mapping[str, str],
) -> _AcquisitionResult:
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
        if _rebind_compatible_checkpoint(
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

    def run_node(node: _scheduler.CertificationNode) -> int:
        records = deep_records[node.node_id]
        core.record_manual_cio_diagnostic_progress(
            f"certification_dag:{node.asset_class}",
            metrics={
                "decision_eligible_records": len(records),
                "provider_budget_count": len(node.provider_groups),
            },
        )
        features = core.default_redundant_market_probe(records, timestamp, resolved)
        if not isinstance(features, Mapping):
            raise _scheduler.CertificationSchedulerError(
                f"{node.node_id} market evidence probe returned a non-mapping"
            )
        core.record_manual_cio_diagnostic_progress(
            f"certification_dag_complete:{node.asset_class}",
            metrics={
                "decision_eligible_records": len(records),
                "evidence_complete_records": len(features),
            },
        )
        return len(features)

    manifest: _scheduler.CertificationRunResult | None = None
    try:
        manifest = scheduler.run(nodes, run_node)
    except _scheduler.CertificationSchedulerError as error:
        raise _scheduler.CertificationSchedulerError(
            _failure_detail(
                values,
                release_sha=release_sha,
                epoch=timestamp,
                nodes=nodes,
                error=error,
            )
        ) from error
    finally:
        for node in nodes:
            _publish_compatible_checkpoint(
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
    return _AcquisitionResult(
        timestamp=timestamp,
        policy=resolved,
        raw_catalogs=raw_catalogs,
        publication=publication,
        manifest=manifest,
    )


def _provider_free_finalize(
    core: Any,
    delegate,
    acquisition: _AcquisitionResult,
    *,
    as_of: datetime,
    held_symbols: Sequence[str],
    tracked_symbols: Sequence[str],
    excluded_symbols: Sequence[str],
    prior_cutoff_observations: Sequence[object],
    policy: object | None,
    values: Mapping[str, str],
):
    strict_market_probe = _strict_checkpoint_market_probe(core, values)
    original_catalog_probe = core._base.default_catalog_probe
    original_market_probe = core.default_redundant_market_probe
    original_publication = core.ensure_provider_preselection_publication

    def frozen_catalog_probe(timestamp, *, policy=None):
        del policy
        observed = core._base._legacy._aware(
            timestamp,
            field_name="provider_free_catalog_cutoff",
        )
        if observed != acquisition.timestamp:
            raise core._base._legacy.ComprehensiveMarketDiscoveryError(
                "provider-free comprehensive finalizer catalog epoch changed"
            )
        return acquisition.raw_catalogs

    def frozen_publication(catalogs, *, as_of, policy=None, **kwargs):
        del policy, kwargs
        observed = core._base._legacy._aware(
            as_of,
            field_name="provider_free_publication_cutoff",
        )
        if observed != acquisition.timestamp:
            raise core.ProviderPreselectionPublicationError(
                "provider-free comprehensive finalizer publication epoch changed"
            )
        catalog_count = sum(
            len(items) for items in catalogs.values() if isinstance(items, Sequence)
        )
        expected_count = int(getattr(acquisition.publication, "catalog_count", -1))
        if expected_count >= 0 and catalog_count != expected_count:
            raise core.ProviderPreselectionPublicationError(
                "provider-free comprehensive finalizer catalog boundary changed"
            )
        return acquisition.publication

    core.record_manual_cio_diagnostic_progress(
        "comprehensive_discovery_provider_free_finalizer",
        metrics={
            "required_nodes": len(acquisition.manifest.required_nodes),
            "completed_nodes": len(acquisition.manifest.completed_nodes),
            "reused_nodes": len(acquisition.manifest.reused_nodes),
        },
    )
    with _FINALIZER_LOCK:
        core._base.default_catalog_probe = frozen_catalog_probe
        core.default_redundant_market_probe = strict_market_probe
        core.ensure_provider_preselection_publication = frozen_publication
        try:
            result = delegate(
                as_of=as_of,
                held_symbols=held_symbols,
                tracked_symbols=tracked_symbols,
                excluded_symbols=excluded_symbols,
                catalog_probe=None,
                market_probe=None,
                preselection_probe=None,
                prior_cutoff_observations=prior_cutoff_observations,
                policy=policy,
            )
        finally:
            core._base.default_catalog_probe = original_catalog_probe
            core.default_redundant_market_probe = original_market_probe
            core.ensure_provider_preselection_publication = original_publication
    core.record_manual_cio_diagnostic_progress(
        "comprehensive_discovery_provider_free_finalizer_complete"
    )
    return result


def install_authoritative_certification_scheduler(core: Any) -> None:
    """Make the persistent DAG authoritative for canonical provider acquisition."""

    if getattr(core, "_authoritative_certification_scheduler_installed", False):
        return
    delegate = core.discover_comprehensive_markets

    def discover_comprehensive_markets(
        *,
        as_of,
        held_symbols=(),
        tracked_symbols=(),
        excluded_symbols=(),
        catalog_probe=None,
        market_probe=None,
        preselection_probe=None,
        prior_cutoff_observations=(),
        policy=None,
    ):
        canonical = (
            catalog_probe is None
            and market_probe is None
            and preselection_probe is None
            and not tuple(prior_cutoff_observations)
        )
        values = os.environ
        if not canonical or not _scheduler._enabled(values):
            return delegate(
                as_of=as_of,
                held_symbols=held_symbols,
                tracked_symbols=tracked_symbols,
                excluded_symbols=excluded_symbols,
                catalog_probe=catalog_probe,
                market_probe=market_probe,
                preselection_probe=preselection_probe,
                prior_cutoff_observations=prior_cutoff_observations,
                policy=policy,
            )

        try:
            acquisition = _acquire(
                core,
                as_of=as_of,
                held_symbols=held_symbols,
                tracked_symbols=tracked_symbols,
                excluded_symbols=excluded_symbols,
                policy=policy,
                values=values,
            )
        except _scheduler.CertificationSchedulerError as error:
            raise core._base._legacy.ComprehensiveMarketDiscoveryError(
                f"persistent certification DAG is not ready: {error}"
            ) from error

        return _provider_free_finalize(
            core,
            delegate,
            acquisition,
            as_of=as_of,
            held_symbols=held_symbols,
            tracked_symbols=tracked_symbols,
            excluded_symbols=excluded_symbols,
            prior_cutoff_observations=prior_cutoff_observations,
            policy=policy,
            values=values,
        )

    core.discover_comprehensive_markets = discover_comprehensive_markets
    core._authoritative_certification_scheduler_installed = True


__all__ = ["install_authoritative_certification_scheduler"]
