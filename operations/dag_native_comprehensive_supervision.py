"""Make comprehensive-discovery supervision match the persistent certification DAG.

The comprehensive-discovery coordinator is resumable state-machine orchestration, not one
provider call. The parent process owns scheduling, provider leases, durable state, and
credential-safe progress. Provider-facing lanes run in fresh ``spawn`` interpreters so
they cannot inherit service thread locks, HTTP pools, logging locks, or other unsafe
state from the long-running Render process.

The canonical catalog, preselection, market-evidence, terminal-accounting, global
certification, CIO, construction, execution, and paper-only rules are untouched. A global
discovery result still exists only after every required DAG node qualifies and the
provider-free finalizer succeeds.
"""

from __future__ import annotations

import math
import multiprocessing
import os
import pickle
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from multiprocessing.connection import Connection
from typing import Callable, Mapping, Sequence

from operations import supervised_component_execution as _supervision
from operations.comprehensive_descendant_reaper import process_start_ticks


_NODE_TIMEOUT_ENV = "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_NODE_TIMEOUT_SECONDS"
_DEFAULT_NODE_TIMEOUT_SECONDS = 540.0
_MAX_NODE_TIMEOUT_SECONDS = 3600.0
_POLL_INTERVAL_SECONDS = 0.02
_RUNTIME_JOURNAL_SCHEMA = "persistent-certification-runtime.v1"
_SAFE_FAILURE_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,119}$")


class SpawnSerializationError(RuntimeError):
    """Raised when a governed lane input cannot cross the clean spawn boundary."""


@dataclass(slots=True)
class _RunningNode:
    node: object
    lease: tuple[str, ...]
    connection: Connection
    process: multiprocessing.Process
    launched_at: float
    process_start_ticks: int | None = None
    ready_at: float | None = None
    process_group_ready: bool = False


def _node_timeout_seconds(values: Mapping[str, str]) -> float:
    raw = str(values.get(_NODE_TIMEOUT_ENV) or "").strip()
    if not raw:
        return _DEFAULT_NODE_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError as error:
        raise ValueError(f"{_NODE_TIMEOUT_ENV} must be numeric") from error
    if (
        not math.isfinite(timeout)
        or timeout <= 0.0
        or timeout > _MAX_NODE_TIMEOUT_SECONDS
    ):
        raise ValueError(
            f"{_NODE_TIMEOUT_ENV} must be positive and no more than "
            f"{_MAX_NODE_TIMEOUT_SECONDS:g}"
        )
    return timeout


def _node_worker(
    connection: Connection,
    runner: Callable[[object], int],
    node: object,
) -> None:
    """Run one lane in a fresh interpreter and return only bounded metadata."""

    process_group_ready = False
    try:
        if os.name == "posix":
            os.setsid()
            process_group_ready = True
        connection.send(("ready", process_group_ready))
        try:
            result = int(runner(node))
        except BaseException as error:  # noqa: BLE001 - child reports provider failure.
            retry_after = getattr(error, "retry_after_seconds", None)
            try:
                retry_seconds = float(retry_after) if retry_after is not None else None
            except (TypeError, ValueError):
                retry_seconds = None
            if retry_seconds is not None and (
                not math.isfinite(retry_seconds) or retry_seconds <= 0.0
            ):
                retry_seconds = None
            connection.send(
                (
                    "error",
                    type(error).__name__,
                    _supervision._safe_error(error),
                    retry_seconds,
                )
            )
            return
        connection.send(("ok", result))
    except BaseException:
        # Parent treats a missing terminal message as a fail-closed worker failure.
        return
    finally:
        try:
            connection.close()
        except OSError:
            pass


def _remote_error(
    failure_type: object,
    detail: object,
    retry_after_seconds: object,
) -> BaseException:
    """Preserve the child's safe exception class name for scheduler attribution."""

    type_name = str(failure_type or "RemoteNodeExecutionError").strip()
    if _SAFE_FAILURE_TYPE.fullmatch(type_name) is None:
        type_name = "RemoteNodeExecutionError"
    error_type = type(type_name, (RuntimeError,), {})
    error = error_type(str(detail or "provider-facing certification node failed"))
    try:
        retry = float(retry_after_seconds) if retry_after_seconds is not None else None
    except (TypeError, ValueError):
        retry = None
    if retry is not None and math.isfinite(retry) and retry > 0.0:
        setattr(error, "retry_after_seconds", min(retry, 3600.0))
    return error


