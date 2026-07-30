"""Educational and operational summaries for the four primary Streamlit surfaces.

This presentation layer connects governed public developments, current economic
readings, the opportunity scan, CIO conclusions, portfolio freshness, and later
outcome accountability. It never grants candidate, sizing, construction,
execution, policy-promotion, or real-money authority.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import premium_ui as ui
from api.config import ApiSettings
from core.portfolio import get_mandate_details
from educational_market_briefing_ui import (
    EducationalBriefingItem,
    PublicEventSnapshot,
    build_economic_event_items,
    build_today_items,
    economic_investment_implications,
    economic_snapshot_summary,
    load_public_event_snapshot,
)
from live_operating_console import load_live_market_console
from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    active_paper_universe_path,
    load_free_paper_pilot_universe,
)
from portfolio.constants import CANONICAL_PORTFOLIO_CODE
from providers.economic_snapshot import EconomicDashboardData, load_dashboard_data
from screening import SQLiteFullUniverseScreeningStore


_STATE_FILENAME = "production-context-publication-state.json"
_OUTCOME_TABLE = "opportunity_outcome_events"
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "with",
    }
)


@dataclass(frozen=True, slots=True)
class FreshnessEntry:
    label: str
    state: str
    detail: str


@dataclass(frozen=True, slots=True)
class OpportunityScanSnapshot:
    state: str
    as_of: datetime | None
    broad_assets_screened: int | None
    snapshot_covered: int | None
    companies_deepened: int | None
    governed_candidates: int | None
    opportunities_reaching_cio: int | None
    strongest_alternative: str
    strongest_stage: str
    main_reason: str
    decision_reference: str
    detail: str


@dataclass(frozen=True, slots=True)
class DecisionAccountabilitySnapshot:
    state: str
    recorded_decisions: int
    awaiting_evaluation: int
    avoided_losses: int
    missed_opportunities: int
    supported_gains: int
    supported_losses: int
    neutral_outcomes: int
    lesson: str
    recent_outcomes: tuple[Mapping[str, Any], ...]
    detail: str


def _clean_text(value: object) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", str(value or "")).split())


def _truncate(value: object, limit: int = 220) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    shortened = text[: max(1, limit - 1)].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (shortened or text[: max(1, limit - 1)]) + "…"


def _parse_datetime(value: object) -> datetime | None:
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


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def scheduler_timezone_name() -> str:
    value = os.getenv(
        "CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE",
        "America/Los_Angeles",
    ).strip()
    try:
        ZoneInfo(value)
    except Exception:
        return "America/Los_Angeles"
    return value


def scheduler_hour() -> int:
    raw = os.getenv("CAPITAL_INTELLIGENCE_SCHEDULER_HOUR", "7").strip()
    try:
        value = int(raw)
    except ValueError:
        return 7
    return value if 0 <= value <= 23 else 7


def operating_date(now: datetime | None = None) -> date:
    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(
        ZoneInfo(scheduler_timezone_name())
    )
    if evaluated_at.hour < scheduler_hour():
        evaluated_at -= timedelta(days=1)
    return evaluated_at.date()


def _schedule_label() -> str:
    zone_name = scheduler_timezone_name()
    zone_label = "Pacific" if zone_name == "America/Los_Angeles" else zone_name
    hour = scheduler_hour()
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return f"{display_hour}:00 {suffix} {zone_label}"


def _briefing_reference(briefing: Mapping[str, Any] | None) -> str:
    if not isinstance(briefing, Mapping):
        return "Unavailable"
    for field_name in ("decision_identifier", "identifier", "cycle_identifier"):
        value = _clean_text(briefing.get(field_name))
        if value:
            return value
    return "Unavailable"


def _flatten_text(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        text = _clean_text(value)
        return (text,) if text else ()
    if isinstance(value, Mapping):
        result: list[str] = []
        for item in value.values():
            result.extend(_flatten_text(item))
        return tuple(result)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result = []
        for item in value:
            result.extend(_flatten_text(item))
        return tuple(result)
    return ()


def _tokens(value: object) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", _clean_text(value).lower())
        if token not in _STOPWORDS
    }


def _material_match(event_text: str, values: Iterable[object]) -> bool:
    event_tokens = _tokens(event_text)
    if not event_tokens:
        return False
    for raw in values:
        text = _clean_text(raw)
        if not text:
            continue
        lowered_event = event_text.lower()
        lowered_text = text.lower()
        if lowered_event in lowered_text or lowered_text in lowered_event:
            return True
        comparison = _tokens(text)
        if not comparison:
            continue
        overlap = len(event_tokens & comparison) / max(1, min(len(event_tokens), len(comparison)))
        if overlap >= 0.34 and len(event_tokens & comparison) >= 2:
            return True
    return False


def classify_event_cio_relevance(
    item: EducationalBriefingItem,
    briefing: Mapping[str, Any] | None,
) -> str:
    """Return a conservative, explainable link between an event and the CIO record."""

    if not isinstance(briefing, Mapping):
        return "Awaiting CIO review"
    event_text = f"{item.title} {item.summary}"
    candidate_fields = (
        briefing.get("candidate_symbol"),
        briefing.get("candidate_asset"),
        briefing.get("candidate_identifier"),
    )
    candidate_tokens = set().union(*(_tokens(value) for value in candidate_fields))
    event_tokens = _tokens(event_text)
    meaningful_candidate_tokens = {
        token
        for token in candidate_tokens
        if token not in {"candidate", "instrument", "equity", "asset"}
    }
    if meaningful_candidate_tokens and meaningful_candidate_tokens & event_tokens:
        return "Advanced — associated with the CIO candidate"
    material_values = (
        *_flatten_text(briefing.get("material_developments")),
        *_flatten_text(briefing.get("what_changed")),
    )
    if _material_match(event_text, material_values):
        return "Material — explicitly reflected in the CIO briefing"
    posture_values = (
        *_flatten_text(briefing.get("why_it_matters")),
        *_flatten_text(briefing.get("opportunity_or_risk")),
        *_flatten_text(briefing.get("portfolio_decision")),
    )
    if _material_match(event_text, posture_values):
        return "Considered — supports the current portfolio posture"
    return "Monitored — not separately cited in the CIO briefing"


def _valid_source_url(value: object) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return text


def _record_source_url(record: Mapping[str, Any]) -> str | None:
    provenance = record.get("provenance")
    candidates: list[object] = []
    for source in (record, provenance if isinstance(provenance, Mapping) else {}):
        candidates.extend(
            source.get(field_name)
            for field_name in (
                "source_url",
                "canonical_url",
                "url",
                "source_uri",
                "uri",
                "link",
            )
        )
    for value in candidates:
        resolved = _valid_source_url(value)
        if resolved is not None:
            return resolved
    return None


def _matching_record(
    item: EducationalBriefingItem,
    records: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    title = item.title.rstrip("…").lower()
    best: tuple[float, Mapping[str, Any]] | None = None
    for record in records:
        topic = _clean_text(record.get("topic"))
        if not topic:
            continue
        topic_lower = topic.lower()
        topic_match = topic_lower == title or topic_lower.startswith(title) or title.startswith(topic_lower)
        record_time = None
        for field_name in ("available_at", "published_at", "event_at"):
            record_time = _parse_datetime(record.get(field_name))
            if record_time is not None:
                break
        time_distance = (
            abs((record_time - item.published_at).total_seconds())
            if record_time is not None
            else 10**9
        )
        score = (2.0 if topic_match else 0.0) + max(0.0, 1.0 - time_distance / 86400.0)
        if best is None or score > best[0]:
            best = (score, record)
    return None if best is None or best[0] < 1.0 else best[1]


def _daily_synopsis(items: Sequence[EducationalBriefingItem]) -> str:
    if not items:
        return (
            "No public development in the last 24 hours met the recency, reliability, "
            "and portfolio-relevance controls. That is a valid quiet-day conclusion."
        )
    affected = list(dict.fromkeys(item.affected_investments for item in items))
    channels = list(
        dict.fromkeys(
            channel.replace("_", " ")
            for item in items
            for channel in item.impact_channels
        )
    )
    return _truncate(
        f"{len(items)} development{'s' if len(items) != 1 else ''} currently deserve investor attention. "
        f"The main transmission channels are {', '.join(channels[:4]) or 'broad market risk'}. "
        f"Investments most likely to react include {'; '.join(affected[:2])}. "
        "The cards below explain the likely effect and what evidence would confirm or reverse it.",
        560,
    )


def _daily_caption(snapshot: PublicEventSnapshot) -> str:
    freshness = (
        "Unavailable"
        if snapshot.evaluated_at is None
        else snapshot.evaluated_at.strftime("%b %d, %Y · %H:%M UTC")
    )
    interval_seconds = max(
        60,
        _safe_int(os.getenv("CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS"))
        or 1800,
    )
    interval_minutes = max(1, interval_seconds // 60)
    return (
        f"Operating briefing for {operating_date().strftime('%B %d, %Y')} · rolls at {_schedule_label()} · "
        f"governed public information is collected at least every {interval_minutes} minutes · source set as of {freshness}."
    )


def _render_events(
    items: Sequence[EducationalBriefingItem],
    records: Sequence[Mapping[str, Any]],
    briefing: Mapping[str, Any] | None,
    *,
    detail_label: str,
) -> None:
    decision_reference = _briefing_reference(briefing)
    for index, item in enumerate(items, start=1):
        relevance = classify_event_cio_relevance(item, briefing)
        ui.callout_card(
            f"{index}. {item.title}",
            f"What happened: {item.summary} Investment impact: {item.portfolio_lens}",
            (
                f"CIO relevance: {relevance} · Most affected: {item.affected_investments} · "
                f"Watch next: {item.what_to_watch}"
            ),
        )
        st.markdown("<div style='height:.55rem'></div>", unsafe_allow_html=True)
    with st.expander(detail_label):
        for index, item in enumerate(items, start=1):
            record = _matching_record(item, records)
            source_url = _record_source_url(record) if isinstance(record, Mapping) else None
            st.markdown(f"**{index}. {item.title}**")
            st.write(item.summary)
            st.caption(
                f"CIO relevance: {classify_event_cio_relevance(item, briefing)} · "
                f"Decision reference: {decision_reference} · {item.source_type} source: {item.source} · "
                f"Published {item.published_at.strftime('%b %d · %H:%M UTC')}"
            )
            if source_url is not None:
                st.markdown(f"[Read original source]({source_url})")


def render_today_market_brief(
    *,
    briefing: Mapping[str, Any] | None = None,
) -> None:
    snapshot = load_public_event_snapshot()
    records = tuple(item for item in snapshot.records if isinstance(item, Mapping))
    items = build_today_items(records)
    ui.page_header(
        "What's happening today",
        "A concise daily investment briefing: what happened, how investments may react, what the CIO did with it, and what to watch next.",
        "NOW",
    )
    ui.text_card("Daily investment synopsis", _daily_synopsis(items))
    if items:
        _render_events(
            items,
            records,
            briefing,
            detail_label="Sources, CIO relevance, and supporting event detail",
        )
    else:
        st.caption(snapshot.detail)
    st.caption(
        _daily_caption(snapshot)
        + " Educational context only; headlines cannot alter the CIO conclusion or authorize a paper trade."
    )


def render_environment_economic_brief(
    *,
    briefing: Mapping[str, Any] | None = None,
) -> None:
    snapshot = load_public_event_snapshot()
    records = tuple(item for item in snapshot.records if isinstance(item, Mapping))
    items = build_economic_event_items(records)
    dashboard = load_dashboard_data()
    ui.page_header(
        "Economic context today",
        "The daily economic picture and a direct explanation of how rates, inflation, growth, and the yield curve can affect portfolios.",
        "ECON",
    )
    ui.text_card("Economic picture", economic_snapshot_summary(dashboard.readings))
    for title, explanation in economic_investment_implications(dashboard.readings):
        ui.callout_card(title, explanation)
        st.markdown("<div style='height:.55rem'></div>", unsafe_allow_html=True)
    if items:
        ui.page_header(
            "Economic developments affecting investments",
            "Recent economic and policy events with their likely asset-class transmission and CIO relevance stated plainly.",
            "WATCH",
        )
        _render_events(
            items,
            records,
            briefing,
            detail_label="Sources, CIO relevance, and supporting economic detail",
        )
    else:
        st.caption(snapshot.detail)
    st.caption(
        _daily_caption(snapshot)
        + f" Economic readings: {dashboard.data_source}. Educational interpretation only; "
        "the governed CIO process separately determines whether portfolio action is justified."
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _runtime_settings() -> ApiSettings | None:
    try:
        return ApiSettings.from_env()
    except (OSError, TypeError, ValueError):
        return None


def _candidate_name_map(
    candidate_payloads: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for payload in candidate_payloads:
        identifier = _clean_text(payload.get("identifier"))
        instrument = payload.get("instrument")
        if not identifier or not isinstance(instrument, Mapping):
            continue
        symbol = _clean_text(instrument.get("symbol")).upper()
        name = _clean_text(instrument.get("name")) or symbol
        result[identifier] = (symbol, name)
    return result


def _active_dynamic_instruments() -> tuple[tuple[str, str], ...]:
    try:
        base = load_free_paper_pilot_universe(DEFAULT_UNIVERSE_PATH)
        base_symbols = set(base.symbol_map)
    except (OSError, TypeError, ValueError):
        base_symbols = set()
    payload = _read_json(active_paper_universe_path())
    universe = payload.get("universe") if isinstance(payload, Mapping) else None
    raw = universe.get("instruments") if isinstance(universe, Mapping) else None
    if not isinstance(raw, list):
        return ()
    result: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        symbol = _clean_text(item.get("symbol")).upper()
        if not symbol or symbol in base_symbols:
            continue
        result.append((symbol, _clean_text(item.get("name")) or symbol))
    return tuple(result)


def _main_rejection_reason(publication: object) -> str:
    reasons: list[str] = []
    queue = getattr(publication, "opportunity_queue_payload", {})
    if isinstance(queue, Mapping):
        rejected = queue.get("rejected")
        if isinstance(rejected, list):
            for item in rejected:
                if isinstance(item, Mapping):
                    reasons.extend(_flatten_text(item.get("reasons")))
    exclusions = getattr(publication, "exclusions", ())
    if isinstance(exclusions, Sequence):
        for item in exclusions:
            if isinstance(item, Mapping):
                reasons.extend(_flatten_text(item.get("reasons")))
    cleaned = [_clean_text(item) for item in reasons if _clean_text(item)]
    if not cleaned:
        return (
            "No candidate cleared the complete evidence, return, downside, liquidity, "
            "implementation-cost, and opportunity-cost requirements."
        )
    return _truncate(Counter(cleaned).most_common(1)[0][0], 260)


def load_opportunity_scan() -> OpportunityScanSnapshot:
    settings = _runtime_settings()
    if settings is None:
        return OpportunityScanSnapshot(
            "unavailable",
            None,
            None,
            None,
            None,
            None,
            None,
            "Unavailable",
            "No operating context",
            "The production settings are unavailable.",
            "Unavailable",
            "The opportunity scan is available on the persistent operating host.",
        )
    state = _read_json(settings.portfolio_database.parent / _STATE_FILENAME)
    if state is None:
        return OpportunityScanSnapshot(
            "unavailable",
            None,
            None,
            None,
            None,
            None,
            None,
            "Unavailable",
            "Awaiting first scan",
            "The governed production-context state has not been published.",
            "Unavailable",
            "The next completed CIO cycle will publish the scan summary.",
        )
    as_of = _parse_datetime(state.get("decision_as_of"))
    cycle_identifier = _clean_text(state.get("screening_cycle_identifier"))
    equity = state.get("equity_discovery")
    equity_map = equity if isinstance(equity, Mapping) else {}
    publication = None
    try:
        publication = SQLiteFullUniverseScreeningStore(
            settings.full_universe_screening_database
        ).publication(cycle_identifier)
    except (OSError, RuntimeError, TypeError, ValueError):
        publication = None
    candidate_payloads = (
        tuple(item for item in getattr(publication, "candidate_payloads", ()) if isinstance(item, Mapping))
        if publication is not None
        else ()
    )
    queue = getattr(publication, "opportunity_queue_payload", {}) if publication is not None else {}
    ranked = queue.get("ranked", []) if isinstance(queue, Mapping) else []
    ranked = [item for item in ranked if isinstance(item, Mapping)] if isinstance(ranked, list) else []
    candidate_names = _candidate_name_map(candidate_payloads)
    strongest_symbol = "Unavailable"
    strongest_name = ""
    strongest_stage = "No company alternative was published"
    if ranked:
        strongest = ranked[0]
        strongest_symbol = _clean_text(strongest.get("symbol")).upper() or "Unavailable"
        candidate_identifier = _clean_text(strongest.get("candidate_identifier"))
        strongest_name = candidate_names.get(candidate_identifier, (strongest_symbol, strongest_symbol))[1]
        strongest_stage = "Reached the governed CIO opportunity queue"
    elif candidate_payloads:
        strongest_payload = max(
            candidate_payloads,
            key=lambda item: _safe_float(item.get("opportunity_edge")) or -10**9,
        )
        instrument = strongest_payload.get("instrument")
        if isinstance(instrument, Mapping):
            strongest_symbol = _clean_text(instrument.get("symbol")).upper() or "Unavailable"
            strongest_name = _clean_text(instrument.get("name")) or strongest_symbol
        strongest_stage = "Received complete candidate evidence but did not qualify"
    else:
        dynamic = _active_dynamic_instruments()
        if dynamic:
            strongest_symbol, strongest_name = dynamic[0]
            strongest_stage = "Received deeper company analysis but did not become a governed candidate"
    strongest_alternative = (
        strongest_symbol
        if strongest_symbol == "Unavailable" or not strongest_name or strongest_name == strongest_symbol
        else f"{strongest_symbol} — {strongest_name}"
    )
    qualified = _safe_int(state.get("qualified_candidate_count"))
    if qualified is None:
        qualified = len(ranked)
    candidate_count = _safe_int(state.get("candidate_count"))
    if candidate_count is None and publication is not None:
        candidate_count = _safe_int(getattr(publication, "candidate_count", None))
    return OpportunityScanSnapshot(
        state="available" if publication is not None else "partial",
        as_of=as_of,
        broad_assets_screened=_safe_int(equity_map.get("screened_asset_count")),
        snapshot_covered=_safe_int(equity_map.get("snapshot_covered_count")),
        companies_deepened=_safe_int(equity_map.get("selected_count")),
        governed_candidates=candidate_count,
        opportunities_reaching_cio=qualified,
        strongest_alternative=strongest_alternative,
        strongest_stage=strongest_stage,
        main_reason=_main_rejection_reason(publication),
        decision_reference=_clean_text(state.get("context_identifier")) or "Unavailable",
        detail=(
            "Broad U.S.-company discovery competes with the strategic cross-asset wrappers for capital. "
            "Counts describe process coverage, not investability or expected performance."
        ),
    )


def _count_label(value: int | None) -> str:
    return "Unavailable" if value is None else f"{value:,}"


def render_today_opportunity_scan(
    *,
    briefing: Mapping[str, Any] | None = None,
) -> None:
    snapshot = load_opportunity_scan()
    ui.page_header(
        "Opportunity scan",
        "How broadly the system searched, how far the strongest alternatives progressed, and why capital did or did not move.",
        "SCAN",
    )
    ui.metric_grid(
        (
            ("U.S. companies screened", _count_label(snapshot.broad_assets_screened), "Broad eligible universe"),
            ("Market snapshots", _count_label(snapshot.snapshot_covered), "Usable initial evidence"),
            ("Companies deepened", _count_label(snapshot.companies_deepened), "Full company analysis"),
            ("Reached CIO queue", _count_label(snapshot.opportunities_reaching_cio), "Qualified opportunities"),
        ),
        variant="today",
    )
    left, right = st.columns(2, gap="large")
    with left:
        ui.text_card(
            "Strongest alternative to cash",
            f"{snapshot.strongest_alternative}. {snapshot.strongest_stage}.",
        )
    with right:
        ui.text_card("Main reason capital did not advance", snapshot.main_reason)
    st.caption(
        f"Scan as of {ui.format_datetime(snapshot.as_of)} · production context {snapshot.decision_reference} · "
        f"CIO decision {_briefing_reference(briefing)}. {snapshot.detail}"
    )


def _accountability_db_path(settings: ApiSettings) -> Path:
    return settings.portfolio_database.with_name("opportunity_outcomes.db")


def summarize_accountability_events(
    decisions: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
) -> DecisionAccountabilitySnapshot:
    decision_ids = {
        _clean_text(item.get("candidate_identifier"))
        for item in decisions
        if _clean_text(item.get("candidate_identifier"))
    }
    outcome_ids = {
        _clean_text(item.get("candidate_identifier"))
        for item in outcomes
        if _clean_text(item.get("candidate_identifier"))
    }
    counts = Counter(_clean_text(item.get("outcome")) for item in outcomes)
    awaiting = max(0, len(decision_ids - outcome_ids))
    missed = counts["missed_opportunity"]
    avoided = counts["avoided_loss"]
    gains = counts["supported_gain"]
    losses = counts["supported_loss"]
    neutral = counts["neutral"]
    resolved = len(outcomes)
    if resolved == 0:
        lesson = (
            "No screening observation has matured yet. The ledger remains observation-only until "
            "the minimum evaluation window and a valid later price are available."
        )
    elif missed > avoided and missed >= max(gains, losses):
        lesson = (
            "Rejected candidates have produced more material upside surprises than avoided losses so far. "
            "Governance should examine whether qualification is becoming too conservative, without weakening evidence standards."
        )
    elif avoided > missed and avoided >= max(gains, losses):
        lesson = (
            "Rejected candidates have more often protected capital from subsequent losses than missed material gains. "
            "That supports selectivity, while the sample still requires continued observation."
        )
    elif gains > losses:
        lesson = (
            "Qualified opportunities have more often produced gains relative to contemporaneous cash than losses. "
            "This is process-accountability evidence, not a verified performance claim."
        )
    elif losses > gains:
        lesson = (
            "Qualified opportunities have produced more material losses than gains relative to cash. "
            "The evidence should prompt review of downside assumptions and qualification controls."
        )
    else:
        lesson = (
            "Matured outcomes are mixed. No single process conclusion is justified yet; continued observation "
            "and source-level review remain appropriate."
        )
    ordered = sorted(
        outcomes,
        key=lambda item: _parse_datetime(item.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return DecisionAccountabilitySnapshot(
        state="available",
        recorded_decisions=len(decision_ids),
        awaiting_evaluation=awaiting,
        avoided_losses=avoided,
        missed_opportunities=missed,
        supported_gains=gains,
        supported_losses=losses,
        neutral_outcomes=neutral,
        lesson=lesson,
        recent_outcomes=tuple(ordered[:8]),
        detail=(
            "Outcome classes compare later candidate returns with contemporaneous cash after the observation window. "
            "They do not feed back into the same decision or authorize execution."
        ),
    )


def load_decision_accountability() -> DecisionAccountabilitySnapshot:
    settings = _runtime_settings()
    if settings is None:
        return DecisionAccountabilitySnapshot(
            "unavailable", 0, 0, 0, 0, 0, 0, 0,
            "Decision accountability is available on the persistent operating host.",
            (),
            "Production settings are unavailable.",
        )
    path = _accountability_db_path(settings)
    if not path.exists():
        return DecisionAccountabilitySnapshot(
            "unavailable", 0, 0, 0, 0, 0, 0, 0,
            "The opportunity-cost ledger has not recorded a screening decision yet.",
            (),
            "The next complete broad-equity cycle will begin the append-only accountability record.",
        )
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                f"SELECT event_type, payload_json FROM {_OUTCOME_TABLE} ORDER BY sequence"
            ).fetchall()
    except (OSError, sqlite3.DatabaseError):
        return DecisionAccountabilitySnapshot(
            "degraded", 0, 0, 0, 0, 0, 0, 0,
            "The opportunity-cost ledger could not be read safely.",
            (),
            "The append-only record remains authoritative; the interface is temporarily incomplete.",
        )
    decisions: list[Mapping[str, Any]] = []
    outcomes: list[Mapping[str, Any]] = []
    for event_type, payload_json in rows:
        try:
            payload = json.loads(str(payload_json))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, Mapping):
            continue
        if event_type == "screening_decision":
            decisions.append(payload)
        elif event_type == "screening_outcome":
            outcomes.append(payload)
    return summarize_accountability_events(decisions, outcomes)


def _outcome_label(value: object) -> str:
    return _clean_text(value).replace("_", " ").title() or "Unavailable"


def render_history_decision_accountability() -> None:
    snapshot = load_decision_accountability()
    ui.page_header(
        "Decision accountability",
        "Whether rejected and qualified opportunities later became avoided losses, missed opportunities, supported gains, or supported losses relative to cash.",
        "LEARN",
    )
    ui.metric_grid(
        (
            ("Awaiting evaluation", f"{snapshot.awaiting_evaluation:,}", "Decision horizon not matured"),
            ("Avoided losses", f"{snapshot.avoided_losses:,}", "Rejected and later lagged cash"),
            ("Missed opportunities", f"{snapshot.missed_opportunities:,}", "Rejected and later beat cash"),
            ("Supported gains", f"{snapshot.supported_gains:,}", "Qualified and later beat cash"),
            ("Supported losses", f"{snapshot.supported_losses:,}", "Qualified and later lagged cash"),
            ("Neutral", f"{snapshot.neutral_outcomes:,}", "No material edge versus cash"),
        ),
        variant="history",
    )
    ui.callout_card(
        "What the record is teaching",
        snapshot.lesson,
        snapshot.detail,
    )
    if snapshot.recent_outcomes:
        with st.expander("Recent matured opportunity observations"):
            frame = pd.DataFrame(
                {
                    "Observed": ui.format_datetime(item.get("observed_at")),
                    "Symbol": item.get("symbol"),
                    "Original disposition": _outcome_label(item.get("disposition")),
                    "Outcome": _outcome_label(item.get("outcome")),
                    "Excess return vs cash": (
                        None
                        if _safe_float(item.get("excess_return_vs_cash")) is None
                        else f"{float(item['excess_return_vs_cash']):.2%}"
                    ),
                }
                for item in snapshot.recent_outcomes
            )
            st.dataframe(frame, use_container_width=True, hide_index=True)


def _format_time(value: datetime | None) -> str:
    return "Unavailable" if value is None else value.strftime("%b %d · %H:%M UTC")


def _economic_detail(dashboard: EconomicDashboardData) -> tuple[str, str]:
    readings = dashboard.readings
    if readings is None:
        return "Incomplete", _truncate(dashboard.status, 90)
    evaluated_at = _parse_datetime(getattr(readings, "evaluated_at", None))
    observation_dates = getattr(readings, "observation_dates", ())
    dates = [str(value) for _, value in observation_dates if str(value)] if isinstance(observation_dates, Sequence) else []
    latest_date = max(dates) if dates else "date unavailable"
    return "Current", f"Checked {_format_time(evaluated_at)} · latest source date {latest_date}"


def _scheduled_record_state(
    timestamp: datetime | None,
    *,
    now: datetime,
) -> tuple[str, str]:
    if timestamp is None:
        return "Incomplete", "No governed timestamp"
    zone = ZoneInfo(scheduler_timezone_name())
    record_date = timestamp.astimezone(zone).date()
    expected_date = operating_date(now)
    local_now = now.astimezone(zone)
    if record_date == expected_date:
        return "Current", _format_time(timestamp)
    if record_date < expected_date and local_now.hour < scheduler_hour() + 2:
        return "Awaiting refresh", _format_time(timestamp)
    return "Stale", _format_time(timestamp)


def build_freshness_entries(
    *,
    now: datetime,
    market: Mapping[str, Any],
    dashboard: EconomicDashboardData,
    public_snapshot: PublicEventSnapshot,
    briefing: Mapping[str, Any] | None,
    mandate: Mapping[str, Any] | None,
) -> tuple[FreshnessEntry, ...]:
    evaluated_at = now.astimezone(timezone.utc)
    market_status = _clean_text(market.get("status"))
    latest_quote = _parse_datetime(market.get("latest_quote_at"))
    market_open = market.get("market_open") is True
    if market_status not in {"connected", "partial"} or latest_quote is None:
        quote_state = "Incomplete"
    elif not market_open:
        quote_state = "Awaiting refresh"
    elif evaluated_at - latest_quote <= timedelta(minutes=15):
        quote_state = "Current"
    else:
        quote_state = "Stale"
    economic_state, economic_detail = _economic_detail(dashboard)
    interval_seconds = max(
        60,
        _safe_int(os.getenv("CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS"))
        or 1800,
    )
    public_time = public_snapshot.evaluated_at
    if public_snapshot.state != "available" or public_time is None:
        public_state = "Incomplete"
    elif evaluated_at - public_time <= timedelta(seconds=max(3600, interval_seconds * 2)):
        public_state = "Current"
    else:
        public_state = "Stale"
    briefing_time = _parse_datetime(briefing.get("as_of")) if isinstance(briefing, Mapping) else None
    cio_state, cio_detail = _scheduled_record_state(briefing_time, now=evaluated_at)
    portfolio_time = _parse_datetime(mandate.get("as_of")) if isinstance(mandate, Mapping) else None
    portfolio_state, portfolio_detail = _scheduled_record_state(portfolio_time, now=evaluated_at)
    return (
        FreshnessEntry("Market quotes", quote_state, _format_time(latest_quote)),
        FreshnessEntry("Economic data", economic_state, economic_detail),
        FreshnessEntry("Public events", public_state, _format_time(public_time)),
        FreshnessEntry("CIO conclusion", cio_state, cio_detail),
        FreshnessEntry("Portfolio valuation", portfolio_state, portfolio_detail),
    )


def render_information_freshness(
    *,
    briefing: Mapping[str, Any] | None,
    surface: str,
) -> None:
    now = datetime.now(timezone.utc)
    market = load_live_market_console()
    dashboard = load_dashboard_data()
    public_snapshot = load_public_event_snapshot()
    try:
        mandate = get_mandate_details(CANONICAL_PORTFOLIO_CODE)
    except (OSError, RuntimeError, TypeError, ValueError):
        mandate = None
    entries = build_freshness_entries(
        now=now,
        market=market,
        dashboard=dashboard,
        public_snapshot=public_snapshot,
        briefing=briefing,
        mandate=mandate,
    )
    st.caption("Information freshness and operating status")
    ui.metric_grid(
        tuple((item.label, item.state, item.detail) for item in entries),
        variant=surface,
    )
    st.caption(
        f"The CIO and canonical portfolio roll at {_schedule_label()}; market, economic, and public-event sources retain their own timestamps."
    )


__all__ = [
    "DecisionAccountabilitySnapshot",
    "FreshnessEntry",
    "OpportunityScanSnapshot",
    "build_freshness_entries",
    "classify_event_cio_relevance",
    "load_decision_accountability",
    "load_opportunity_scan",
    "operating_date",
    "render_environment_economic_brief",
    "render_history_decision_accountability",
    "render_information_freshness",
    "render_today_market_brief",
    "render_today_opportunity_scan",
    "scheduler_hour",
    "scheduler_timezone_name",
    "summarize_accountability_events",
]
