"""Bounded rolling history for investor-facing public-event metadata.

Every collection pass may return a partial source window or experience one provider
outage. This module merges the new normalized records with recent prior records so a
successful 24-hour news set is not erased by one thin or degraded pass. Source
publication time remains authoritative and stale records are never renewed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


_HISTORY_WINDOW = timedelta(hours=30)
_MAX_RECORDS = 2000


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("rolling public-event history requires an aware timestamp")
    return value.astimezone(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _record_time(record: Mapping[str, Any], *, fallback: datetime | None) -> datetime | None:
    for field_name in ("published_at", "event_at", "available_at"):
        parsed = _parse_time(record.get(field_name))
        if parsed is not None:
            return parsed
    return fallback


def _record_key(record: Mapping[str, Any]) -> str:
    direct = str(
        record.get("canonical_event_identifier")
        or record.get("identifier")
        or ""
    ).strip().casefold()
    if direct:
        return direct
    provenance = record.get("provenance")
    source_identifier = (
        str(provenance.get("source_identifier", "")).strip().casefold()
        if isinstance(provenance, Mapping)
        else ""
    )
    material = "|".join(
        (
            source_identifier,
            str(record.get("topic", "")).strip().casefold(),
            str(record.get("published_at", "")).strip(),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _existing_records(path: Path) -> tuple[Mapping[str, Any], ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, Mapping):
        return ()
    records = payload.get("records", [])
    if not isinstance(records, list):
        return ()
    return tuple(item for item in records if isinstance(item, Mapping))


def merge_public_event_records(
    path: str | Path,
    current_records: Iterable[Mapping[str, Any]],
    *,
    evaluated_at: datetime,
) -> list[dict[str, Any]]:
    """Return current plus recent prior records, deduplicated by event identity."""

    now = _aware(evaluated_at)
    cutoff = now - _HISTORY_WINDOW
    current = tuple(dict(item) for item in current_records if isinstance(item, Mapping))
    previous = _existing_records(Path(path))

    # Current normalized metadata wins when the same event appears in both sets.
    # A current corrected record also suppresses an older cached version even when
    # the corrected timestamp proves the event is outside the rolling window.
    current_keys = {_record_key(record) for record in current}
    chosen: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for is_current, records in ((True, current), (False, previous)):
        for record in records:
            key = _record_key(record)
            if not is_current and key in current_keys:
                continue
            observed_at = _record_time(record, fallback=now if is_current else None)
            if observed_at is None or observed_at > now or observed_at < cutoff:
                continue
            if key in chosen:
                continue
            chosen[key] = (observed_at, dict(record))

    ordered = sorted(
        chosen.values(),
        key=lambda item: (item[0], _record_key(item[1])),
        reverse=True,
    )
    return [record for _observed_at, record in ordered[:_MAX_RECORDS]]


__all__ = ["merge_public_event_records"]
