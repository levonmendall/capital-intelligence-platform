"""Serialize heavyweight Render work without changing investment authority.

The production web service has a hard 2 GB memory ceiling. A diagnostic, provider
validation pass, CIO operator pass, historical backfill, or encrypted backup can each be
legitimate on its own while still being unsafe when several start together. This module
provides a tiny POSIX advisory lock so lightweight coordinators can guarantee that only one
bounded heavyweight child owns the constrained memory lane at a time.

Release qualification may reserve a priority fence before waiting for the heavyweight lane.
The fence does not evict a live owner; it only prevents new background work from cutting in
between the current owner and the exact-release gate. The lock remains operational
coordination only. It cannot authorize a CIO decision, alter market scope, bypass evidence
gates, or enable real-money execution.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


_DEFAULT_TIMEOUT_SECONDS = 3600.0
_DEFAULT_POLL_SECONDS = 0.25
MEMORY_LANE_PRIORITY_BYPASS_ENV = (
    "CAPITAL_INTELLIGENCE_RENDER_MEMORY_LANE_PRIORITY_BYPASS"
)


def memory_lane_path(values: Mapping[str, str] | None = None) -> Path:
    resolved = os.environ if values is None else values
    configured = resolved.get("CAPITAL_INTELLIGENCE_RENDER_MEMORY_LANE_LOCK", "").strip()
    if configured:
        return Path(configured).expanduser()
    state_root = Path(
        resolved.get(
            "CAPITAL_INTELLIGENCE_DATA_DIR",
            "/app/database" if resolved.get("RENDER", "").lower() == "true" else "database",
        )
    ).expanduser()
    return state_root / "render-heavy-memory-lane.lock"


def memory_lane_priority_path(values: Mapping[str, str] | None = None) -> Path:
    resolved = os.environ if values is None else values
    configured = resolved.get(
        "CAPITAL_INTELLIGENCE_RENDER_MEMORY_LANE_PRIORITY_LOCK",
        "",
    ).strip()
    if configured:
        return Path(configured).expanduser()
    return Path(str(memory_lane_path(resolved)) + ".priority")


def _priority_bypass(values: Mapping[str, str]) -> bool:
    return str(values.get(MEMORY_LANE_PRIORITY_BYPASS_ENV) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _write_owner_payload(
    descriptor: int,
    *,
    owner: str,
    priority: bool,
) -> None:
    payload = json.dumps(
        {
            "owner": owner,
            "pid": os.getpid(),
            "acquired_at": time.time(),
            "priority": bool(priority),
            "operational_only": True,
            "real_money_authorized": False,
        },
        sort_keys=True,
    ).encode("utf-8")
    os.ftruncate(descriptor, 0)
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.write(descriptor, payload)
    os.fsync(descriptor)


@dataclass(slots=True)
class MemoryLaneLease:
    descriptor: int
    path: Path
    owner: str
    _released: bool = False

    def release(self) -> None:
        if self._released:
            return
        import fcntl

        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self.descriptor)
            self._released = True

    def __enter__(self) -> "MemoryLaneLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        self.release()


@dataclass(slots=True)
class MemoryLanePriorityLease:
    descriptor: int
    path: Path
    owner: str
    _released: bool = False

    def release(self) -> None:
        if self._released:
            return
        import fcntl

        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self.descriptor)
            self._released = True

    def __enter__(self) -> "MemoryLanePriorityLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        self.release()


def acquire_memory_lane_priority(
    owner: str,
    *,
    values: Mapping[str, str] | None = None,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    poll_seconds: float = _DEFAULT_POLL_SECONDS,
) -> MemoryLanePriorityLease | None:
    """Fence new background lane entrants without evicting the current heavy owner."""

    if not owner.strip():
        raise ValueError("memory lane priority owner cannot be empty")
    if timeout_seconds < 0:
        raise ValueError("timeout_seconds cannot be negative")
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")

    try:
        import fcntl
    except ImportError as error:
        raise RuntimeError("cross-process memory-lane locking requires POSIX flock") from error

    path = memory_lane_priority_path(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(descriptor)
                return None
            time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
            continue

        _write_owner_payload(descriptor, owner=owner, priority=True)
        return MemoryLanePriorityLease(descriptor=descriptor, path=path, owner=owner)


def acquire_memory_lane(
    owner: str,
    *,
    values: Mapping[str, str] | None = None,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    poll_seconds: float = _DEFAULT_POLL_SECONDS,
) -> MemoryLaneLease | None:
    """Acquire the single heavyweight lane, returning ``None`` on bounded timeout.

    Ordinary background owners briefly take a shared priority gate before each heavyweight
    lock attempt. A release-priority owner holds the corresponding exclusive gate, which
    prevents new background entrants while allowing the already-running heavy owner to
    finish normally. Exact-release children opt out of the shared gate only while their
    parent priority lease is held.
    """

    if not owner.strip():
        raise ValueError("memory lane owner cannot be empty")
    if timeout_seconds < 0:
        raise ValueError("timeout_seconds cannot be negative")
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")

    try:
        import fcntl
    except ImportError as error:  # Render is Linux; fail closed elsewhere.
        raise RuntimeError("cross-process memory-lane locking requires POSIX flock") from error

    resolved = dict(os.environ if values is None else values)
    path = memory_lane_path(resolved)
    priority_path = memory_lane_priority_path(resolved)
    path.parent.mkdir(parents=True, exist_ok=True)
    priority_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    priority_descriptor = (
        None
        if _priority_bypass(resolved)
        else os.open(priority_path, os.O_CREAT | os.O_RDWR, 0o600)
    )
    deadline = time.monotonic() + timeout_seconds

    while True:
        shared_priority_acquired = False
        if priority_descriptor is not None:
            try:
                fcntl.flock(priority_descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                shared_priority_acquired = True
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(priority_descriptor)
                    os.close(descriptor)
                    return None
                time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
                continue

        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if shared_priority_acquired and priority_descriptor is not None:
                fcntl.flock(priority_descriptor, fcntl.LOCK_UN)
            if time.monotonic() >= deadline:
                if priority_descriptor is not None:
                    os.close(priority_descriptor)
                os.close(descriptor)
                return None
            time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
            continue

        # The shared priority gate protects only the atomic heavy-lane acquisition. Release
        # it immediately after the heavy lane is owned so a foreground priority request may
        # fence future background entrants while this already-running owner finishes.
        if shared_priority_acquired and priority_descriptor is not None:
            fcntl.flock(priority_descriptor, fcntl.LOCK_UN)
        if priority_descriptor is not None:
            os.close(priority_descriptor)

        _write_owner_payload(descriptor, owner=owner, priority=False)
        return MemoryLaneLease(descriptor=descriptor, path=path, owner=owner)
