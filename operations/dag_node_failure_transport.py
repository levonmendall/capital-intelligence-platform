"""Preserve bounded causal truth across the certification DAG spawn boundary.

DAG-native comprehensive discovery intentionally executes provider-facing nodes in fresh
``spawn`` interpreters. The parent must receive enough credential-safe terminal evidence
to distinguish the actual provider/checkpoint failure from the process transport itself.
This module also ensures the DAG-native aggregate exception reflects the exact terminal
failure already persisted by the canonical scheduler contract instead of reducing it back
to only an exception class name. Scheduling, provider budgets, node timeouts, evidence
requirements, market scope, investment authority, and paper-only controls are unchanged.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable, Mapping
from multiprocessing.connection import Connection

from operations import dag_native_comprehensive_supervision as _dag
from operations import persistent_certification_scheduler as _scheduler
from operations import supervised_component_execution as _supervision


_DETAIL_MESSAGE = "message"
_DETAIL_CAUSE_TYPE = "cause_type"
_DETAIL_CAUSE_MESSAGE = "cause_message"


def _direct_cause(error: BaseException) -> BaseException | None:
    if error.__cause__ is not None:
        return error.__cause__
    if not error.__suppress_context__ and error.__context__ is not None:
        return error.__context__
    return None


def _safe_type_name(value: object, *, fallback: str) -> str:
    name = str(value or "").strip()
    if _dag._SAFE_FAILURE_TYPE.fullmatch(name) is None:
        return fallback
    return name


def _transport_detail(error: BaseException) -> dict[str, str | None]:
    cause = _direct_cause(error)
    return {
        _DETAIL_MESSAGE: _supervision._safe_error(error),
        _DETAIL_CAUSE_TYPE: None if cause is None else type(cause).__name__,
        _DETAIL_CAUSE_MESSAGE: None if cause is None else _supervision._safe_error(cause),
    }


def _node_worker(
    connection: Connection,
    runner: Callable[[object], int],
    node: object,
) -> None:
    """Run one clean-spawn node and return bounded causal metadata to its parent."""

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
                    _transport_detail(error),
                    retry_seconds,
                )
            )
            return
        connection.send(("ok", result))
    except BaseException:
        # The parent treats a missing terminal message as a fail-closed worker failure.
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
    """Reconstruct the child's safe error and its direct cause in the scheduler parent."""

    type_name = _safe_type_name(failure_type, fallback="RemoteNodeExecutionError")
    cause_type_name: str | None = None
    cause_message: str | None = None
    if isinstance(detail, Mapping):
        message = str(
            detail.get(_DETAIL_MESSAGE)
            or "provider-facing certification node failed"
        )
        raw_cause_type = str(detail.get(_DETAIL_CAUSE_TYPE) or "").strip()
        raw_cause_message = str(detail.get(_DETAIL_CAUSE_MESSAGE) or "").strip()
        if raw_cause_type or raw_cause_message:
            cause_type_name = _safe_type_name(
                raw_cause_type,
                fallback="RemoteNodeCauseError",
            )
            cause_message = (
                raw_cause_message
                or "provider-facing certification node cause unavailable"
            )
    else:
        # Backward-compatible support for a legacy worker message already in flight.
        message = str(detail or "provider-facing certification node failed")

    error_type = type(type_name, (RuntimeError,), {})
    error = error_type(message)
    if cause_type_name is not None:
        cause_type = type(cause_type_name, (RuntimeError,), {})
        error.__cause__ = cause_type(
            cause_message or "provider-facing certification node cause unavailable"
        )

    try:
        retry = float(retry_after_seconds) if retry_after_seconds is not None else None
    except (TypeError, ValueError):
        retry = None
    if retry is not None and math.isfinite(retry) and retry > 0.0:
        setattr(error, "retry_after_seconds", min(retry, 3600.0))
    return error


