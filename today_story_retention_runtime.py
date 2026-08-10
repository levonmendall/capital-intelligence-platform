"""Retain the last qualified Today stories when no new story is available.

The current 24-hour selection remains authoritative. This retention-only runtime
stores the most recent source-qualified record set on the persistent application
disk and reuses it only when the current selection is empty. Prior stories remain
available for a bounded 72-hour continuity window, keep their original publication
timestamps, and are explicitly labeled as retained history by the canonical Today
renderer; they are never renewed, treated as current evidence, or allowed to
authorize a portfolio action.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping, Sequence


_INSTALLED_STATE_KEY = "_capital_intelligence_today_story_retention_installed"
_ORIGINAL_CALLABLE_ATTRIBUTE = "_capital_intelligence_today_story_retention_original"
_SCHEMA_VERSION = "today-story-retention.v1"
_MAX_CACHED_RECORDS = 250
_MAX_RETENTION_AGE = timedelta(hours=72)


def _utc_now(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise ValueError("Today story selection requires a timezone-aware timestamp")
    return resolved.astimezone(timezone.utc)


def _cache_path() -> Path:
    configured = os.getenv("CAPITAL_INTELLIGENCE_TODAY_STORY_RETENTION", "").strip()
    if configured:
        return Path(configured).expanduser()
    data_root = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    return data_root / "today-story-retention.json"


def _records(value: Iterable[Mapping[str, Any]]) -> tuple[Mapping[str, Any], ...]:
    return tuple(item for item in value if isinstance(item, Mapping))


def _base_callable(value: Callable[..., Any]) -> Callable[..., Any]:
    original = getattr(value, _ORIGINAL_CALLABLE_ATTRIBUTE, None)
    return original if callable(original) else value


def _mark_wrapper(
    wrapper: Callable[..., Any],
    original: Callable[..., Any],
) -> Callable[..., Any]:
    setattr(wrapper, _ORIGINAL_CALLABLE_ATTRIBUTE, _base_callable(original))
    return wrapper


def _record_time(event_ui: ModuleType, record: Mapping[str, Any]) -> datetime | None:
    parser = getattr(event_ui, "_record_time", None)
    if not callable(parser):
        return None
    parsed = parser(record)
    if not isinstance(parsed, datetime):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _latest_record_time(
    event_ui: ModuleType,
    records: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
) -> datetime | None:
    observed = [
        value
        for record in records
        if (value := _record_time(event_ui, record)) is not None and value <= now
    ]
    return max(observed) if observed else None


def _build_retained_items(
    original_builder: Callable[..., tuple[object, ...]],
    event_ui: ModuleType,
    records: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    limit: int = 3,
) -> tuple[object, ...]:
    """Use current items first, then the latest verified story batch."""

    evaluated_at = _utc_now(now)
    candidates = _records(records)
    current = tuple(original_builder(candidates, now=evaluated_at, limit=limit))
    if current:
        return current
    latest = _latest_record_time(event_ui, candidates, now=evaluated_at)
    if latest is None or evaluated_at - latest >= _MAX_RETENTION_AGE:
        return ()
    # Reuse the governed ranking, quality, channel, clustering, and provider
    # diversity controls by anchoring selection to the last recorded event.
    historical_anchor = latest + timedelta(microseconds=1)
    return tuple(original_builder(candidates, now=historical_anchor, limit=limit))


def _record_key(event_ui: ModuleType, record: Mapping[str, Any]) -> str:
    identifier = str(
        record.get("canonical_event_identifier")
        or record.get("identifier")
        or record.get("topic")
        or ""
    ).strip().casefold()
    observed_at = _record_time(event_ui, record)
    timestamp = observed_at.isoformat() if observed_at is not None else "unknown"
    return f"{identifier}|{timestamp}"


def _ordered_records(
    event_ui: ModuleType,
    records: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
) -> tuple[Mapping[str, Any], ...]:
    timed: list[tuple[datetime, Mapping[str, Any]]] = []
    cutoff = now - _MAX_RETENTION_AGE
    for record in _records(records):
        observed_at = _record_time(event_ui, record)
        if observed_at is None or observed_at > now or observed_at <= cutoff:
            continue
        timed.append((observed_at, record))
    timed.sort(key=lambda item: item[0], reverse=True)
    unique: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for _observed_at, record in timed:
        key = _record_key(event_ui, record)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(record)
        if len(unique) >= _MAX_CACHED_RECORDS:
            break
    return tuple(unique)


def _write_cache(
    event_ui: ModuleType,
    records: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
) -> None:
    ordered = _ordered_records(event_ui, records, now=now)
    if not ordered:
        return
    serializable: list[dict[str, Any]] = []
    for record in ordered:
        try:
            normalized = json.loads(json.dumps(dict(record), default=str))
        except (TypeError, ValueError):
            continue
        if isinstance(normalized, dict):
            serializable.append(normalized)
    if not serializable:
        return
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "cached_at": now.isoformat(),
        "records": serializable,
    }
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_cache() -> tuple[Mapping[str, Any], ...]:
    try:
        payload = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, Mapping):
        return ()
    if payload.get("schema_version") != _SCHEMA_VERSION:
        return ()
    raw_records = payload.get("records", [])
    if not isinstance(raw_records, list):
        return ()
    return tuple(item for item in raw_records if isinstance(item, Mapping))


def _merge_records(
    event_ui: ModuleType,
    primary: Iterable[Mapping[str, Any]],
    fallback: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
) -> tuple[Mapping[str, Any], ...]:
    return _ordered_records(event_ui, (*_records(primary), *_records(fallback)), now=now)


def _retention_detail(items: Sequence[object]) -> str:
    published = [
        value.astimezone(timezone.utc)
        for item in items
        if isinstance((value := getattr(item, "published_at", None)), datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    ]
    latest = max(published) if published else None
    date_label = (
        latest.strftime("%b %d, %Y · %H:%M UTC")
        if latest is not None
        else "an earlier period"
    )
    return (
        "No new source-qualified development cleared the current 24-hour controls. "
        f"The latest verified stories remain visible; the most recent was published {date_label}. "
        "Their original publication times are preserved while independent feeds refresh."
    )


def _retaining_loader(
    original_loader: Callable[[], object],
    original_builder: Callable[..., tuple[object, ...]],
    event_ui: ModuleType,
) -> Callable[[], object]:
    base_loader = _base_callable(original_loader)

    def load_snapshot() -> object:
        snapshot = base_loader()
        source_records = _records(getattr(snapshot, "records", ()))
        now = datetime.now(timezone.utc)
        current = tuple(original_builder(source_records, now=now, limit=3))
        if current:
            _write_cache(event_ui, source_records, now=now)
            return snapshot

        historical_source = _build_retained_items(
            original_builder,
            event_ui,
            source_records,
            now=now,
            limit=3,
        )
        if historical_source:
            _write_cache(event_ui, source_records, now=now)
            retained_records = source_records
            retained_items = historical_source
        else:
            retained_records = _merge_records(
                event_ui,
                source_records,
                _read_cache(),
                now=now,
            )
            retained_items = _build_retained_items(
                original_builder,
                event_ui,
                retained_records,
                now=now,
                limit=3,
            )
        if not retained_items:
            return snapshot

        return event_ui.PublicEventSnapshot(
            records=retained_records,
            evaluated_at=getattr(snapshot, "evaluated_at", None),
            state=str(getattr(snapshot, "state", "available")),
            detail=_retention_detail(retained_items),
        )

    return _mark_wrapper(load_snapshot, base_loader)


def install(
    app_impl: ModuleType,
    event_ui: ModuleType,
    operating_ui: ModuleType,
    story_ui: ModuleType,
) -> None:
    """Reattach retention adapters after each Streamlit rerun.

    This runtime owns story selection continuity only. It deliberately leaves
    ``story_ui._render_today`` unchanged so the canonical Today presentation can
    be installed independently by ``today_trust_ui_runtime``.
    """

    # Render and local Streamlit entrypoints run from top to bottom after every
    # navigation interaction. Earlier setup steps intentionally restore the
    # nonblocking loaders and the aligned 24-hour builder. Rebind retention on
    # every run so those assignments cannot silently remove the fallback.
    original_builder = _base_callable(event_ui.build_today_items)
    original_event_loader = _base_callable(event_ui.load_public_event_snapshot)
    original_operating_loader = _base_callable(operating_ui.load_public_event_snapshot)

    def build_today_items(
        records: Iterable[Mapping[str, Any]],
        *,
        now: datetime | None = None,
        limit: int = 3,
    ) -> tuple[object, ...]:
        return _build_retained_items(
            original_builder,
            event_ui,
            records,
            now=now,
            limit=limit,
        )

    retained_builder = _mark_wrapper(build_today_items, original_builder)
    event_ui.build_today_items = retained_builder
    operating_ui.build_today_items = retained_builder
    event_ui.load_public_event_snapshot = _retaining_loader(
        original_event_loader,
        original_builder,
        event_ui,
    )
    operating_ui.load_public_event_snapshot = _retaining_loader(
        original_operating_loader,
        original_builder,
        event_ui,
    )
    setattr(app_impl, _INSTALLED_STATE_KEY, True)


__all__ = ["install"]
