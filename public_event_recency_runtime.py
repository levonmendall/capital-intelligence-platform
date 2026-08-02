"""Use source publication time—not collection time—for Today recency.

Public sources can return the same item on every collection pass. The governed
collector truthfully records a new ``available_at`` retrieval timestamp each time,
but that timestamp must not renew an old story's investor-facing 24-hour life.
This presentation-only adapter makes publication time the primary recency
authority, event time the secondary authority, and retrieval time a last-resort
fallback when the source supplied neither.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType
from typing import Any, Mapping


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def source_event_time(record: Mapping[str, Any]) -> datetime | None:
    """Return the timestamp that governs whether a story is still current."""

    for field_name in ("published_at", "event_at", "available_at"):
        parsed = _parse_time(record.get(field_name))
        if parsed is not None:
            return parsed
    return None


def _recent_public_event_snapshot(event_ui: ModuleType):
    path = event_ui._records_path()
    try:
        modified_ns = path.stat().st_mtime_ns
    except OSError:
        modified_ns = 0
    reader = getattr(event_ui._read_public_event_file, "__wrapped__", event_ui._read_public_event_file)
    snapshot = reader(str(path), modified_ns)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=48)
    timed_records: list[tuple[datetime, Mapping[str, Any]]] = []
    for record in snapshot.records:
        if not isinstance(record, Mapping):
            continue
        observed_at = source_event_time(record)
        if observed_at is None or observed_at < cutoff or observed_at > now:
            continue
        timed_records.append((observed_at, record))
    timed_records.sort(key=lambda item: item[0], reverse=True)
    return event_ui.PublicEventSnapshot(
        records=tuple(record for _, record in timed_records[:1000]),
        evaluated_at=snapshot.evaluated_at,
        state=snapshot.state,
        detail=snapshot.detail,
    )


def install(event_ui: ModuleType | None = None) -> None:
    """Install the corrected clock in local and Render presentation paths."""

    if event_ui is None:
        import educational_market_briefing_ui as event_ui_module

        event_ui = event_ui_module

    event_ui._record_time = source_event_time

    nonblocking = sys.modules.get("render_nonblocking_data")
    if not isinstance(nonblocking, ModuleType):
        return
    loader = getattr(nonblocking, "_PUBLIC_EVENTS", None)
    if loader is None:
        return
    loader._supplier = lambda: _recent_public_event_snapshot(event_ui)
    reset = getattr(loader, "reset", None)
    if callable(reset):
        reset()


__all__ = ["install", "source_event_time"]
