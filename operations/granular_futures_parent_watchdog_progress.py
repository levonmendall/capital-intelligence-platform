"""Project granular futures reference progress into the release parent watchdog.

Futures reference qualification is intentionally supervised at the CME venue / Massive
root boundary rather than by one aggregate futures-component timeout.  The granular
coordinator already persists credential-safe logical progress for every active or completed
unit, but the release parent watchdog historically observed only the coarse
``reference-futures-contracts`` component.  Several valid 45-second fallback roots could
therefore look like one stalled reference component and trigger ``ParentStallTimeout``.

This adapter changes only watchdog liveness observation.  It does not change provider
timeouts, reference freshness/completeness, required roots, retry policy, memory limits,
CIO authority, construction, execution, or paper-only controls.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

from operations.granular_futures_reference_prequalification import (
    load_futures_reference_progress,
)


_FUTURES_COMPONENT = "reference-futures-contracts"
_INSTALLED_MARKER = "_capital_intelligence_granular_futures_parent_progress"


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _logical_units(value: object) -> tuple[tuple[str, str, str, str], ...]:
    if not isinstance(value, list):
        return ()
    logical: list[tuple[str, str, str, str]] = []
    for row in value:
        if not isinstance(row, Mapping):
            continue
        logical.append(
            (
                str(row.get("unit") or "").strip(),
                str(row.get("state") or "").strip(),
                str(row.get("root") or "").strip(),
                str(row.get("provider") or "").strip(),
            )
        )
    return tuple(logical)


def _project_granular_futures_progress(
    watchdog,
    coarse,
    values: Mapping[str, str],
    *,
    boundary: datetime,
):
    """Return root/venue progress only while the coarse futures component owns the stage."""

    if (
        coarse is None
        or coarse.phase != "reference_acquisition"
        or coarse.component != _FUTURES_COMPONENT
    ):
        return coarse

    progress = load_futures_reference_progress(values)
    if not isinstance(progress, Mapping):
        return coarse
    updated_at = watchdog._aware(progress.get("updated_at"))
    if updated_at is None or updated_at < boundary or updated_at < coarse.updated_at:
        return coarse

    active_unit = str(progress.get("active_unit") or "").strip()
    units = _logical_units(progress.get("units"))
    last_unit = next((unit for unit, _state, _root, _provider in reversed(units) if unit), "")
    component = active_unit or last_unit or coarse.component

    required_roots = tuple(
        sorted(
            str(item).strip().upper()
            for item in progress.get("required_roots", ())
            if str(item).strip()
        )
    ) if isinstance(progress.get("required_roots"), list) else ()
    qualified_roots = tuple(
        sorted(
            str(item).strip().upper()
            for item in progress.get("qualified_roots", ())
            if str(item).strip()
        )
    ) if isinstance(progress.get("qualified_roots"), list) else ()
    unresolved_roots = tuple(
        sorted(
            str(item).strip().upper()
            for item in progress.get("unresolved_roots", ())
            if str(item).strip()
        )
    ) if isinstance(progress.get("unresolved_roots"), list) else ()

    metrics = dict(coarse.metrics)
    for source, target in (
        ("required_root_count", "futures_required_root_count"),
        ("qualified_root_count", "futures_qualified_root_count"),
        ("unresolved_root_count", "futures_unresolved_root_count"),
    ):
        count = _nonnegative_int(progress.get(source))
        if count is not None:
            metrics[target] = count
    if active_unit:
        metrics["futures_active_unit"] = 1

    # Use logical state, not the file timestamp, as the liveness token.  Rewriting the same
    # checkpoint cannot manufacture indefinite progress; starting/completing a new venue or
    # root, changing coverage, or transitioning state can.
    token = repr(
        (
            str(progress.get("cutoff") or ""),
            str(progress.get("state") or ""),
            active_unit,
            required_roots,
            qualified_roots,
            unresolved_roots,
            units,
        )
    )
    parent_token = coarse.progress_token or coarse.updated_at.isoformat()
    return watchdog.PrequalificationProgress(
        phase=coarse.phase,
        component=component,
        updated_at=updated_at,
        state=coarse.state,
        # Preserve the existing finite reference stall budget unchanged.  Granular unit
        # checkpoints merely reset that budget when real durable progress occurs.
        stall_limit_seconds=coarse.stall_limit_seconds,
        metrics=metrics,
        progress_token=f"{parent_token}|granular-futures:{token}",
    )


def install_granular_futures_parent_watchdog_progress() -> None:
    """Wrap the parent's reference reader idempotently at startup."""

    from operations import release_prequalification_parent_watchdog as watchdog

    current = watchdog._reference_progress
    if bool(getattr(current, _INSTALLED_MARKER, False)):
        return

    def reference_progress(values: Mapping[str, str], *, boundary: datetime):
        coarse = current(values, boundary=boundary)
        return _project_granular_futures_progress(
            watchdog,
            coarse,
            values,
            boundary=boundary,
        )

    setattr(reference_progress, _INSTALLED_MARKER, True)
    watchdog._reference_progress = reference_progress


__all__ = [
    "install_granular_futures_parent_watchdog_progress",
]
