"""Bound release-qualifier stderr without replacing Render's subprocess module.

The release prequalification parent watchdog already owns the one-shot evidence subprocess
and already routes its stderr through a disk-backed temporary file. The post-#881 repair
originally installed a second ``memory_safe.subprocess`` proxy before that watchdog. That
violated the watchdog's explicit bootstrap contract requiring the canonical ``subprocess``
module and caused Render startup to fail before the service could open its health-check
port.

This module now patches only the watchdog's internal watched-run implementation. It keeps
stderr disk-backed, returns at most a small tail to the long-lived serving process, and
leaves ``memory_safe.subprocess`` untouched so the existing watchdog and timeout proxies can
compose in their established order. No evidence, market, CIO, construction, execution, or
real-money rule is changed.
"""

from __future__ import annotations

import ctypes
import gc
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Mapping


_TAIL_BYTES = 256 * 1024
_INSTALLED_ATTR = "_release_qualifier_stderr_isolation_installed"


def _bounded_tail(handle, *, text_mode: bool) -> str | bytes:
    """Read only the final bounded stderr segment from an already disk-backed stream."""

    handle.flush()
    handle.seek(0, os.SEEK_END)
    size = int(handle.tell())
    handle.seek(max(0, size - _TAIL_BYTES), os.SEEK_SET)
    payload = handle.read(_TAIL_BYTES)
    if text_mode:
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="replace")
        return str(payload)
    if isinstance(payload, bytes):
        return payload
    return str(payload).encode("utf-8", errors="replace")


def _release_retry_heap() -> None:
    """Best-effort return of already-unreferenced allocator arenas between attempts."""

    try:
        gc.collect()
    except Exception:
        pass
    try:
        libc = ctypes.CDLL(None)
        malloc_trim = getattr(libc, "malloc_trim", None)
        if callable(malloc_trim):
            malloc_trim.argtypes = [ctypes.c_size_t]
            malloc_trim.restype = ctypes.c_int
            malloc_trim(0)
    except (AttributeError, OSError, TypeError, ValueError):
        pass


def _bounded_parent_watched_run(command: object, *, original_run, **kwargs):
    """Mirror the canonical parent watchdog while retaining only a bounded stderr tail."""

    from operations import release_prequalification_parent_watchdog as parent

    env = dict(kwargs.get("env") or os.environ)
    status = parent.load_release_evidence_prequalification(env)
    if not isinstance(status, Mapping) or parent._aware(status.get("started_at")) is None:
        return original_run(command, **kwargs)

    attempt_started_at = datetime.now(timezone.utc)
    poll_seconds = parent._positive_seconds(
        env,
        (parent._POLL_ENV,),
        parent._DEFAULT_POLL_SECONDS,
    )
    popen_kwargs = dict(kwargs)
    popen_kwargs.pop("check", None)
    requested_stderr = popen_kwargs.pop("stderr", None)
    if popen_kwargs.pop("capture_output", False):
        popen_kwargs.pop("stdout", None)
    text_mode = bool(
        popen_kwargs.get("text") or popen_kwargs.get("universal_newlines")
    )
    temporary_root = str(env.get("TMPDIR") or os.environ.get("TMPDIR") or "").strip() or None

    with tempfile.TemporaryFile(mode="w+b", dir=temporary_root) as error_stream:
        process = parent._subprocess.Popen(
            command,
            stderr=error_stream,
            start_new_session=(os.name == "posix"),
            **popen_kwargs,
        )
        last_marker: tuple[str, str, str, str] | None = None
        last_progress_at = time.monotonic()
        last_progress = None

        while process.poll() is None:
            progress = parent.observe_current_prequalification_progress(
                env,
                started_at=attempt_started_at,
            )
            if progress.marker != last_marker:
                last_marker = progress.marker
                last_progress_at = time.monotonic()
                last_progress = progress
                parent._publish_parent_progress(env, progress=progress)
            stalled_for = time.monotonic() - last_progress_at
            if stalled_for >= progress.stall_limit_seconds:
                parent._stop_process_group(process)
                failure_line = parent._stall_failure_line(
                    progress,
                    stall_seconds=stalled_for,
                )
                error_stream.write(("\n" + failure_line + "\n").encode("utf-8"))
                captured = _bounded_tail(error_stream, text_mode=text_mode)
                _release_retry_heap()
                return parent._subprocess.CompletedProcess(
                    command,
                    124,
                    stdout=None,
                    stderr=(
                        captured
                        if requested_stderr == parent._subprocess.PIPE
                        else None
                    ),
                )
            time.sleep(
                min(
                    poll_seconds,
                    max(0.05, progress.stall_limit_seconds / 4.0),
                )
            )

        if last_progress is not None:
            parent._publish_parent_progress(env, progress=last_progress)
        captured = _bounded_tail(error_stream, text_mode=text_mode)
        completed = parent._subprocess.CompletedProcess(
            command,
            int(process.returncode or 0),
            stdout=None,
            stderr=(captured if requested_stderr == parent._subprocess.PIPE else None),
        )
        _release_retry_heap()
        if kwargs.get("check") and completed.returncode:
            raise parent._subprocess.CalledProcessError(
                completed.returncode,
                command,
                output=completed.stdout,
                stderr=completed.stderr,
            )
        return completed


def install(memory_safe: Any) -> None:
    """Patch the existing watchdog owner without mutating ``memory_safe.subprocess``."""

    # ``memory_safe`` is intentionally inspected but never rewritten. The subsequent
    # parent-watchdog installer must still observe the canonical subprocess module.
    if getattr(memory_safe, "subprocess", None) is None:
        return

    from operations import release_prequalification_parent_watchdog as parent

    if getattr(parent, _INSTALLED_ATTR, False):
        return
    parent._watched_run = _bounded_parent_watched_run
    setattr(parent, _INSTALLED_ATTR, True)


__all__ = [
    "_TAIL_BYTES",
    "_bounded_parent_watched_run",
    "_bounded_tail",
    "_release_retry_heap",
    "install",
]
