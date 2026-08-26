"""Keep release-prequalification progress visible across wrapper retries.

The durable release-prequalification record owns the generation boundary for one governed
prequalification attempt. A short-lived wrapper process may retry while the stage-isolated
evidence pipeline for that same generation is still active. Using the wrapper process's
``now()`` timestamp as the observation boundary can therefore hide valid same-generation
journals that began before the retry and manufacture a false parent stall.

This adapter changes only watchdog liveness observation. It reuses the persisted
``prequalification_id`` / ``started_at`` generation identity when the release
prequalification is still pending or in progress. Older-generation journals remain outside
the boundary, all existing finite stall limits remain unchanged, and terminal states fall
back to the caller-provided boundary.

Nothing here changes evidence requirements, provider policy, memory limits, CIO authority,
construction, execution, or paper-only controls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping


_INSTALLED_MARKER = "_capital_intelligence_prequalification_generation_boundary"
_ACTIVE_STATES = frozenset({"pending", "in_progress"})


def _generation_boundary(watchdog, values: Mapping[str, str], *, fallback: datetime) -> datetime:
    """Return the persisted active-generation start without moving the boundary forward."""

    status = watchdog.load_release_evidence_prequalification(values)
    if not isinstance(status, Mapping):
        return fallback.astimezone(timezone.utc)

    prequalification_id = str(status.get("prequalification_id") or "").strip()
    state = str(status.get("state") or "").strip().lower()
    started_at = watchdog._aware(status.get("started_at"))
    fallback_utc = fallback.astimezone(timezone.utc)
    if (
        not prequalification_id
        or state not in _ACTIVE_STATES
        or started_at is None
        or started_at > fallback_utc
    ):
        return fallback_utc
    return started_at


def install_release_prequalification_retry_progress_boundary() -> None:
    """Make the parent observer use the durable generation boundary idempotently."""

    from operations import release_prequalification_parent_watchdog as watchdog

    current = watchdog.observe_current_prequalification_progress
    if bool(getattr(current, _INSTALLED_MARKER, False)):
        return

    def observe_current_prequalification_progress(
        values: Mapping[str, str], *, started_at: datetime
    ):
        boundary = _generation_boundary(watchdog, values, fallback=started_at)
        return current(values, started_at=boundary)

    setattr(observe_current_prequalification_progress, _INSTALLED_MARKER, True)
    watchdog.observe_current_prequalification_progress = observe_current_prequalification_progress


__all__ = [
    "install_release_prequalification_retry_progress_boundary",
]
