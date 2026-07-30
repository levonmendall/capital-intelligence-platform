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
from zoneinfo import ZoneInfo

import streamlit as st

import premium_ui as ui
from providers.economic_snapshot import EconomicReadings, load_dashboard_data


_RECENT_WINDOW = timedelta(hours=24)
_DAILY_TIMEZONE = ZoneInfo("America/Los_Angeles")
_DAILY_ROLLOVER_HOUR = 5
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
    affected_investments: str
    what_to_watch: str
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


def daily_briefing_date(now: datetime | None = None) -> str:
    """Return the Pacific operating date that rolls at the 5:00 AM CIO cycle."""

    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(_DAILY_TIMEZONE)
    if evaluated_at.hour < _DAILY_ROLLOVER_HOUR:
        evaluated_at -= timedelta(days=1)
    return evaluated_at.date().isoformat()


def _daily_briefing_label(now: datetime | None = None) -> str:
    date_value = datetime.fromisoformat(daily_briefing_date(now))
    return date_value.strftime("%B %d, %Y")


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
    recency_bonus = max(
        0.0,
        1.0 - age_hours / (_RECENT_WINDOW.total_seconds() / 3600.0),
    ) * 0.18
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


def _investment_effects(channels: Sequence[str]) -> tuple[str, str, str]:
    channel_set = set(channels)
    effects: list[str] = []
    affected: list[str] = []
    watch: list[str] = []

    if channel_set & {"policy", "liquidity", "discount_rate", "inflation"}:
        effects.append(
            "Interest-rate expectations can move Treasury prices, borrowing costs, the dollar and the valuations of long-duration equities."
        )
        affected.extend(
            ("cash and short-duration bonds", "Treasuries", "growth equities", "U.S. dollar")
        )
        watch.extend(("central-bank guidance", "inflation data", "Treasury yields"))
    if channel_set & {"growth", "demand", "earnings"}:
        effects.append(
            "Changes in expected economic activity can alter revenue and profit expectations, especially for cyclical companies and lower-quality credit."
        )
        affected.extend(
            ("cyclical equities", "small caps", "corporate credit", "consumer sectors")
        )
        watch.extend(("employment", "consumer demand", "earnings guidance"))
    if channel_set & {"credit", "counterparty"}:
        effects.append(
            "A change in credit conditions can widen or narrow spreads and influence banks, leveraged companies and overall risk appetite."
        )
        affected.extend(("corporate bonds", "banks", "high-yield credit", "risk assets"))
        watch.extend(("credit spreads", "defaults", "funding conditions"))
    if channel_set & {"supply", "commodity", "climate_weather"}:
        effects.append(
            "Supply constraints can raise input costs and commodity prices while helping some producers and pressuring industries that consume those inputs."
        )
        affected.extend(
            ("commodities", "energy and materials", "transportation", "inflation-sensitive bonds")
        )
        watch.extend(("inventories", "shipping", "weather and production updates"))
    if channel_set & {"geopolitical", "regulation", "operational", "cyber"}:
        effects.append(
            "Policy or disruption risk can increase volatility and create sharply different outcomes across directly exposed sectors and regions."
        )
        affected.extend(
            ("defense and energy", "regulated industries", "regional equities", "volatility hedges")
        )
        watch.extend(("official actions", "company exposure", "market liquidity"))
    if channel_set & {"currency", "volatility", "positioning", "sentiment"}:
        effects.append(
            "Market positioning can amplify price moves even when fundamentals have not changed, affecting diversification and near-term entry risk."
        )
        affected.extend(("currencies", "equity indexes", "volatility strategies", "diversifiers"))
        watch.extend(("currency moves", "volatility", "positioning reversals"))

    effect_text = " ".join(dict.fromkeys(effects))
    affected_text = ", ".join(dict.fromkeys(affected))
    watch_text = ", ".join(dict.fromkeys(watch))
    return (
        effect_text
        or "The governed CIO process is still resolving the investment relevance of this development.",
        affected_text or "broad portfolio risk",
        watch_text or "corroborating evidence and market response",
    )


