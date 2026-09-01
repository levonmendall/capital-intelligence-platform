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
import time
from collections.abc import Mapping
from multiprocessing.connection import Connection
from typing import Any, Callable, TypeVar


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

    def __init__(
        self,
        message: str,
        *,
        remote_error_type: str | None = None,
        status_code: int | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.remote_error_type = remote_error_type
        self.status_code = status_code
        self.retryable = retryable


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
            raw_status = getattr(error, "status_code", None)
            status_code = (
                int(raw_status)
                if isinstance(raw_status, int) and not isinstance(raw_status, bool)
                else None
            )
            raw_retryable = getattr(error, "retryable", None)
            retryable = raw_retryable if isinstance(raw_retryable, bool) else None
            connection.send(
                (
                    "error",
                    type(error).__name__,
                    _safe_error(error),
                    status_code,
                    retryable,
                )
            )
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
        if message[0] == "error" and len(message) == 5:
            raise SupervisedComponentExecutionError(
                f"{label} failed: {message[1]}: {message[2]}",
                remote_error_type=str(message[1]),
                status_code=message[3] if isinstance(message[3], int) else None,
                retryable=message[4] if isinstance(message[4], bool) else None,
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


def run_supervised_components(
    *,
    components: Mapping[str, Callable[[], Any]],
    timeout_seconds: float,
    maximum_parallel: int,
) -> dict[str, Any | BaseException]:
    """Run independent provider units concurrently with one hard timeout per unit.

    Each operation retains the same process-group isolation as
    :func:`run_supervised_component`.  The bounded parent launches no more than
    ``maximum_parallel`` children at once and returns a terminal value or exception for
    every requested unit, so one failed fallback cannot erase successful sibling work.
    """

    try:
        timeout = float(timeout_seconds)
    except (TypeError, ValueError) as error:
        raise ValueError("component batch timeout must be numeric") from error
    if not math.isfinite(timeout) or timeout <= 0.0:
        raise ValueError("component batch timeout must be positive")
    if isinstance(maximum_parallel, bool) or not isinstance(maximum_parallel, int):
        raise TypeError("maximum_parallel must be an integer")
    if maximum_parallel < 1:
        raise ValueError("maximum_parallel must be positive")

    ordered: list[tuple[str, Callable[[], Any]]] = []
    for raw_label, operation in components.items():
        label = str(raw_label).strip()
        if not label:
            raise ValueError("component batch labels must be nonempty")
        if not callable(operation):
            raise TypeError(f"{label} operation must be callable")
        ordered.append((label, operation))
    if len({label for label, _operation in ordered}) != len(ordered):
        raise ValueError("component batch labels must be unique")
    if not ordered:
        return {}

    try:
        context = multiprocessing.get_context("fork")
    except ValueError as error:
        raise SupervisedComponentExecutionError(
            "component batch requires POSIX fork process isolation"
        ) from error

    pending = list(ordered)
    outcomes: dict[str, Any | BaseException] = {}
    running: dict[str, dict[str, Any]] = {}

    def launch(label: str, operation: Callable[[], Any]) -> None:
        parent_connection, child_connection = context.Pipe(duplex=False)
        process = context.Process(
            target=_worker,
            args=(child_connection, operation, True),
            name=f"evidence-{label}",
        )
        try:
            process.start()
            child_connection.close()
        except BaseException:
            child_connection.close()
            parent_connection.close()
            raise
        running[label] = {
            "connection": parent_connection,
            "process": process,
            "launched_at": time.monotonic(),
            "ready_at": None,
            "process_group_ready": False,
        }

    def finish(label: str, outcome: Any | BaseException) -> None:
        item = running.pop(label)
        connection = item["connection"]
        process = item["process"]
        if isinstance(outcome, BaseException):
            duration_origin = item["ready_at"] or item["launched_at"]
            setattr(
                outcome,
                "supervised_duration_ms",
                int(max(0.0, time.monotonic() - float(duration_origin)) * 1000),
            )
        try:
            connection.close()
        except OSError:
            pass
        if process.pid is not None and process.is_alive():
            _stop_process(
                process,
                process_group_ready=bool(item["process_group_ready"]),
            )
        outcomes[label] = outcome

    try:
        while pending or running:
            while pending and len(running) < maximum_parallel:
                label, operation = pending.pop(0)
                launch(label, operation)

            progressed = False
            now = time.monotonic()
            for label, item in tuple(running.items()):
                connection = item["connection"]
                process = item["process"]
                ready_at = item["ready_at"]
                if ready_at is None:
                    if connection.poll(0.0):
                        try:
                            message = connection.recv()
                        except (EOFError, OSError):
                            finish(
                                label,
                                SupervisedComponentExecutionError(
                                    f"{label} worker exited before becoming ready"
                                ),
                            )
                            progressed = True
                            continue
                        if (
                            not isinstance(message, tuple)
                            or len(message) != 2
                            or message[0] != "ready"
                        ):
                            finish(
                                label,
                                SupervisedComponentExecutionError(
                                    f"{label} worker returned an invalid readiness message"
                                ),
                            )
                            progressed = True
                            continue
                        item["process_group_ready"] = bool(message[1])
                        item["ready_at"] = time.monotonic()
                        progressed = True
                        continue
                    if now - float(item["launched_at"]) >= _STARTUP_TIMEOUT_SECONDS:
                        finish(
                            label,
                            SupervisedComponentExecutionError(
                                f"{label} worker did not establish its isolation boundary"
                            ),
                        )
                        progressed = True
                    continue

                if connection.poll(0.0):
                    try:
                        message = connection.recv()
                    except (EOFError, OSError):
                        finish(
                            label,
                            SupervisedComponentExecutionError(
                                f"{label} worker exited without a terminal result"
                            ),
                        )
                        progressed = True
                        continue
                    process.join(timeout=_SHUTDOWN_GRACE_SECONDS)
                    if process.is_alive():
                        finish(
                            label,
                            SupervisedComponentExecutionError(
                                f"{label} worker did not terminate after producing a result"
                            ),
                        )
                    elif isinstance(message, tuple) and len(message) == 2 and message[0] == "ok":
                        finish(label, message[1])
                    elif isinstance(message, tuple) and len(message) == 5 and message[0] == "error":
                        finish(
                            label,
                            SupervisedComponentExecutionError(
                                f"{label} failed: {message[1]}: {message[2]}",
                                remote_error_type=str(message[1]),
                                status_code=(
                                    message[3] if isinstance(message[3], int) else None
                                ),
                                retryable=(
                                    message[4] if isinstance(message[4], bool) else None
                                ),
                            ),
                        )
                    else:
                        finish(
                            label,
                            SupervisedComponentExecutionError(
                                f"{label} worker returned an invalid terminal result"
                            ),
                        )
                    progressed = True
                    continue

                if now - float(ready_at) >= timeout:
                    finish(
                        label,
                        SupervisedComponentTimeout(
                            f"{label} exceeded its {timeout:g}s execution budget"
                        ),
                    )
                    progressed = True
                    continue
                if not process.is_alive():
                    finish(
                        label,
                        SupervisedComponentExecutionError(
                            f"{label} worker exited without a terminal result"
                        ),
                    )
                    progressed = True

            if not progressed and running:
                time.sleep(0.01)
    finally:
        for label in tuple(running):
            finish(
                label,
                SupervisedComponentExecutionError(
                    f"{label} batch execution was interrupted"
                ),
            )

    return outcomes


__all__ = [
    "SupervisedComponentExecutionError",
    "SupervisedComponentTimeout",
    "run_supervised_component",
    "run_supervised_components",
]
