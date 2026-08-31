"""Keep release-evidence qualifier diagnostics out of the long-lived service heap.

The release prequalification coordinator is intentionally long lived while every heavy
qualifier runs in a disposable child.  Capturing a child's complete stderr with
``subprocess.PIPE`` defeats part of that isolation: a verbose failed attempt can allocate a
large Python string in the serving process, and CPython's allocator may retain those arenas
across later retries.  Production then sees anonymous cgroup memory owned by the service
rather than by the currently supervised qualifier child.

This installer changes only stderr transport for the one bounded evidence command.  The
child still has the same resource/freshness limits and return code.  A bounded tail is read
from an unlinked disk-backed temporary file so the existing credential-safe failure parser
can retain its structured terminal record without retaining the complete child log in RAM.
No evidence, market, CIO, construction, execution, or real-money rule is changed.
"""

from __future__ import annotations

import ctypes
import gc
import os
import subprocess as _subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


_TAIL_BYTES = 256 * 1024
_QUALIFIER_SCRIPT = "run_bounded_continuous_evidence_plane.py"
_INSTALLED_ATTR = "_release_qualifier_stderr_isolation_installed"


def _command(args: object) -> tuple[str, ...]:
    if isinstance(args, (str, bytes, bytearray)):
        return (str(args),)
    if isinstance(args, Sequence):
        return tuple(str(item) for item in args)
    return ()


def _is_release_qualifier(args: object) -> bool:
    command = _command(args)
    return len(command) >= 2 and Path(command[1]).name == _QUALIFIER_SCRIPT and "--once" in command


def _bounded_tail(handle) -> str:
    handle.flush()
    handle.seek(0, os.SEEK_END)
    size = int(handle.tell())
    handle.seek(max(0, size - _TAIL_BYTES), os.SEEK_SET)
    payload = handle.read(_TAIL_BYTES)
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    return str(payload)


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


class _SubprocessProxy:
    """Module-local subprocess proxy overriding only the release qualifier's stderr path."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        setattr(self, _INSTALLED_ATTR, True)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def run(self, *args: Any, **kwargs: Any):
        command = args[0] if args else kwargs.get("args")
        if kwargs.get("stderr") is not self._delegate.PIPE or not _is_release_qualifier(command):
            return self._delegate.run(*args, **kwargs)

        temporary_root = str(os.environ.get("TMPDIR") or "").strip() or None
        with tempfile.TemporaryFile(mode="w+b", dir=temporary_root) as stderr_file:
            bounded_kwargs = dict(kwargs)
            bounded_kwargs["stderr"] = stderr_file
            completed = self._delegate.run(*args, **bounded_kwargs)
            stderr_tail = _bounded_tail(stderr_file)

        # Drop any unreferenced allocator arenas before the parent starts another bounded
        # attempt.  This cannot make an unsafe child pass a memory guard; it only returns
        # memory that the long-lived parent no longer owns logically.
        _release_retry_heap()
        return self._delegate.CompletedProcess(
            completed.args,
            completed.returncode,
            completed.stdout,
            stderr_tail,
        )


def install(memory_safe: Any) -> None:
    """Install disk-backed stderr capture on the memory-safe Render bootstrap only."""

    current = getattr(memory_safe, "subprocess", None)
    if current is None or getattr(current, _INSTALLED_ATTR, False):
        return
    memory_safe.subprocess = _SubprocessProxy(current)


__all__ = [
    "_TAIL_BYTES",
    "_SubprocessProxy",
    "_bounded_tail",
    "_is_release_qualifier",
    "_release_retry_heap",
    "install",
]
