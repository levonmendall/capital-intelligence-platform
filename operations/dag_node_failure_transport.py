"""Preserve bounded causal truth across the certification DAG spawn boundary.

DAG-native comprehensive discovery intentionally executes provider-facing nodes in fresh
``spawn`` interpreters.  The parent must receive enough credential-safe terminal evidence
to distinguish the actual provider/checkpoint failure from the process transport itself.
This module upgrades only that error transport.  Scheduling, provider budgets, node
timeouts, evidence requirements, market scope, investment authority, and paper-only
controls are unchanged.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Mapping
from multiprocessing.connection import Connection

from operations import dag_native_comprehensive_supervision as _dag
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
        message = str(detail.get(_DETAIL_MESSAGE) or "provider-facing certification node failed")
        raw_cause_type = str(detail.get(_DETAIL_CAUSE_TYPE) or "").strip()
        raw_cause_message = str(detail.get(_DETAIL_CAUSE_MESSAGE) or "").strip()
        if raw_cause_type or raw_cause_message:
            cause_type_name = _safe_type_name(
                raw_cause_type,
                fallback="RemoteNodeCauseError",
            )
            cause_message = raw_cause_message or "provider-facing certification node cause unavailable"
    else:
        # Backward-compatible support for a legacy worker message already in flight.
        message = str(detail or "provider-facing certification node failed")

    error_type = type(type_name, (RuntimeError,), {})
    error = error_type(message)
    if cause_type_name is not None:
        cause_type = type(cause_type_name, (RuntimeError,), {})
        error.__cause__ = cause_type(cause_message or "provider-facing certification node cause unavailable")

    try:
        retry = float(retry_after_seconds) if retry_after_seconds is not None else None
    except (TypeError, ValueError):
        retry = None
    if retry is not None and math.isfinite(retry) and retry > 0.0:
        setattr(error, "retry_after_seconds", min(retry, 3600.0))
    return error


def install_dag_node_failure_transport() -> None:
    """Install causal error transport without changing DAG scheduling or supervision."""

    if getattr(_dag._node_worker, "_causal_failure_transport", False):
        return
    _node_worker._causal_failure_transport = True  # type: ignore[attr-defined]
    _remote_error._causal_failure_transport = True  # type: ignore[attr-defined]
    _dag._node_worker = _node_worker
    _dag._remote_error = _remote_error


__all__ = ["install_dag_node_failure_transport"]