def _terminal_manifest_body(self: object) -> Mapping[str, object] | None:
    """Load only this scheduler instance's integrity-protected exact-epoch manifest."""

    values = getattr(self, "values", None)
    release_sha = str(getattr(self, "release_sha", "") or "").strip()
    epoch = getattr(self, "epoch", None)
    policy_version = str(getattr(self, "policy_version", "") or "")
    if not isinstance(values, Mapping) or not release_sha or epoch is None:
        return None
    try:
        path = (
            _scheduler._root(values)
            / _scheduler._SCHEMA_VERSION
            / release_sha
            / _scheduler._epoch_key(epoch)
            / "latest.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    body = payload.get("body") if isinstance(payload, Mapping) else None
    if not isinstance(body, Mapping) or payload.get("sha256") != _scheduler._digest(body):
        return None
    expected = {
        "schema_version": _scheduler._MANIFEST_SCHEMA_VERSION,
        "release_sha": release_sha,
        "decision_epoch": _scheduler._aware(
            epoch,
            field_name="scheduler_epoch",
        ).isoformat(),
        "policy_version": policy_version,
    }
    if any(body.get(key) != value for key, value in expected.items()):
        return None
    return body


def _terminal_failure_detail(body: Mapping[str, object]) -> str | None:
    """Render the same exact terminal detail contract as the canonical scheduler."""

    raw_failed = body.get("failed_nodes")
    node_results = body.get("node_results")
    if not isinstance(raw_failed, list) or not raw_failed or not isinstance(node_results, Mapping):
        return None

    details: list[str] = []
    for raw_node_id in raw_failed:
        node_id = str(raw_node_id or "").strip()
        item = node_results.get(node_id)
        if not node_id or not isinstance(item, Mapping):
            return None
        suffix = str(item.get("failure_type") or "unqualified")
        failure_message = str(item.get("failure_message") or "").strip()
        if failure_message:
            suffix += f": {failure_message}"
        failure_cause_type = str(item.get("failure_cause_type") or "").strip()
        failure_cause_message = str(item.get("failure_cause_message") or "").strip()
        if failure_cause_type:
            suffix += f"; cause={failure_cause_type}"
            if failure_cause_message:
                suffix += f": {failure_cause_message}"
        suffix += f"; retryable={str(bool(item.get('retryable'))).lower()}"
        retry_after = str(item.get("retry_after") or "").strip()
        if retry_after:
            suffix += f"; retry_after={retry_after}"
        details.append(f"{node_id}:{suffix}")
    return "required certification DAG nodes did not qualify: " + "; ".join(details)


def _install_terminal_failure_projection() -> None:
    """Prevent DAG-native aggregation from discarding persisted exact terminal truth."""

    current = _scheduler.PersistentCertificationScheduler.run
    if getattr(current, "_exact_terminal_failure_projection", False):
        return

    def run(self, nodes, runner):
        try:
            return current(self, nodes, runner)
        except _scheduler.CertificationSchedulerError as error:
            body = _terminal_manifest_body(self)
            detail = None if body is None else _terminal_failure_detail(body)
            if detail is None or detail == str(error):
                raise
            raise _scheduler.CertificationSchedulerError(detail) from error

    # This is a transparent terminal projection around the already-installed scheduler
    # runtime. Preserve every upstream runtime identity/capability marker so strict bootstrap
    # verification still sees the same DAG-native/progress-aware supervision contract.
    run.__dict__.update(getattr(current, "__dict__", {}))
    run._exact_terminal_failure_projection = True  # type: ignore[attr-defined]
    _scheduler.PersistentCertificationScheduler.run = run


def install_dag_node_failure_transport() -> None:
    """Install causal transport and exact terminal projection without changing scheduling."""

    if not getattr(_dag._node_worker, "_causal_failure_transport", False):
        _node_worker._causal_failure_transport = True  # type: ignore[attr-defined]
        _remote_error._causal_failure_transport = True  # type: ignore[attr-defined]
        _dag._node_worker = _node_worker
        _dag._remote_error = _remote_error
    _install_terminal_failure_projection()


__all__ = ["install_dag_node_failure_transport"]