def _runner_for_node(runner: Callable[[object], int], node: object):
    factory = getattr(runner, "for_node", None)
    return factory(node) if callable(factory) else runner


def _launch_node(
    context,
    *,
    node: object,
    lease: tuple[str, ...],
    runner: Callable[[object], int],
) -> _RunningNode:
    child_runner = _runner_for_node(runner, node)
    try:
        # Fail in the parent with exact attribution rather than waiting for a spawn
        # bootstrap failure if a future lane input introduces an unpicklable object.
        pickle.dumps((child_runner, node), protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as error:
        raise SpawnSerializationError(
            f"{getattr(node, 'node_id', 'certification-node')} cannot cross spawn boundary: "
            f"{type(error).__name__}"
        ) from error

    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_node_worker,
        args=(child_connection, child_runner, node),
        name=f"certification-{getattr(node, 'asset_class', 'lane')}",
    )
    try:
        process.start()
        child_connection.close()
    except BaseException:
        try:
            child_connection.close()
        except OSError:
            pass
        try:
            parent_connection.close()
        except OSError:
            pass
        raise
    pid = int(process.pid or 0)
    return _RunningNode(
        node=node,
        lease=lease,
        connection=parent_connection,
        process=process,
        launched_at=time.monotonic(),
        process_start_ticks=process_start_ticks(pid) if pid > 1 else None,
    )


def _close_running(item: _RunningNode) -> None:
    try:
        item.connection.close()
    except OSError:
        pass


def _terminal_result(item: _RunningNode, message: object) -> int | BaseException:
    process = item.process
    process.join(timeout=_supervision._SHUTDOWN_GRACE_SECONDS)
    if process.is_alive():
        _supervision._stop_process(
            process,
            process_group_ready=item.process_group_ready,
        )
        return _supervision.SupervisedComponentExecutionError(
            f"{getattr(item.node, 'node_id', 'certification-node')} worker did not "
            "terminate after producing a result"
        )
    if not isinstance(message, tuple) or not message:
        return _supervision.SupervisedComponentExecutionError(
            f"{getattr(item.node, 'node_id', 'certification-node')} returned an invalid "
            "terminal result"
        )
    if message[0] == "ok" and len(message) == 2:
        try:
            return int(message[1])
        except (TypeError, ValueError):
            return _supervision.SupervisedComponentExecutionError(
                f"{getattr(item.node, 'node_id', 'certification-node')} returned a "
                "non-integer evidence count"
            )
    if message[0] == "error" and len(message) == 4:
        return _remote_error(message[1], message[2], message[3])
    return _supervision.SupervisedComponentExecutionError(
        f"{getattr(item.node, 'node_id', 'certification-node')} returned an invalid "
        "terminal result"
    )


def _poll_running(
    item: _RunningNode,
    *,
    timeout_seconds: float,
) -> int | BaseException | None:
    now = time.monotonic()
    if item.ready_at is None:
        if item.connection.poll(0.0):
            try:
                message = item.connection.recv()
            except (EOFError, OSError):
                return _supervision.SupervisedComponentExecutionError(
                    f"{getattr(item.node, 'node_id', 'certification-node')} worker exited "
                    "before becoming ready"
                )
            if not isinstance(message, tuple) or len(message) != 2 or message[0] != "ready":
                return _supervision.SupervisedComponentExecutionError(
                    f"{getattr(item.node, 'node_id', 'certification-node')} returned an "
                    "invalid readiness message"
                )
            item.process_group_ready = bool(message[1])
            item.ready_at = time.monotonic()
            return None
        if now - item.launched_at >= _supervision._STARTUP_TIMEOUT_SECONDS:
            _supervision._stop_process(item.process, process_group_ready=False)
            return _supervision.SupervisedComponentExecutionError(
                f"{getattr(item.node, 'node_id', 'certification-node')} worker did not "
                "establish its isolation boundary"
            )
        if not item.process.is_alive():
            return _supervision.SupervisedComponentExecutionError(
                f"{getattr(item.node, 'node_id', 'certification-node')} worker exited "
                "before becoming ready"
            )
        return None

    if item.connection.poll(0.0):
        try:
            message = item.connection.recv()
        except (EOFError, OSError):
            return _supervision.SupervisedComponentExecutionError(
                f"{getattr(item.node, 'node_id', 'certification-node')} worker exited "
                "without a terminal result"
            )
        return _terminal_result(item, message)
    if now - item.ready_at >= timeout_seconds:
        _supervision._stop_process(
            item.process,
            process_group_ready=item.process_group_ready,
        )
        return _supervision.SupervisedComponentTimeout(
            f"{getattr(item.node, 'node_id', 'certification-node')} exceeded its "
            f"{timeout_seconds:g}s execution budget"
        )
    if not item.process.is_alive():
        return _supervision.SupervisedComponentExecutionError(
            f"{getattr(item.node, 'node_id', 'certification-node')} worker exited without "
            "a terminal result"
        )
    return None


