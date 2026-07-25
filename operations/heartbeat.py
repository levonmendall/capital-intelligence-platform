"""Atomic scheduler heartbeat files for worker health checks."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class WorkerHeartbeat:
    status: str
    observed_at: datetime
    cycle_key: str | None = None
    detail: str | None = None
    pid: int | None = None

    def __post_init__(self) -> None:
        if self.status not in {"starting", "healthy", "degraded", "failed", "stopped"}:
            raise ValueError("unsupported heartbeat status")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "observed_at": self.observed_at.isoformat(),
            "cycle_key": self.cycle_key,
            "detail": self.detail,
            "pid": self.pid,
        }


class WorkerHeartbeatStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(
        self,
        status: str,
        *,
        cycle_key: str | None = None,
        detail: str | None = None,
        observed_at: datetime | None = None,
    ) -> WorkerHeartbeat:
        heartbeat = WorkerHeartbeat(
            status=status,
            observed_at=observed_at or datetime.now(timezone.utc),
            cycle_key=cycle_key,
            detail=detail,
            pid=os.getpid(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(heartbeat.to_dict(), sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)
        return heartbeat

    def read(self) -> WorkerHeartbeat | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return WorkerHeartbeat(
            status=str(payload["status"]),
            observed_at=datetime.fromisoformat(str(payload["observed_at"])),
            cycle_key=payload.get("cycle_key"),
            detail=payload.get("detail"),
            pid=payload.get("pid"),
        )

    def health(
        self,
        *,
        maximum_age_seconds: int,
        now: datetime | None = None,
    ) -> tuple[bool, str, WorkerHeartbeat | None]:
        heartbeat = self.read()
        if heartbeat is None:
            return False, "worker heartbeat has not been recorded", None
        timestamp = now or datetime.now(timezone.utc)
        age = (timestamp - heartbeat.observed_at).total_seconds()
        if age < -5:
            return False, "worker heartbeat timestamp is in the future", heartbeat
        if age > maximum_age_seconds:
            return False, f"worker heartbeat is stale by {int(age)} seconds", heartbeat
        if heartbeat.status == "failed":
            return False, heartbeat.detail or "worker reported failure", heartbeat
        return True, f"worker heartbeat is {int(max(0, age))} seconds old", heartbeat


__all__ = ["WorkerHeartbeat", "WorkerHeartbeatStore"]
