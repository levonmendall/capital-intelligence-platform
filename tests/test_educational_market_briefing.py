from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from educational_market_briefing_ui import (
    build_economic_event_items,
    build_today_items,
    economic_investment_implications,
    economic_portfolio_lens,
    economic_snapshot_summary,
)
from operating_intelligence_ui import operating_date
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
    assert "Interest-rate expectations" in items[0].portfolio_lens
    assert "Treasuries" in items[0].affected_investments
    assert "central-bank guidance" in items[0].what_to_watch


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
    assert "growth equities" in items[0].affected_investments


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
    implications = economic_investment_implications(readings)

    assert "unemployment 4.2%" in summary
    assert "10-year Treasury 4.40%" in summary
    assert "Cash and short-duration bonds" in lens
    assert "growth-stock valuations" in lens
    assert [title for title, _ in implications] == [
        "Rates, cash and bonds",
        "Equities and credit",
        "Growth and consumer sensitivity",
    ]


def test_app_places_connected_intelligence_at_surface_entry() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert "render_today_market_brief" in source
    assert "render_environment_economic_brief" in source
    assert "render_today_opportunity_scan" in source
    assert "render_history_decision_accountability" in source
    assert "render_information_freshness" in source
    assert "operating intelligence insertion point is unavailable" in source
    assert 'render_today_market_brief(briefing=briefing)\\n' in source
    assert 'render_environment_economic_brief(briefing=latest_briefing)\\n' in source


def test_daily_briefing_operating_date_rolls_at_seven_pacific(monkeypatch) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE", "America/Los_Angeles")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_SCHEDULER_HOUR", "7")
    before = datetime(2026, 7, 30, 13, 59, tzinfo=timezone.utc)
    after = datetime(2026, 7, 30, 14, 1, tzinfo=timezone.utc)

    assert operating_date(before).isoformat() == "2026-07-29"
    assert operating_date(after).isoformat() == "2026-07-30"


def test_briefing_copy_is_informative_educational_and_non_executing() -> None:
    source = Path("operating_intelligence_ui.py").read_text(encoding="utf-8")

    assert "What's happening today" in source
    assert "Economic context today" in source
    assert "What happened:" in source
    assert "Investment impact:" in source
    assert "Most affected:" in source
    assert "Watch next:" in source
    assert "rolls at {_schedule_label()}" in source
    assert "Educational context only" in source
    assert "headlines cannot alter the CIO conclusion or authorize a paper trade" in source
