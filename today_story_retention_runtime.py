"""Retain the last qualified Today stories when no new story is available.

The current 24-hour selection remains authoritative. This presentation-only
runtime stores the most recent source-qualified record set on the persistent
application disk and reuses it only when the current selection is empty. Prior
stories keep their original publication timestamps and are explicitly labeled
as retained history; they are never renewed, treated as current evidence, or
allowed to authorize a portfolio action.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping, Sequence

import streamlit as st


_INSTALLED_STATE_KEY = "_capital_intelligence_today_story_retention_installed"
_SCHEMA_VERSION = "today-story-retention.v1"
_MAX_CACHED_RECORDS = 250


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
    """Use current items first, then the latest historical 24-hour story batch."""

    evaluated_at = _utc_now(now)
    candidates = _records(records)
    current = tuple(
        original_builder(candidates, now=evaluated_at, limit=limit)
    )
    if current:
        return current
    latest = _latest_record_time(event_ui, candidates, now=evaluated_at)
    if latest is None:
        return ()
    # Reuse the governed ranking, quality, channel, clustering, and provider
    # diversity controls by anchoring selection to the last recorded event.
    historical_anchor = latest + timedelta(microseconds=1)
    return tuple(
        original_builder(candidates, now=historical_anchor, limit=limit)
    )


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
    for record in _records(records):
        observed_at = _record_time(event_ui, record)
        if observed_at is None or observed_at > now:
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
        f"The latest prior stories remain visible; the most recent was published {date_label}. "
        "Their original publication times are preserved until newer qualifying information arrives."
    )


def _retaining_loader(
    original_loader: Callable[[], object],
    original_builder: Callable[..., tuple[object, ...]],
    event_ui: ModuleType,
) -> Callable[[], object]:
    def load_snapshot() -> object:
        snapshot = original_loader()
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

    return load_snapshot


def _retained_today_renderer(
    app: ModuleType,
    event_ui: ModuleType,
    operating_ui: ModuleType,
    story_ui: ModuleType,
    original_builder: Callable[..., tuple[object, ...]],
) -> Callable[[ModuleType, object], None]:
    def render_today(active_app: ModuleType, dependencies: object) -> None:
        del dependencies
        story_ui._styles()
        briefing = active_app._latest("daily_cio_briefing")
        market = active_app.load_live_market_console()
        snapshot = operating_ui.load_public_event_snapshot()
        records = _records(getattr(snapshot, "records", ()))
        now = datetime.now(timezone.utc)
        current_items = tuple(original_builder(records, now=now, limit=3))
        items = tuple(operating_ui.build_today_items(records, now=now, limit=3))
        retained = not current_items and bool(items)

        active_app.page_header(
            "Investment world today",
            "What happened, why investors care, how markets may react, and what evidence matters next.",
            "NOW",
        )
        active_app.render_information_freshness(
            briefing=briefing,
            surface="today",
        )
        if retained:
            kicker = "Today // latest prior developments"
            deck = (
                "No new source-qualified development cleared the current 24-hour controls. "
                "The most recent prior stories remain visible with their original publication age "
                "until newer qualifying information arrives."
            )
        else:
            kicker = "Today // current developments"
            deck = (
                "Only source-qualified developments from the last 24 hours appear as current. "
                "Each story separates the fact, the investment mechanism, and the possible market "
                "reaction so headlines are not mistaken for trading signals."
            )
        hero = (
            '<section class="ci-today"><div class="ci-head"><div>'
            f'<div class="ci-kicker">{escape(kicker)}</div>'
            '<h2>What is moving the investment conversation</h2>'
            f'<div class="ci-deck">{escape(deck)}</div></div><div class="ci-chips">'
            f'<span class="ci-chip">Market {story_ui._session(market).lower()}</span>'
            f'<span class="ci-chip">{escape(story_ui._coverage(market))} governed quotes</span>'
            f'<span class="ci-chip">{escape(story_ui._age_label(getattr(snapshot, "evaluated_at", None)))}</span>'
            + ('<span class="ci-chip">No new qualifying stories</span>' if retained else "")
            + "</div></div>"
        )
        if items:
            hero += story_ui._primary(items[0])
        else:
            detail = story_ui._clean(getattr(snapshot, "detail", "")) or (
                "No material, source-qualified event cleared the last-24-hour controls."
            )
            hero += (
                '<div class="ci-primary"><div class="ci-meta"><span class="ci-rank">'
                "Quiet-day conclusion</span></div>"
                '<div class="ci-title">No new story earned investor attention.</div>'
                '<div class="ci-box"><div class="ci-label">Why this is useful</div>'
                f'<p>{escape(detail)} A quiet result is more trustworthy than filling the page '
                "with repetitive or low-quality headlines.</p></div></div>"
            )
        st.markdown(hero + "</section>", unsafe_allow_html=True)

        if len(items) > 1:
            st.markdown(
                '<section class="ci-story-grid">'
                + "".join(
                    story_ui._secondary(item, rank)
                    for rank, item in enumerate(items[1:], start=2)
                )
                + "</section>",
                unsafe_allow_html=True,
            )
        if items:
            concept, explanation = story_ui._lesson(items[0])
            watch_markup = "".join(
                '<div class="ci-watch">'
                f'<span class="ci-num">{index:02d}</span><span>{escape(value)}</span></div>'
                for index, value in enumerate(story_ui._watch(items), start=1)
            )
            st.markdown(
                '<section class="ci-pair"><div class="ci-panel"><div class="ci-meta">'
                '<span class="ci-rank">What to watch next</span></div>'
                '<h3>Evidence that can confirm or reverse the story</h3>'
                f'{watch_markup}</div><div class="ci-panel"><div class="ci-meta">'
                '<span class="ci-rank">Investor lesson</span></div>'
                f'<h3>{escape(concept)}</h3><div class="ci-lesson">Learn the mechanism</div>'
                f'<div class="ci-copy">{escape(explanation)}</div></div></section>',
                unsafe_allow_html=True,
            )
        with st.expander("Original source context", expanded=False):
            if not items:
                st.write(
                    story_ui._clean(getattr(snapshot, "detail", ""))
                    or "No source-qualified event is available."
                )
            for index, item in enumerate(items, start=1):
                st.markdown(
                    f"**{index}. {story_ui._clean(getattr(item, 'title', 'Market development'))}**"
                )
                st.write(story_ui._clean(getattr(item, "summary", "")))
                st.caption(
                    f"{story_ui._clean(getattr(item, 'source_type', 'Public'))} source: "
                    f"{story_ui._clean(getattr(item, 'source', 'Public source'))} · published "
                    f"{story_ui._format_time(getattr(item, 'published_at', None))}"
                )
        story_ui._research_radar()
        with st.expander("Live market operating detail", expanded=False):
            active_app.render_live_market_status()
        retained_caption = (
            " No new qualifying event was available, so the latest prior stories remain visible "
            "with their original publication timestamps."
            if retained
            else ""
        )
        st.caption(
            event_ui._daily_caption(snapshot)
            + retained_caption
            + " Educational interpretation only. Today explains external developments; holdings "
            "and CIO-authorized actions remain in Portfolio."
        )

    return render_today


def install(
    app_impl: ModuleType,
    event_ui: ModuleType,
    operating_ui: ModuleType,
    story_ui: ModuleType,
) -> None:
    """Install story retention after the final Today storytelling renderer."""

    if getattr(app_impl, _INSTALLED_STATE_KEY, False):
        return

    original_builder = event_ui.build_today_items
    original_event_loader = event_ui.load_public_event_snapshot
    original_operating_loader = operating_ui.load_public_event_snapshot

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

    event_ui.build_today_items = build_today_items
    operating_ui.build_today_items = build_today_items
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
    story_ui._render_today = _retained_today_renderer(
        app_impl,
        event_ui,
        operating_ui,
        story_ui,
        original_builder,
    )
    setattr(app_impl, _INSTALLED_STATE_KEY, True)


__all__ = ["install"]
