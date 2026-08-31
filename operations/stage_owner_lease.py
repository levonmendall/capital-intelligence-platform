"""Cross-process ownership lease for one stage-isolated evidence worker.

The durable stage journal records what work is active, but it is not itself a liveness
primitive.  This POSIX flock lease lets a later coordinator distinguish a genuinely live
stage owner from an interrupted journal before it considers restart or freshness failure.
The lease is operational only and carries no evidence, investment, or execution authority.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class StageOwnerLease:
    descriptor: int
    path: Path
    pipeline_id: str
    stage: str
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

    def __enter__(self) -> "StageOwnerLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        self.release()


def _lease_path(state_path: Path, *, pipeline_id: str, stage: str) -> Path:
    safe_pipeline = "".join(ch for ch in str(pipeline_id) if ch.isalnum() or ch in "-_.")
    safe_stage = "".join(ch for ch in str(stage) if ch.isalnum() or ch in "-_.")
    if not safe_pipeline or not safe_stage:
        raise ValueError("stage owner identity is invalid")
    return state_path.parent / "stage-owners" / f"{safe_pipeline}-{safe_stage}.lock"


def try_acquire_stage_owner(
    state_path: Path,
    *,
    pipeline_id: str,
    stage: str,
) -> StageOwnerLease | None:
    """Acquire one exact pipeline/stage lease, returning ``None`` when already live."""

    try:
        import fcntl
    except ImportError as error:
        raise RuntimeError("stage ownership requires POSIX flock") from error

    path = _lease_path(state_path, pipeline_id=pipeline_id, stage=stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        return None

    payload = json.dumps(
        {
            "pipeline_id": pipeline_id,
            "stage": stage,
            "owner_pid": os.getpid(),
            "acquired_at": time.time(),
            "operational_only": True,
            "decision_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        },
        sort_keys=True,
    ).encode("utf-8")
    os.ftruncate(descriptor, 0)
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.write(descriptor, payload)
    os.fsync(descriptor)
    return StageOwnerLease(
        descriptor=descriptor,
        path=path,
        pipeline_id=pipeline_id,
        stage=stage,
    )


__all__ = ["StageOwnerLease", "try_acquire_stage_owner"]
