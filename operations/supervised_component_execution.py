"""Bound provider-facing evidence work behind a killable process boundary.

The continuous evidence plane is fail-closed: a provider call that never returns must not
hold release prequalification forever.  This module executes one operational component in
an isolated POSIX process group, returns only a small explicitly requested result, and
terminates the whole child process group when its execution budget expires.

Nothing here has investment, specialist, construction, execution, or real-money authority.
"""

from __future__ import annotations

import math
import multiprocessing
import os
import re
import signal
from multiprocessing.connection import Connection
from typing import Callable, TypeVar


_T = TypeVar("_T")
_STARTUP_TIMEOUT_SECONDS = 10.0
_SHUTDOWN_GRACE_SECONDS = 2.0
_MAX_ERROR_LENGTH = 600
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|token|secret|password|authorization)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)


class SupervisedComponentExecutionError(RuntimeError):
    """Raised when an isolated evidence component cannot complete safely."""


class SupervisedComponentTimeout(SupervisedComponentExecutionError):
    """Raised when a component exceeds its hard execution budget."""


def _safe_error(value: object) -> str:
    text = " ".join(str(value).split())
    text = _SECRET_PATTERN.sub(r"\1\2<redacted>", text)
    return text[:_MAX_ERROR_LENGTH]


def _worker(
    connection: Connection,
    operation: Callable[[], object],
    return_value: bool,
) -> None:
    process_group_ready = False
    try:
        if os.name == "posix":
            os.setsid()
            process_group_ready = True
        connection.send(("ready", process_group_ready))
        try:
            result = operation()
        except BaseException as error:  # child must report ordinary provider failures
            connection.send(("error", type(error).__name__, _safe_error(error)))
            return
        connection.send(("ok", result if return_value else None))
    except BaseException:
        # The parent treats a missing terminal message as a fail-closed worker failure.
        return
    finally:
        try:
            connection.close()
        except OSError:
            pass


def _stop_process(process: multiprocessing.Process, *, process_group_ready: bool) -> None:
    if not process.is_alive():
        process.join(timeout=_SHUTDOWN_GRACE_SECONDS)
        return

    terminated_group = False
    if os.name == "posix" and process_group_ready and process.pid is not None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            terminated_group = True
        except (OSError, ProcessLookupError):
            terminated_group = False
    if not terminated_group:
        process.terminate()
    process.join(timeout=_SHUTDOWN_GRACE_SECONDS)

    if process.is_alive():
        killed_group = False
        if os.name == "posix" and process_group_ready and process.pid is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
                killed_group = True
            except (OSError, ProcessLookupError):
                killed_group = False
        if not killed_group:
            try:
                process.kill()
            except AttributeError:
                process.terminate()
        process.join(timeout=_SHUTDOWN_GRACE_SECONDS)


def run_supervised_component(
    *,
    component: str,
    operation: Callable[[], _T],
    timeout_seconds: float,
    return_value: bool = True,
) -> _T | None:
    """Run one component with a hard timeout and terminate its process subtree on expiry."""

    label = str(component).strip() or "evidence-component"
    try:
        timeout = float(timeout_seconds)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} timeout must be numeric") from error
    if not math.isfinite(timeout) or timeout <= 0.0:
        raise ValueError(f"{label} timeout must be positive")

    try:
        context = multiprocessing.get_context("fork")
    except ValueError as error:
        raise SupervisedComponentExecutionError(
            f"{label} requires POSIX fork process isolation"
        ) from error

    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker,
        args=(child_connection, operation, return_value),
        name=f"evidence-{label}",
    )
    process_group_ready = False
    try:
        process.start()
        child_connection.close()

        if not parent_connection.poll(_STARTUP_TIMEOUT_SECONDS):
            _stop_process(process, process_group_ready=False)
            raise SupervisedComponentExecutionError(
                f"{label} worker did not establish its isolation boundary"
            )
        try:
            ready = parent_connection.recv()
        except (EOFError, OSError) as error:
            _stop_process(process, process_group_ready=False)
            raise SupervisedComponentExecutionError(
                f"{label} worker exited before becoming ready"
            ) from error
        if not isinstance(ready, tuple) or len(ready) != 2 or ready[0] != "ready":
            _stop_process(process, process_group_ready=False)
            raise SupervisedComponentExecutionError(
                f"{label} worker returned an invalid readiness message"
            )
        process_group_ready = bool(ready[1])

        if not parent_connection.poll(timeout):
            _stop_process(process, process_group_ready=process_group_ready)
            raise SupervisedComponentTimeout(
                f"{label} exceeded its {timeout:g}s execution budget"
            )
        try:
            message = parent_connection.recv()
        except (EOFError, OSError) as error:
            _stop_process(process, process_group_ready=process_group_ready)
            raise SupervisedComponentExecutionError(
                f"{label} worker exited without a terminal result"
            ) from error

        process.join(timeout=_SHUTDOWN_GRACE_SECONDS)
        if process.is_alive():
            _stop_process(process, process_group_ready=process_group_ready)
            raise SupervisedComponentExecutionError(
                f"{label} worker did not terminate after producing a result"
            )
        if not isinstance(message, tuple) or not message:
            raise SupervisedComponentExecutionError(
                f"{label} worker returned an invalid terminal result"
            )
        if message[0] == "error" and len(message) == 3:
            raise SupervisedComponentExecutionError(
                f"{label} failed: {message[1]}: {message[2]}"
            )
        if message[0] != "ok" or len(message) != 2:
            raise SupervisedComponentExecutionError(
                f"{label} worker returned an invalid terminal result"
            )
        return message[1]
    finally:
        try:
            child_connection.close()
        except OSError:
            pass
        try:
            parent_connection.close()
        except OSError:
            pass
        if process.pid is not None and process.is_alive():
            _stop_process(process, process_group_ready=process_group_ready)


__all__ = [
    "SupervisedComponentExecutionError",
    "SupervisedComponentTimeout",
    "run_supervised_component",
]
