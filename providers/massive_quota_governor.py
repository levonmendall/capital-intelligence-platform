"""Cross-process request governor for the shared Massive API quota.

Massive credentials are shared by several evidence adapters. Per-provider retry and sleep
logic cannot prevent independent Render processes from consuming the same low-rate quota
at the same time. This module reserves request slots on persistent storage so every
production Massive adapter observes one common minimum interval.

The governor changes transport pacing only. It has no discovery, ranking, CIO,
construction, execution, or real-money authority.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Callable, Iterator, TextIO

try:  # pragma: no cover - Render is POSIX; fallback keeps imports portable.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

_DEFAULT_MINIMUM_INTERVAL_SECONDS = 12.5
_INTERVAL_ENV = "CAPITAL_INTELLIGENCE_MASSIVE_GLOBAL_MIN_INTERVAL_SECONDS"
_PROCESS_LOCK = Lock()


def _minimum_interval(values: Mapping[str, str]) -> float:
    raw = str(values.get(_INTERVAL_ENV, "")).strip()
    if not raw:
        return _DEFAULT_MINIMUM_INTERVAL_SECONDS
    try:
        interval = float(raw)
    except ValueError as error:
        raise ValueError(f"{_INTERVAL_ENV} must be numeric") from error
    if not 0.0 <= interval <= 60.0:
        raise ValueError(f"{_INTERVAL_ENV} must be between 0 and 60")
    return interval


def _state_path(values: Mapping[str, str]) -> Path:
    root = Path(values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    return root / "provider_limits" / "massive-global-rate.json"


@contextmanager
def _locked_state(path: Path) -> Iterator[TextIO]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    _PROCESS_LOCK.acquire()
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield handle
    finally:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        _PROCESS_LOCK.release()
        handle.close()


def reserve_massive_request(
    *,
    values: Mapping[str, str] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
) -> float:
    """Reserve one shared Massive request slot and sleep until it becomes available.

    The persisted value is the wall-clock time of the most recently reserved slot, which
    may be in the near future when concurrent processes queue. Reserving before sleeping
    prevents two processes from waking into the same provider window.
    """

    resolved = os.environ if values is None else values
    interval = _minimum_interval(resolved)
    if interval <= 0.0:
        return 0.0

    path = _state_path(resolved)
    current = float(now())
    with _locked_state(path) as handle:
        handle.seek(0)
        try:
            payload = json.load(handle)
        except (json.JSONDecodeError, ValueError):
            payload = {}
        try:
            last_reserved = float(payload.get("last_reserved_epoch", 0.0))
        except (AttributeError, TypeError, ValueError):
            last_reserved = 0.0
        reserved = max(current, last_reserved + interval)
        handle.seek(0)
        handle.truncate(0)
        json.dump(
            {
                "schema_version": "massive-global-rate-governor.v1",
                "last_reserved_epoch": reserved,
                "minimum_interval_seconds": interval,
            },
            handle,
            sort_keys=True,
            separators=(",", ":"),
        )
        handle.write("\n")
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass

    delay = max(0.0, reserved - current)
    if delay > 0.0:
        sleeper(delay)
    return delay


__all__ = ["reserve_massive_request"]
