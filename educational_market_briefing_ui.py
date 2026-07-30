"""Concise educational market and economic context for the primary app surfaces.

The UI reads the governed public-information record set already collected by the
paper operator. It never fetches article bodies, invents a current event, changes
a CIO conclusion, or authorizes implementation.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import streamlit as st

import premium_ui as ui
from providers.economic_snapshot import EconomicReadings, load_dashboard_data


_RECENT_WINDOW = timedelta(hours=36)
_MARKET_CHANNELS = frozenset(
    {
        "growth",
        "inflation",
        "policy",
        "liquidity",
        "discount_rate",
        "earnings",
        "credit",
        "supply",
        "demand",
        "commodity",
        "currency",
        "volatility",
        "regulation",
        "geopolitical",
        "operational",
        "cyber",
        "climate_weather",
        "positioning",
        "sentiment",
        "counterparty",
    }
)
_ECONOMIC_CHANNELS = frozenset(
    {
        "growth",
        "inflation",
        "policy",
        "liquidity",
        "discount_rate",
        "credit",
        "demand",
        "commodity",
        "currency",
    }
)
_EXCLUDED_TAGS = frozenset({"sanctions-list", "fixture"})


@dataclass(frozen=True, slots=True)
class EducationalBriefingItem:
    title: str
    summary: str
    portfolio_lens: str
    source: str
    source_type: str
    published_at: datetime
    impact_channels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PublicEventSnapshot:
    records: tuple[Mapping[str, Any], ...]
    evaluated_at: datetime | None
    state: str
    detail: str


def _records_path() -> Path:
    configured = os.getenv("CAPITAL_INTELLIGENCE_PUBLIC_LIVE_RECORDS", "").strip()
    if configured:
        return Path(configured).expanduser()
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    return data_dir / "public-live-information-records.json"


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _clean_text(value: object) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(text.split())


def _truncate(value: object, *, limit: int) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    shortened = text[: max(limit - 1, 1)].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (shortened or text[: max(limit - 1, 1)]) + "…"


def _number(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _channels(record: Mapping[str, Any]) -> tuple[str, ...]:
    value = record.get("impact_channels", [])
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        dict.fromkeys(
            normalized
            for item in value
            if (normalized := _clean_text(item).lower())
        )
    )


def _tags(record: Mapping[str, Any]) -> frozenset[str]:
    value = record.get("tags", [])
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return frozenset()
    return frozenset(_clean_text(item).lower() for item in value if _clean_text(item))


def _provenance(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = record.get("provenance")
    return value if isinstance(value, Mapping) else {}


def _record_time(record: Mapping[str, Any]) -> datetime | None:
    for field_name in ("available_at", "published_at", "event_at"):
        parsed = _parse_datetime(record.get(field_name))
        if parsed is not None:
            return parsed
    return None


def _record_score(
    record: Mapping[str, Any],
    *,
    now: datetime,
    allowed_channels: frozenset[str],
) -> float:
    available_at = _record_time(record)
    if available_at is None:
        return -1.0
    age_hours = max((now - available_at).total_seconds() / 3600.0, 0.0)
    quality = (
        _number(record.get("reliability"), 0.0)
        * _number(record.get("relevance"), 0.0)
        * _number(record.get("materiality"), 0.0)
        * max(_number(record.get("independence"), 0.1), 0.1)
    )
    source_type = _clean_text(_provenance(record).get("source_type")).lower()
    source_bonus = {
        "official": 0.24,
        "regulatory": 0.20,
        "newswire": 0.16,
        "journalism": 0.12,
        "research": 0.08,
        "market": 0.08,
        "alternative": 0.02,
    }.get(source_type, 0.0)
    recency_bonus = max(0.0, 1.0 - age_hours / (_RECENT_WINDOW.total_seconds() / 3600.0)) * 0.18
    channel_bonus = min(len(set(_channels(record)) & allowed_channels), 3) * 0.04
    return quality + source_bonus + recency_bonus + channel_bonus


def _displayable(
    record: Mapping[str, Any],
    *,
    now: datetime,
    allowed_channels: frozenset[str],
) -> bool:
    topic = _clean_text(record.get("topic"))
    summary = _clean_text(record.get("summary"))
    available_at = _record_time(record)
    if not topic or not summary or available_at is None:
        return False
    if available_at > now or now - available_at > _RECENT_WINDOW:
        return False
    if _EXCLUDED_TAGS & _tags(record):
        return False
    if topic.lower().startswith("ofac sanctions listing:"):
        return False
    return bool(set(_channels(record)) & allowed_channels)


def _topic_key(record: Mapping[str, Any]) -> str:
    canonical = _clean_text(record.get("canonical_event_identifier")).lower()
    if canonical:
        return canonical
    return re.sub(r"[^a-z0-9]+", " ", _clean_text(record.get("topic")).lower()).strip()


def _select_records(
    records: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    allowed_channels: frozenset[str],
    limit: int,
) -> tuple[Mapping[str, Any], ...]:
    candidates = [
        record
        for record in records
        if _displayable(record, now=now, allowed_channels=allowed_channels)
    ]
    candidates.sort(
        key=lambda record: (
            _record_score(record, now=now, allowed_channels=allowed_channels),
            _record_time(record) or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )

    selected: list[Mapping[str, Any]] = []
    seen_topics: set[str] = set()
    provider_counts: dict[str, int] = {}
    deferred: list[Mapping[str, Any]] = []
    for record in candidates:
        key = _topic_key(record)
        if not key or key in seen_topics:
            continue
        provider = _clean_text(_provenance(record).get("provider")).lower() or "unknown"
        if provider_counts.get(provider, 0) >= 1:
            deferred.append(record)
            continue
        selected.append(record)
        seen_topics.add(key)
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
        if len(selected) >= limit:
            return tuple(selected)

    for record in deferred:
        key = _topic_key(record)
        if not key or key in seen_topics:
            continue
        selected.append(record)
        seen_topics.add(key)
        if len(selected) >= limit:
            break
    return tuple(selected)


def _portfolio_lens(channels: Sequence[str]) -> str:
    channel_set = set(channels)
    lenses: list[str] = []
    groups = (
        (
            {"policy", "liquidity", "discount_rate", "inflation"},
            "Rates, bond prices, equity valuations and the dollar may be most sensitive.",
        ),
        (
            {"growth", "demand", "earnings"},
            "Earnings expectations, cyclical assets and credit may be most sensitive.",
        ),
        (
            {"credit", "counterparty"},
            "Credit spreads, lenders and broader risk appetite may be most sensitive.",
        ),
        (
            {"supply", "commodity", "climate_weather"},
            "Commodity prices, inflation expectations and exposed industries may be most sensitive.",
        ),
        (
            {"geopolitical", "regulation", "operational", "cyber"},
            "Risk premiums and directly exposed sectors may be most sensitive.",
        ),
        (
            {"currency", "volatility", "positioning", "sentiment"},
            "Currency moves, volatility and diversification may matter most.",
        ),
    )
    for group, explanation in groups:
        if group & channel_set and explanation not in lenses:
            lenses.append(explanation)
        if len(lenses) == 2:
            break
    return " ".join(lenses) or "Portfolio relevance is still being resolved by the governed CIO process."


def _to_item(record: Mapping[str, Any]) -> EducationalBriefingItem:
    provenance = _provenance(record)
    published_at = _record_time(record) or datetime.now(timezone.utc)
    channels = _channels(record)
    title = _truncate(record.get("topic"), limit=112)
    summary = _truncate(record.get("summary"), limit=240)
    if summary.lower() == title.lower():
        summary = "The public source reported this development without additional concise detail."
    return EducationalBriefingItem(
        title=title,
        summary=summary,
        portfolio_lens=_portfolio_lens(channels),
        source=_truncate(provenance.get("provider") or "Public source", limit=80),
        source_type=_clean_text(provenance.get("source_type")).title() or "Public",
        published_at=published_at,
        impact_channels=channels,
    )


def build_today_items(
    records: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    limit: int = 3,
) -> tuple[EducationalBriefingItem, ...]:
    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return tuple(
        _to_item(record)
        for record in _select_records(
            records,
            now=evaluated_at,
            allowed_channels=_MARKET_CHANNELS,
            limit=limit,
        )
    )


def build_economic_event_items(
    records: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    limit: int = 2,
) -> tuple[EducationalBriefingItem, ...]:
    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return tuple(
        _to_item(record)
        for record in _select_records(
            records,
            now=evaluated_at,
            allowed_channels=_ECONOMIC_CHANNELS,
            limit=limit,
        )
    )


def _overview(items: Sequence[EducationalBriefingItem]) -> str:
    if not items:
        return "No recent public event met the section's recency and portfolio-relevance controls."
    titles = [item.title.rstrip(".") for item in items]
    if len(titles) == 1:
        event_text = titles[0]
    elif len(titles) == 2:
        event_text = f"{titles[0]} and {titles[1]}"
    else:
        event_text = f"{titles[0]}, {titles[1]}, and {titles[2]}"
    channels = [
        channel.replace("_", " ")
        for item in items
        for channel in item.impact_channels
    ]
    common = list(dict.fromkeys(channels))[:3]
    channel_text = ", ".join(common) if common else "general market risk"
    return _truncate(
        f"The current public feed highlights {event_text}. The main portfolio channels are {channel_text}. "
        "Each item is educational context; none becomes a trade instruction by itself.",
        limit=430,
    )


def economic_snapshot_summary(readings: EconomicReadings | None) -> str:
    if readings is None:
        return (
            "Live economic readings are unavailable. The section will remain explicitly incomplete "
            "rather than substitute sample values as current information."
        )
    spread = readings.yield_curve_spread
    if spread > 0.10:
        curve = f"The 10-year Treasury yield is {spread:.2f} percentage points above the 2-year yield."
    elif spread < -0.10:
        curve = f"The 2-year Treasury yield is {abs(spread):.2f} percentage points above the 10-year yield."
    else:
        curve = "The 2-year and 10-year Treasury yields are close to one another."
    return (
        f"Latest available readings: unemployment {readings.unemployment_rate:.1f}%, "
        f"inflation {readings.inflation_rate:.2f}%, federal funds {readings.federal_funds_rate:.2f}%, "
        f"2-year Treasury {readings.two_year_yield:.2f}%, and 10-year Treasury {readings.ten_year_yield:.2f}%. "
        f"{curve}"
    )


def economic_portfolio_lens(readings: EconomicReadings | None) -> str:
    if readings is None:
        return (
            "Without live readings, the app does not infer a current economic stance. Rates, inflation, "
            "growth and credit remain monitored through the governed evidence process."
        )
    policy_gap = readings.federal_funds_rate - readings.inflation_rate
    if policy_gap >= 1.0:
        policy_text = (
            "The policy rate is meaningfully above the latest inflation estimate. That generally supports "
            "income on cash and short-duration bonds while keeping borrowing and valuation hurdles elevated."
        )
    elif policy_gap <= -1.0:
        policy_text = (
            "The policy rate is below the latest inflation estimate. Real cash income may be less protective, "
            "and inflation-sensitive assets can remain important to watch."
        )
    else:
        policy_text = (
            "The policy rate is relatively close to the latest inflation estimate. Markets may remain sensitive "
            "to new inflation and central-bank evidence."
        )

    if readings.yield_curve_spread < -0.10:
        curve_text = (
            "A higher 2-year than 10-year yield can reflect restrictive policy or slower-growth concern, "
            "which may affect cyclicals, credit and rate-sensitive assets differently."
        )
    elif readings.yield_curve_spread > 0.10:
        curve_text = (
            "A higher 10-year than 2-year yield can improve the term premium available to longer bonds, "
            "while also raising discount-rate sensitivity for long-duration equities."
        )
    else:
        curve_text = (
            "A relatively flat curve leaves portfolios sensitive to whether the next change comes from growth, "
            "inflation or monetary policy."
        )
    labor_text = (
        f"At {readings.unemployment_rate:.1f}%, unemployment remains a key growth signal: a sustained rise "
        "would usually pressure consumption and cyclical earnings, while a tight labor market can keep wage "
        "and inflation pressure in focus."
    )
    return f"{policy_text} {curve_text} {labor_text}"


@st.cache_data(ttl=120, show_spinner=False)
def _read_public_event_file(path_value: str, modified_ns: int) -> PublicEventSnapshot:
    del modified_ns
    path = Path(path_value)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return PublicEventSnapshot((), None, "unavailable", "The public-event record set has not been created yet.")
    except (OSError, json.JSONDecodeError) as error:
        return PublicEventSnapshot((), None, "degraded", f"The public-event record set could not be read: {error}")
    if not isinstance(payload, Mapping):
        return PublicEventSnapshot((), None, "degraded", "The public-event record set has an invalid structure.")
    raw_records = payload.get("records", [])
    records = tuple(item for item in raw_records if isinstance(item, Mapping)) if isinstance(raw_records, list) else ()
    evaluated_at = _parse_datetime(payload.get("evaluated_at"))
    return PublicEventSnapshot(records, evaluated_at, "available", "Governed public-event metadata is available.")


def load_public_event_snapshot() -> PublicEventSnapshot:
    path = _records_path()
    try:
        modified_ns = path.stat().st_mtime_ns
    except OSError:
        modified_ns = 0
    return _read_public_event_file(str(path), modified_ns)


def _render_event_details(label: str, items: Sequence[EducationalBriefingItem]) -> None:
    if not items:
        return
    with st.expander(label):
        for index, item in enumerate(items, start=1):
            st.markdown(f"**{index}. {item.title}**")
            st.write(item.summary)
            st.caption(
                f"{item.source_type} source: {item.source} · "
                f"Published {item.published_at.strftime('%b %d · %H:%M UTC')} · "
                f"Portfolio lens: {item.portfolio_lens}"
            )


def render_today_market_brief() -> None:
    snapshot = load_public_event_snapshot()
    items = build_today_items(snapshot.records)
    ui.page_header(
        "What's happening today",
        "A one-minute educational summary of current events that may matter to investors.",
        "NOW",
    )
    ui.text_card("Today in one minute", _overview(items))
    if items:
        ui.activity_rail(
            tuple(
                (
                    " / ".join(channel.replace("_", " ").upper() for channel in item.impact_channels[:2])
                    or "MARKET EVENT",
                    item.title,
                    item.portfolio_lens,
                )
                for item in items
            )
        )
        _render_event_details("Brief event summaries and sources", items)
    else:
        st.caption(snapshot.detail)
    freshness = (
        "Unavailable"
        if snapshot.evaluated_at is None
        else snapshot.evaluated_at.strftime("%b %d, %Y · %H:%M UTC")
    )
    st.caption(
        f"Public-event metadata as of {freshness}. Educational context only; this section does not alter "
        "the CIO conclusion or authorize a paper trade."
    )


def render_environment_economic_brief() -> None:
    snapshot = load_public_event_snapshot()
    items = build_economic_event_items(snapshot.records)
    dashboard = load_dashboard_data()
    ui.page_header(
        "Economic context today",
        "The latest economic readings, relevant public developments, and the portfolio meaning in plain language.",
        "ECON",
    )
    left, right = st.columns(2, gap="large")
    with left:
        ui.text_card("Economic picture", economic_snapshot_summary(dashboard.readings))
    with right:
        ui.callout_card(
            "How it can affect portfolios",
            economic_portfolio_lens(dashboard.readings),
            "Educational interpretation, not a forecast or trade instruction.",
        )
    if items:
        ui.activity_rail(
            tuple(
                (
                    "ECONOMIC EVENT",
                    item.title,
                    item.portfolio_lens,
                )
                for item in items
            )
        )
        _render_event_details("Brief economic event summaries and sources", items)
    else:
        st.caption(snapshot.detail)
    st.caption(
        f"Economic readings: {dashboard.data_source}. Public-event metadata is used for education and context; "
        "the governed CIO process separately determines whether any portfolio action is justified."
    )
