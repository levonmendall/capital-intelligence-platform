"""Process-isolated, spool-backed authoritative comprehensive-discovery acquisition.

The comprehensive-discovery coordinator retains only compact certification-node metadata.
Catalog assembly, provider preselection, and lane descriptor construction run in finite
bounded-memory interpreters. Provider-facing market-evidence lanes are then executed one at
a time in genuinely fresh Python interpreters. Frozen catalog/publication inputs are loaded
only after every required lane qualifies, immediately before the existing provider-free
canonical finalizer.

The earlier spawn-safe implementation correctly bounded spool construction, but its lane
runner was submitted through ``PersistentCertificationScheduler``'s ThreadPoolExecutor and
performed the heavyweight provider probe directly in that scheduler thread. With the
scheduler's default worker count, several complete market lanes could therefore coexist in
one Python process even though the class described a fresh-interpreter boundary. This
module makes that boundary real: the scheduler retains only compact node metadata, launches
one finite lane subprocess at a time, and receives only a tiny integrity-protected result.
Provider-level I/O inside the lane remains governed by the existing provider budgets.

This changes only memory lifetime and operational transport. It does not change market
membership, evidence standards, screening, CIO authority, construction, execution, or
paper-only governance.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from operations import authoritative_comprehensive_discovery as _authoritative
from operations import comprehensive_discovery_input_spool as _spool
from operations import persistent_certification_scheduler as _scheduler
from operations import supervised_component_execution as _supervision
from operations.bounded_comprehensive_discovery_spool import build_spool, load_finalizer_inputs
from operations.comprehensive_discovery_input_spool import (
    ComprehensiveDiscoverySpoolError,
    SpoolReference,
    load_failure,
    load_lane_inputs,
    load_manifest_for_request,
    manifest_available,
    nodes_from_manifest,
    prepare_request,
)


_MODULE = "operations.spawn_safe_authoritative_acquisition"
_LANE_RESULT_SCHEMA = "spawn-safe-certification-lane-result.v1"
_LANE_FAILURE_SCHEMA = "spawn-safe-certification-lane-failure.v1"
_SERIAL_LANE_WORKERS_ENV = "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS"
_SAFE_FAILURE_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,119}$")


def _lane_result_path(manifest_path: str | Path, node_id: str) -> Path:
    directory = Path(manifest_path).expanduser().parent
    return directory / f"lane-result-{_spool._safe_release(node_id)}.json"


def _lane_failure_path(manifest_path: str | Path, node_id: str) -> Path:
    directory = Path(manifest_path).expanduser().parent
    return directory / f"lane-failure-{_spool._safe_release(node_id)}.json"


def _unlink_if_present(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _retry_after_seconds(error: BaseException) -> float | None:
    raw = getattr(error, "retry_after_seconds", None)
    try:
        retry = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
    if retry is None or not math.isfinite(retry) or retry <= 0.0:
        return None
    return min(retry, 3600.0)


def _direct_cause(error: BaseException) -> BaseException | None:
    if error.__cause__ is not None:
        return error.__cause__
    if not error.__suppress_context__ and error.__context__ is not None:
        return error.__context__
    return None


def _safe_failure_type(value: object, *, fallback: str) -> str:
    name = str(value or "").strip()
    if _SAFE_FAILURE_TYPE.fullmatch(name) is None:
        return fallback
    return name


def _write_lane_failure(
    manifest_path: str | Path,
    *,
    node: _scheduler.CertificationNode,
    timestamp: datetime,
    policy_version: str,
    error: BaseException,
) -> Path:
    """Persist bounded credential-safe child failure truth before the process exits."""

    cause = _direct_cause(error)
    body: dict[str, object] = {
        "schema_version": _LANE_FAILURE_SCHEMA,
        "node_id": node.node_id,
        "asset_class": node.asset_class,
        "input_fingerprint": node.input_fingerprint,
        "decision_epoch": timestamp.isoformat(),
        "policy_version": str(policy_version),
        "decision_eligible_count": int(node.decision_eligible_count),
        "provider_groups": list(node.provider_groups),
        "error_type": _safe_failure_type(
            type(error).__name__, fallback="RemoteLaneExecutionError"
        ),
        "error_detail": _supervision._safe_error(error),
        "cause_type": (
            _safe_failure_type(type(cause).__name__, fallback="RemoteLaneCauseError")
            if cause is not None
            else None
        ),
        "cause_detail": _supervision._safe_error(cause) if cause is not None else None,
        "retry_after_seconds": _retry_after_seconds(error),
        **_spool._authority_fields(),
    }
    path = _lane_failure_path(manifest_path, node.node_id)
    _spool._atomic_json(path, body)
    return path


def _load_lane_failure(
    manifest_path: str | Path,
    *,
    node: _scheduler.CertificationNode,
    timestamp: datetime,
    policy_version: str,
    return_code: int,
    pid: object,
) -> BaseException:
    """Reconstruct exact safe child failure instead of collapsing it to exit code 2."""

    body = _spool._load_json(
        _lane_failure_path(manifest_path, node.node_id),
        schema=_LANE_FAILURE_SCHEMA,
    )
    if str(body.get("node_id") or "") != node.node_id:
        raise _scheduler.CertificationSchedulerError(
            f"lane subprocess failure node identity changed for {node.node_id}"
        )
    if str(body.get("asset_class") or "") != node.asset_class:
        raise _scheduler.CertificationSchedulerError(
            f"lane subprocess failure asset class changed for {node.node_id}"
        )
    if str(body.get("input_fingerprint") or "") != node.input_fingerprint:
        raise _scheduler.CertificationSchedulerError(
            f"lane subprocess failure fingerprint changed for {node.node_id}"
        )
    if str(body.get("decision_epoch") or "") != timestamp.isoformat():
        raise _scheduler.CertificationSchedulerError(
            f"lane subprocess failure decision epoch changed for {node.node_id}"
        )
    if str(body.get("policy_version") or "") != str(policy_version):
        raise _scheduler.CertificationSchedulerError(
            f"lane subprocess failure policy version changed for {node.node_id}"
        )

    failure_type = _safe_failure_type(
        body.get("error_type"), fallback="RemoteLaneExecutionError"
    )
    detail = str(body.get("error_detail") or "provider-facing certification lane failed")
    error_type = type(failure_type, (RuntimeError,), {})
    error = error_type(
        f"{detail}; subprocess_return_code={int(return_code)}; subprocess_pid={pid}"
    )

    retry = body.get("retry_after_seconds")
    try:
        retry_seconds = float(retry) if retry is not None else None
    except (TypeError, ValueError):
        retry_seconds = None
    if retry_seconds is not None and math.isfinite(retry_seconds) and retry_seconds > 0.0:
        setattr(error, "retry_after_seconds", min(retry_seconds, 3600.0))

    cause_type_name = str(body.get("cause_type") or "").strip()
    cause_detail = str(body.get("cause_detail") or "").strip()
    if cause_type_name or cause_detail:
        cause_type_name = _safe_failure_type(
            cause_type_name, fallback="RemoteLaneCauseError"
        )
        cause_type = type(cause_type_name, (RuntimeError,), {})
        error.__cause__ = cause_type(cause_detail or "provider-facing lane cause unavailable")
    return error


def _write_lane_result(
    manifest_path: str | Path,
    *,
    node: _scheduler.CertificationNode,
    evidence_complete_count: int,
) -> Path:
    body: dict[str, object] = {
        "schema_version": _LANE_RESULT_SCHEMA,
        "node_id": node.node_id,
        "input_fingerprint": node.input_fingerprint,
        "evidence_complete_count": int(evidence_complete_count),
        **_spool._authority_fields(),
    }
    path = _lane_result_path(manifest_path, node.node_id)
    _spool._atomic_json(path, body)
    return path


def _load_lane_result(
    manifest_path: str | Path,
    *,
    node: _scheduler.CertificationNode,
) -> int:
    body = _spool._load_json(
        _lane_result_path(manifest_path, node.node_id),
        schema=_LANE_RESULT_SCHEMA,
    )
    if str(body.get("node_id") or "") != node.node_id:
        raise _scheduler.CertificationSchedulerError(
            f"lane subprocess result node identity changed for {node.node_id}"
        )
    if str(body.get("input_fingerprint") or "") != node.input_fingerprint:
        raise _scheduler.CertificationSchedulerError(
            f"lane subprocess result fingerprint changed for {node.node_id}"
        )
    try:
        count = int(body.get("evidence_complete_count", -1))
    except (TypeError, ValueError) as error:
        raise _scheduler.CertificationSchedulerError(
            f"lane subprocess result count is malformed for {node.node_id}"
        ) from error
    if count < 0:
        raise _scheduler.CertificationSchedulerError(
            f"lane subprocess result count is invalid for {node.node_id}"
        )
    return count


def _execute_lane_in_current_process(
    *,
    manifest_path: str,
    node: _scheduler.CertificationNode,
    timestamp: datetime,
    policy_version: str,
) -> int:
    """Execute one lane inside the finite child interpreter only."""

    records, policy, descriptor = load_lane_inputs(
        manifest_path,
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

    # Import only the canonical preserved core and exact-epoch checkpoint seams in this
    # finite child. The long-lived serving process and scheduler never import or retain
    # the provider-facing lane's complete record/evidence graph.
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
            timestamp=timestamp,
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
            epoch=timestamp,
            policy_version=policy_version,
        )


@dataclass(frozen=True, slots=True)
class SpawnSafeSingleLaneRunner:
    """Compact parent callable that launches one finite provider-facing interpreter."""

    manifest_path: str
    node_id: str
    timestamp: datetime
    policy_version: str
    environment: tuple[tuple[str, str], ...] = ()

    def __call__(self, node: _scheduler.CertificationNode) -> int:
        if node.node_id != self.node_id:
            raise _scheduler.CertificationSchedulerError(
                "spool-backed lane runner node identity changed across process boundary"
            )

        result_path = _lane_result_path(self.manifest_path, node.node_id)
        failure_path = _lane_failure_path(self.manifest_path, node.node_id)
        _unlink_if_present(result_path)
        _unlink_if_present(failure_path)

        repository_root = Path(__file__).resolve().parents[1]
        command = (
            sys.executable,
            "-m",
            _MODULE,
            "run-lane",
            "--manifest",
            self.manifest_path,
            "--node-id",
            node.node_id,
            "--timestamp",
            self.timestamp.isoformat(),
            "--policy-version",
            self.policy_version,
        )
        environment = dict(os.environ)
        environment.update(dict(self.environment))
        process = subprocess.Popen(
            command,
            cwd=str(repository_root),
            env=environment,
            # Remain in the outer diagnostic process group so its resource/timeout
            # supervisor can fail closed across the complete process tree.
            start_new_session=False,
        )
        return_code = int(process.wait())
        if return_code != 0:
            try:
                error = _load_lane_failure(
                    self.manifest_path,
                    node=node,
                    timestamp=self.timestamp,
                    policy_version=self.policy_version,
                    return_code=return_code,
                    pid=getattr(process, "pid", "unknown"),
                )
            except (ComprehensiveDiscoverySpoolError, OSError, ValueError) as failure_error:
                raise _scheduler.CertificationSchedulerError(
                    f"provider-facing certification lane subprocess failed without durable "
                    f"failure attribution for {node.node_id}; return_code={return_code}; "
                    f"pid={getattr(process, 'pid', 'unknown')}; "
                    f"failure_record_error={type(failure_error).__name__}: {failure_error}"
                ) from failure_error
            raise error
        try:
            return _load_lane_result(self.manifest_path, node=node)
        except (ComprehensiveDiscoverySpoolError, OSError, ValueError) as error:
            raise _scheduler.CertificationSchedulerError(
                f"provider-facing certification lane subprocess produced no valid result "
                f"for {node.node_id}: {error}"
            ) from error


@dataclass(frozen=True, slots=True)
class SpawnSafeLaneRunner:
    """Compact parent-side factory; no deep-record mapping is retained here."""

    manifest_path: str
    timestamp: datetime
    policy_version: str
    environment: tuple[tuple[str, str], ...] = ()

    def for_node(self, node: _scheduler.CertificationNode) -> SpawnSafeSingleLaneRunner:
        return SpawnSafeSingleLaneRunner(
            manifest_path=self.manifest_path,
            node_id=node.node_id,
            timestamp=self.timestamp,
            policy_version=self.policy_version,
            environment=self.environment,
        )

    def __call__(self, node: _scheduler.CertificationNode) -> int:
        return self.for_node(node)(node)


def _prepare_spool_process(request_path: Path, values: Mapping[str, str]) -> None:
    """Build the spool without a redundant nested coordinator interpreter."""

    if manifest_available(request_path):
        return
    try:
        # ``build_spool`` is itself only a compact coordinator. Every heavyweight catalog,
        # publication, and lane materialization step still runs in its own finite child via
        # bounded_comprehensive_discovery_spool._run_stage. Calling it here removes only the
        # extra long-lived build interpreter that previously overlapped each finite child.
        build_spool(request_path, values=values)
    except (ComprehensiveDiscoverySpoolError, OSError, ValueError) as error:
        failure = load_failure(request_path)
        if failure is None:
            raise _scheduler.CertificationSchedulerError(
                "comprehensive discovery input spool builder failed without durable failure attribution; "
                f"error_type={type(error).__name__}; detail={error}"
            ) from error
        raise _scheduler.CertificationSchedulerError(
            "comprehensive discovery input spool preparation failed; "
            f"stage={failure.get('failure_stage')}; "
            f"failure_type={failure.get('error_type')}; "
            f"detail={failure.get('error_detail')}"
        ) from error


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

    # A provider-facing lane now owns a complete finite child interpreter. Running several
    # such children concurrently would reintroduce the exact cgroup overlap this boundary
    # is intended to remove. Keep lane processes serial; provider I/O remains independently
    # concurrent/budgeted inside each lane and the full market universe is unchanged.
    scheduler_values = dict(values)
    scheduler_values[_SERIAL_LANE_WORKERS_ENV] = "1"
    scheduler = _scheduler.PersistentCertificationScheduler(
        values=scheduler_values,
        release_sha=release_sha,
        epoch=timestamp,
        policy_version=policy_version,
    )
    lane_runner = SpawnSafeLaneRunner(
        manifest_path=str(manifest_path),
        timestamp=timestamp,
        policy_version=policy_version,
        environment=tuple(sorted((str(key), str(value)) for key, value in values.items())),
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
    # but the two heavyweight finalizer fields contain only tiny spool references.
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


def _run_lane_cli(
    *,
    manifest_path: str,
    node_id: str,
    timestamp: datetime,
    policy_version: str,
) -> int:
    manifest = _spool.load_manifest(manifest_path)
    node = next((item for item in nodes_from_manifest(manifest) if item.node_id == node_id), None)
    if node is None:
        raise _scheduler.CertificationSchedulerError(
            f"spool manifest has no certification node for {node_id}"
        )
    count = _execute_lane_in_current_process(
        manifest_path=manifest_path,
        node=node,
        timestamp=timestamp,
        policy_version=policy_version,
    )
    _unlink_if_present(_lane_failure_path(manifest_path, node.node_id))
    _write_lane_result(
        manifest_path,
        node=node,
        evidence_complete_count=count,
    )
    return count


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run-lane",))
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--timestamp", required=True)
    parser.add_argument("--policy-version", required=True)
    args = parser.parse_args(argv)
    timestamp: datetime | None = None
    try:
        timestamp = datetime.fromisoformat(str(args.timestamp).replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("lane timestamp must be timezone-aware")
        count = _run_lane_cli(
            manifest_path=args.manifest,
            node_id=args.node_id,
            timestamp=timestamp,
            policy_version=args.policy_version,
        )
    except BaseException as error:  # noqa: BLE001 - child boundary must fail closed.
        failure_recorded = False
        if timestamp is not None:
            try:
                manifest = _spool.load_manifest(args.manifest)
                node = next(
                    (item for item in nodes_from_manifest(manifest) if item.node_id == args.node_id),
                    None,
                )
                if node is not None:
                    _write_lane_failure(
                        args.manifest,
                        node=node,
                        timestamp=timestamp,
                        policy_version=args.policy_version,
                        error=error,
                    )
                    failure_recorded = True
            except BaseException:  # noqa: BLE001 - stderr remains secondary fail-closed truth.
                failure_recorded = False
        print(
            json.dumps(
                {
                    "event": "spawn_safe_certification_lane_failed",
                    "node_id": args.node_id,
                    "error_type": type(error).__name__,
                    "error_detail": _supervision._safe_error(error),
                    "failure_recorded": failure_recorded,
                    "credential_safe": True,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 2
    print(
        json.dumps(
            {
                "event": "spawn_safe_certification_lane_complete",
                "node_id": args.node_id,
                "evidence_complete_count": count,
                "credential_safe": True,
                "paper_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "SpawnSafeLaneRunner",
    "SpawnSafeSingleLaneRunner",
    "install_spawn_safe_authoritative_acquisition",
]
