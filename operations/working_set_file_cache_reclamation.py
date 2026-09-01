"""Identify file-backed working-set pressure that can be reclaimed safely.

The production cgroup working-set estimate is ``memory.current - inactive_file``. That is
conservative, but it means recently used *active* file cache is intentionally included in
the working set. A small boundary crossing can therefore be file-backed even when the
non-file working set remains below the unchanged governed boundary.

This helper does not reclaim memory and cannot change a resource boundary. It only answers
whether one bounded clean-file reclamation pass is safe to attempt before the caller
remeasures the exact same boundary. Missing accounting, true non-file pressure, and
insufficient active-file ownership all remain non-reclaimable and fail closed.
"""

from __future__ import annotations

from typing import Protocol


class _Snapshot(Protocol):
    working_set_kib: int | None
    active_file_kib: int | None


class _Boundaries(Protocol):
    working_set_kib: int


def should_reclaim_file_backed_working_set(
    snapshot: _Snapshot,
    boundaries: _Boundaries,
) -> bool:
    """Return true only when active file cache can explain the boundary crossing.

    ``working_set - active_file`` is a conservative non-file remainder because any kernel
    memory and every anonymous page remain in that remainder. A reclaim attempt is allowed
    only when that remainder is still below the unchanged governed boundary and active file
    cache is at least as large as the observed overage. The caller still remeasures the
    original boundary immediately after one bounded clean-file pass, so an ineffective
    advisory reclaim cannot make unsafe memory pass.

    Earlier code additionally required 32 MiB of active-file ownership beyond the actual
    crossing. That classification-only cushion was not a governed memory limit and could
    suppress reclamation for the production-sized small crossings this helper exists to
    distinguish from genuine anonymous/non-file pressure.
    """

    working = snapshot.working_set_kib
    active_file = snapshot.active_file_kib
    boundary = int(boundaries.working_set_kib)
    if (
        not isinstance(working, int)
        or not isinstance(active_file, int)
        or working < boundary
        or active_file <= 0
        or boundary <= 0
    ):
        return False

    overage = working - boundary
    non_file_working = max(0, working - active_file)
    return non_file_working < boundary and active_file >= overage


__all__ = ["should_reclaim_file_backed_working_set"]