def _runtime_counts(results, pending, running) -> dict[str, int]:
    completed = sum(1 for item in results.values() if item.status == "qualified")
    reused = sum(
        1 for item in results.values() if item.status == "qualified" and item.reused
    )
    failed = sum(1 for item in results.values() if item.status != "qualified")
    return {
        "completed_nodes": completed,
        "reused_nodes": reused,
        "failed_nodes": failed,
        "running_nodes": len(running),
        "pending_nodes": len(pending),
    }


def _record_parent_progress(
    self,
    *,
    stage: str,
    node: object,
    required_count: int,
    results,
    pending,
    running,
) -> None:
    from operations.manual_cio_diagnostic import record_manual_cio_diagnostic_progress

    metrics = _runtime_counts(results, pending, running)
    metrics.update(
        {
            "required_nodes": required_count,
            "decision_eligible_records": int(
                getattr(node, "decision_eligible_count", 0)
            ),
            "provider_budget_count": len(getattr(node, "provider_groups", ()) or ()),
        }
    )
    record_manual_cio_diagnostic_progress(
        f"{stage}:{getattr(node, 'asset_class', 'other')}",
        metrics=metrics,
        values=self.values,
    )


def _publish_runtime_journal(self, *, nodes, results, pending, running) -> None:
    """Persist parent-owned lane state and exact process identity for crash recovery."""

    from operations import persistent_certification_scheduler as scheduler

    node_states: dict[str, object] = {}
    running_ids = set(running)
    pending_ids = set(pending)
    for node in nodes:
        active = running.get(node.node_id)
        result = results.get(node.node_id)
        if result is not None:
            state = result.status
            failure_type = result.failure_type
            reused = bool(result.reused)
        elif node.node_id in running_ids:
            state = "running"
            failure_type = None
            reused = False
        elif node.node_id in pending_ids:
            state = "pending"
            failure_type = None
            reused = False
        else:
            state = "blocked"
            failure_type = None
            reused = False
        node_states[node.node_id] = {
            "state": state,
            "asset_class": node.asset_class,
            "provider_groups": list(node.provider_groups),
            "decision_eligible_count": int(node.decision_eligible_count),
            "reused": reused,
            "failure_type": failure_type,
            "pid": (
                int(active.process.pid)
                if active is not None and active.process.pid is not None
                else None
            ),
            "process_start_ticks": (
                active.process_start_ticks if active is not None else None
            ),
            "process_group_ready": (
                bool(active.process_group_ready) if active is not None else False
            ),
        }

    body: dict[str, object] = {
        "schema_version": _RUNTIME_JOURNAL_SCHEMA,
        "release_sha": self.release_sha,
        "decision_epoch": self.epoch.isoformat(),
        "policy_version": self.policy_version,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "required_nodes": [node.node_id for node in nodes],
        "counts": _runtime_counts(results, pending, running),
        "node_states": node_states,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    path = (
        scheduler._root(self.values)
        / scheduler._SCHEMA_VERSION
        / self.release_sha
        / scheduler._epoch_key(self.epoch)
        / "runtime-latest.json"
    )
    scheduler._atomic_json(path, body)


def _dag_native_run(self, nodes: Sequence[object], runner: Callable[[object], int]):
    """Run durable DAG nodes in independently killable, spawn-safe processes."""

    from operations import persistent_certification_scheduler as scheduler

    ordered_nodes = tuple(nodes)
    by_id = {node.node_id: node for node in ordered_nodes}
    if len(by_id) != len(ordered_nodes):
        raise scheduler.CertificationSchedulerError(
            "certification DAG node identifiers must be unique"
        )
    for node in ordered_nodes:
        missing = set(node.dependencies).difference(by_id)
        if missing:
            raise scheduler.CertificationSchedulerError(
                f"certification node {node.node_id} has unknown dependencies: "
                + ", ".join(sorted(missing))
            )

    results: dict[str, object] = {}
    qualified: set[str] = set()
    pending: dict[str, object] = {}
    for node in ordered_nodes:
        cached = self._load_success(node)
        if cached is not None:
            results[node.node_id] = cached
            qualified.add(node.node_id)
        else:
            pending[node.node_id] = node

    providers = tuple(group for node in ordered_nodes for group in node.provider_groups)
    budgets = scheduler.ProviderBudgetRegistry(self.values, providers)
    worker_limit = scheduler._worker_count(self.values, len(pending) or 1)
    timeout_seconds = _node_timeout_seconds(self.values)
    try:
        context = multiprocessing.get_context("spawn")
    except ValueError as error:
        raise scheduler.CertificationSchedulerError(
            "certification DAG requires multiprocessing spawn isolation"
        ) from error

    running: dict[str, _RunningNode] = {}
    failures: set[str] = set()
    required_count = len(ordered_nodes)
    _publish_runtime_journal(
        self,
        nodes=ordered_nodes,
        results=results,
        pending=pending,
        running=running,
    )

    def submit_ready() -> bool:
        submitted = False
        ready = [
            node
            for node in pending.values()
            if set(node.dependencies).issubset(qualified)
            and not set(node.dependencies).intersection(failures)
        ]
        ready.sort(
            key=lambda node: (
                scheduler._aware(node.deadline, field_name="node_deadline"),
                -int(node.priority),
                node.node_id,
            )
        )
        for node in ready:
            if len(running) >= worker_limit:
                break
            lease = budgets.try_acquire(node.provider_groups)
            if lease is None:
                continue
            pending.pop(node.node_id, None)
            try:
                running[node.node_id] = _launch_node(
                    context,
                    node=node,
                    lease=lease,
                    runner=runner,
                )
                _publish_runtime_journal(
                    self,
                    nodes=ordered_nodes,
                    results=results,
                    pending=pending,
                    running=running,
                )
                _record_parent_progress(
                    self,
                    stage="certification_dag",
                    node=node,
                    required_count=required_count,
                    results=results,
                    pending=pending,
                    running=running,
                )
            except BaseException as error:  # noqa: BLE001 - persist launch failure.
                budgets.release(lease)
                results[node.node_id] = self._write_failure(node, error=error)
                failures.add(node.node_id)
                _publish_runtime_journal(
                    self,
                    nodes=ordered_nodes,
                    results=results,
                    pending=pending,
                    running=running,
                )
                _record_parent_progress(
                    self,
                    stage="certification_dag_failed",
                    node=node,
                    required_count=required_count,
                    results=results,
                    pending=pending,
                    running=running,
                )
            submitted = True
        return submitted

    try:
        while pending or running:
            submitted = submit_ready()
            completed_any = False
            for node_id, item in tuple(running.items()):
                outcome = _poll_running(item, timeout_seconds=timeout_seconds)
                if outcome is None:
                    continue
                completed_any = True
                running.pop(node_id, None)
                budgets.release(item.lease)
                _close_running(item)
                if isinstance(outcome, BaseException):
                    results[node_id] = self._write_failure(item.node, error=outcome)
                    failures.add(node_id)
                    stage = "certification_dag_failed"
                else:
                    results[node_id] = self._write_success(
                        item.node,
                        evidence_complete_count=outcome,
                    )
                    qualified.add(node_id)
                    stage = "certification_dag_complete"
                _publish_runtime_journal(
                    self,
                    nodes=ordered_nodes,
                    results=results,
                    pending=pending,
                    running=running,
                )
                _record_parent_progress(
                    self,
                    stage=stage,
                    node=item.node,
                    required_count=required_count,
                    results=results,
                    pending=pending,
                    running=running,
                )

            if not running and pending and not submitted and not completed_any:
                blocked = tuple(sorted(pending))
                for node_id in blocked:
                    node = pending.pop(node_id)
                    error = scheduler.CertificationSchedulerError(
                        f"certification dependencies did not qualify for {node_id}"
                    )
                    results[node_id] = self._write_failure(node, error=error)
                    failures.add(node_id)
                    _record_parent_progress(
                        self,
                        stage="certification_dag_failed",
                        node=node,
                        required_count=required_count,
                        results=results,
                        pending=pending,
                        running=running,
                    )
                _publish_runtime_journal(
                    self,
                    nodes=ordered_nodes,
                    results=results,
                    pending=pending,
                    running=running,
                )
                break
            if running and not completed_any:
                time.sleep(_POLL_INTERVAL_SECONDS)
    finally:
        for item in tuple(running.values()):
            _supervision._stop_process(
                item.process,
                process_group_ready=item.process_group_ready,
            )
            budgets.release(item.lease)
            _close_running(item)

    manifest = self._publish_manifest(nodes=ordered_nodes, results=results)
    _publish_runtime_journal(
        self,
        nodes=ordered_nodes,
        results=results,
        pending={},
        running={},
    )
    if manifest.failed_nodes:
        details = []
        for node_id in manifest.failed_nodes:
            item = results[node_id]
            suffix = item.failure_type or "unqualified"
            if item.retry_after is not None:
                suffix += f" retry_after={item.retry_after.isoformat()}"
            details.append(f"{node_id}:{suffix}")
        raise scheduler.CertificationSchedulerError(
            "required certification DAG nodes did not qualify: " + "; ".join(details)
        )
    return manifest


def _install_scheduler_supervision() -> None:
    from operations import persistent_certification_scheduler as scheduler

    current = scheduler.PersistentCertificationScheduler.run
    if getattr(current, "_dag_native_supervision", False):
        return
    _dag_native_run._dag_native_supervision = True  # type: ignore[attr-defined]
    scheduler.PersistentCertificationScheduler.run = _dag_native_run


def _install_discovery_coordinator() -> None:
    from operations import component_qualified_evidence_maintenance as maintenance

    current = maintenance._supervised_discovery_runner
    if getattr(current, "_dag_native_supervision", False):
        return

    def discovery_runner(values: Mapping[str, str]):
        runner = maintenance._component_discovery_runner(values)

        def run(timestamp: datetime):
            evidence_as_of = maintenance._aware(
                timestamp,
                field_name="dag_native_discovery_evidence_as_of",
            )
            try:
                runner(evidence_as_of)
            except maintenance._plane.ContinuousEvidencePlaneError:
                raise
            except Exception as error:
                raise maintenance._plane.ContinuousEvidencePlaneError(
                    "comprehensive-discovery DAG coordinator failed: "
                    f"{type(error).__name__}: {_supervision._safe_error(error)}"
                ) from error
            try:
                snapshot = maintenance.load_qualified_comprehensive_discovery_snapshot(
                    evidence_as_of=evidence_as_of,
                    values=values,
                )
            except maintenance.ComprehensiveDiscoverySnapshotError as error:
                raise maintenance._plane.ContinuousEvidencePlaneError(
                    "DAG-native discovery completed without a qualified snapshot: "
                    f"{_supervision._safe_error(error)}"
                ) from error
            return snapshot.result

        return run

    discovery_runner._dag_native_supervision = True  # type: ignore[attr-defined]
    maintenance._supervised_discovery_runner = discovery_runner


def install_dag_native_comprehensive_supervision() -> None:
    """Install granular spawn supervision and remove only the obsolete parent kill wall."""

    _install_scheduler_supervision()
    _install_discovery_coordinator()


__all__ = [
    "SpawnSerializationError",
    "install_dag_native_comprehensive_supervision",
]
