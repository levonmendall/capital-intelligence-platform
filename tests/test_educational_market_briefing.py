from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from educational_market_briefing_ui import (
    build_economic_event_items,
    build_today_items,
    economic_portfolio_lens,
    economic_snapshot_summary,
)
from providers.economic_snapshot import EconomicReadings


def _record(
    *,
    identifier: str,
    topic: str,
    published_at: datetime,
    channels: tuple[str, ...],
    provider: str,
    source_type: str,
    tags: tuple[str, ...] = (),
    reliability: float = 0.9,
    relevance: float = 0.9,
    materiality: float = 0.8,
) -> dict[str, object]:
    timestamp = published_at.isoformat()
    return {
        "identifier": identifier,
        "canonical_event_identifier": identifier,
        "topic": topic,
        "summary": f"Concise public summary for {topic}.",
        "event_at": timestamp,
        "published_at": timestamp,
        "available_at": timestamp,
        "impact_channels": list(channels),
        "tags": list(tags),
        "reliability": reliability,
        "relevance": relevance,
        "materiality": materiality,
        "independence": 0.9,
        "provenance": {
            "provider": provider,
            "source_type": source_type,
        },
    }


def test_today_digest_prefers_recent_governed_events_and_removes_noise() -> None:
    now = datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc)
    records = (
        _record(
            identifier="fed",
            topic="Federal Reserve policy communication",
            published_at=now - timedelta(hours=2),
            channels=("policy", "liquidity"),
            provider="Federal Reserve Board",
            source_type="official",
        ),
        _record(
            identifier="news",
            topic="Global supply disruption develops",
            published_at=now - timedelta(hours=1),
            channels=("supply", "commodity"),
            provider="GDELT",
            source_type="alternative",
            reliability=0.55,
            relevance=0.7,
            materiality=0.45,
        ),
        _record(
            identifier="stale",
            topic="Old market event",
            published_at=now - timedelta(days=3),
            channels=("growth",),
            provider="Official archive",
            source_type="official",
        ),
        _record(
            identifier="ofac",
            topic="OFAC sanctions listing: Example Entity",
            published_at=now - timedelta(minutes=5),
            channels=("geopolitical", "regulation"),
            provider="OFAC",
            source_type="official",
            tags=("sanctions-list",),
        ),
    )

    items = build_today_items(records, now=now)

    assert [item.title for item in items] == [
        "Federal Reserve policy communication",
        "Global supply disruption develops",
    ]
    assert all("OFAC sanctions listing" not in item.title for item in items)
    assert "Rates, bond prices" in items[0].portfolio_lens


def test_environment_event_digest_keeps_economic_channels_only() -> None:
    now = datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc)
    records = (
        _record(
            identifier="inflation",
            topic="Inflation release updates the policy debate",
            published_at=now - timedelta(hours=3),
            channels=("inflation", "policy"),
            provider="Official statistics agency",
            source_type="official",
        ),
        _record(
            identifier="cyber",
            topic="Cyber incident affects one company",
            published_at=now - timedelta(hours=1),
            channels=("cyber", "operational"),
            provider="Cyber authority",
            source_type="official",
        ),
    )

    items = build_economic_event_items(records, now=now)

    assert len(items) == 1
    assert items[0].title == "Inflation release updates the policy debate"


def test_economic_context_explains_readings_and_portfolio_channels() -> None:
    readings = EconomicReadings(
        unemployment_rate=4.2,
        inflation_rate=3.1,
        ten_year_yield=4.4,
        two_year_yield=4.0,
        federal_funds_rate=4.5,
    )

    summary = economic_snapshot_summary(readings)
    lens = economic_portfolio_lens(readings)

    assert "unemployment 4.2%" in summary
    assert "10-year Treasury 4.40%" in summary
    assert "cash and short-duration bonds" in lens
    assert "cyclical earnings" in lens


def test_app_wires_briefs_into_today_and_environment_before_process_detail() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert "render_today_market_brief" in source
    assert "render_environment_economic_brief" in source
    assert "educational briefing insertion point is unavailable" in source


def test_briefing_copy_is_informative_educational_and_non_executing() -> None:
    source = Path("educational_market_briefing_ui.py").read_text(encoding="utf-8")

    assert "What's happening today" in source
    assert "Economic context today" in source
    assert "How it can affect portfolios" in source
    assert "Educational context only" in source
    assert "does not alter the CIO conclusion or authorize a paper trade" in source