def _to_item(record: Mapping[str, Any]) -> EducationalBriefingItem:
    provenance = _provenance(record)
    published_at = _record_time(record) or datetime.now(timezone.utc)
    channels = _channels(record)
    title = _truncate(record.get("topic"), limit=112)
    summary = _truncate(record.get("summary"), limit=240)
    if summary.lower() == title.lower():
        summary = "The public source reported this development without additional concise detail."
    portfolio_lens, affected_investments, what_to_watch = _investment_effects(channels)
    return EducationalBriefingItem(
        title=title,
        summary=summary,
        portfolio_lens=portfolio_lens,
        affected_investments=affected_investments,
        what_to_watch=what_to_watch,
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
        return (
            "No public development in the last 24 hours met the recency, reliability and portfolio-relevance controls. "
            "That is a valid quiet-day result rather than missing content."
        )
    channel_names = [
        channel.replace("_", " ")
        for item in items
        for channel in item.impact_channels
    ]
    common = list(dict.fromkeys(channel_names))[:4]
    channel_text = ", ".join(common) if common else "broad market risk"
    affected = list(dict.fromkeys(item.affected_investments for item in items))
    investment_text = "; ".join(affected[:2])
    return _truncate(
        f"The daily feed identified {len(items)} development{'s' if len(items) != 1 else ''} worth understanding. "
        f"The main transmission channels are {channel_text}. Investments most likely to react include {investment_text}. "
        "The sections below explain what happened, why investors may care, and what evidence to watch next.",
        limit=520,
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


def economic_investment_implications(
    readings: EconomicReadings | None,
) -> tuple[tuple[str, str], ...]:
    if readings is None:
        return (
            (
                "Rates and cash",
                "Live readings are unavailable, so the app does not infer whether cash, short bonds or long bonds currently have an advantage.",
            ),
            (
                "Equities and credit",
                "Without current growth, inflation and yield evidence, valuation and credit sensitivity remain unresolved.",
            ),
            (
                "What to watch",
                "The next complete inflation, labor, policy and Treasury-yield update will refresh this daily assessment.",
            ),
        )

    policy_gap = readings.federal_funds_rate - readings.inflation_rate
    if policy_gap >= 1.0:
        rates = (
            "The policy rate is meaningfully above inflation. Cash and short-duration bonds may retain attractive income, "
            "while borrowers and highly valued long-duration assets face a higher hurdle."
        )
    elif policy_gap <= -1.0:
        rates = (
            "The policy rate is below inflation. Cash may provide less real purchasing-power protection, "
            "increasing the importance of inflation sensitivity and pricing power."
        )
    else:
        rates = (
            "The policy rate is close to inflation. Bond and equity pricing may be especially responsive "
            "to the next inflation or central-bank surprise."
        )

    spread = readings.yield_curve_spread
    if spread < -0.10:
        risk_assets = (
            "The 2-year yield is above the 10-year yield, a configuration often associated with restrictive policy or slower-growth concern. "
            "Cyclicals, small caps and lower-quality credit can be more vulnerable if growth weakens."
        )
    elif spread > 0.10:
        risk_assets = (
            "The 10-year yield is above the 2-year yield. Longer bonds offer more term yield, but a rising long rate can pressure "
            "growth-stock valuations and rate-sensitive sectors."
        )
    else:
        risk_assets = (
            "The curve is relatively flat. Investors may receive little term compensation while waiting to learn whether growth, inflation or policy moves next."
        )

    labor = (
        f"Unemployment is {readings.unemployment_rate:.1f}%. A sustained rise would usually challenge consumer demand, "
        "cyclical earnings and credit quality; continued labor strength can support spending but also keep wage and inflation pressure relevant."
    )
    return (
        ("Rates, cash and bonds", rates),
        ("Equities and credit", risk_assets),
        ("Growth and consumer sensitivity", labor),
    )


def economic_portfolio_lens(readings: EconomicReadings | None) -> str:
    return " ".join(text for _, text in economic_investment_implications(readings))


@st.cache_data(ttl=120, show_spinner=False)
def _read_public_event_file(path_value: str, modified_ns: int) -> PublicEventSnapshot:
    del modified_ns
    path = Path(path_value)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return PublicEventSnapshot(
            (),
            None,
            "unavailable",
            "The public-event record set has not been created yet.",
        )
    except (OSError, json.JSONDecodeError) as error:
        return PublicEventSnapshot(
            (),
            None,
            "degraded",
            f"The public-event record set could not be read: {error}",
        )
    if not isinstance(payload, Mapping):
        return PublicEventSnapshot(
            (),
            None,
            "degraded",
            "The public-event record set has an invalid structure.",
        )
    raw_records = payload.get("records", [])
    records = (
        tuple(item for item in raw_records if isinstance(item, Mapping))
        if isinstance(raw_records, list)
        else ()
    )
    evaluated_at = _parse_datetime(payload.get("evaluated_at"))
    return PublicEventSnapshot(
        records,
        evaluated_at,
        "available",
        "Governed public-event metadata is available.",
    )


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
                f"Most affected: {item.affected_investments}"
            )


def _render_visible_event_cards(items: Sequence[EducationalBriefingItem]) -> None:
    for index, item in enumerate(items, start=1):
        ui.callout_card(
            f"{index}. {item.title}",
            f"What happened: {item.summary} Investment impact: {item.portfolio_lens}",
            f"Most affected: {item.affected_investments} · Watch next: {item.what_to_watch}",
        )
        st.markdown("<div style='height:.55rem'></div>", unsafe_allow_html=True)


def _daily_caption(snapshot: PublicEventSnapshot) -> str:
    freshness = (
        "Unavailable"
        if snapshot.evaluated_at is None
        else snapshot.evaluated_at.strftime("%b %d, %Y · %H:%M UTC")
    )
    return (
        f"Daily briefing for {_daily_briefing_label()} · governed public-event metadata as of {freshness}. "
        "The daily operating date rolls at 5:00 AM Pacific and the source file is re-read as new governed records arrive."
    )


def render_today_market_brief() -> None:
    snapshot = load_public_event_snapshot()
    items = build_today_items(snapshot.records)
    ui.page_header(
        "What's happening today",
        "A concise daily investment briefing: what happened, why investors may care, which investments may react, and what to watch next.",
        "NOW",
    )
    ui.text_card("Daily investment synopsis", _overview(items))
    if items:
        _render_visible_event_cards(items)
        _render_event_details("Sources and supporting event detail", items)
    else:
        st.caption(snapshot.detail)
    st.caption(
        _daily_caption(snapshot)
        + " Educational context only; this section does not alter the CIO conclusion or authorize a paper trade."
    )


def render_environment_economic_brief() -> None:
    snapshot = load_public_event_snapshot()
    items = build_economic_event_items(snapshot.records)
    dashboard = load_dashboard_data()
    ui.page_header(
        "Economic context today",
        "The daily economic picture and a direct explanation of how rates, inflation, growth and the yield curve can affect investments.",
        "ECON",
    )
    ui.text_card("Economic picture", economic_snapshot_summary(dashboard.readings))
    for title, explanation in economic_investment_implications(dashboard.readings):
        ui.callout_card(title, explanation)
        st.markdown("<div style='height:.55rem'></div>", unsafe_allow_html=True)
    if items:
        ui.page_header(
            "Economic developments affecting investments",
            "Recent economic and policy events with their likely investment transmission channels stated plainly.",
            "WATCH",
        )
        _render_visible_event_cards(items)
        _render_event_details("Sources and supporting economic detail", items)
    else:
        st.caption(snapshot.detail)
    st.caption(
        _daily_caption(snapshot)
        + f" Economic readings: {dashboard.data_source}. Educational interpretation only; "
        "the governed CIO process separately determines whether any portfolio action is justified."
    )
