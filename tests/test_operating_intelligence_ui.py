from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from educational_market_briefing_ui import EducationalBriefingItem, PublicEventSnapshot
from intelligence.provider import load_sample_snapshot
from operating_intelligence_ui import (
    build_freshness_entries,
    classify_event_cio_relevance,
    summarize_accountability_events,
)
from providers.economic_snapshot import EconomicDashboardData, EconomicReadings


def _item(title: str) -> EducationalBriefingItem:
    return EducationalBriefingItem(
        title=title,
        summary=f"Public reporting about {title}.",
        portfolio_lens="Rates and valuations may respond.",
        affected_investments="Treasuries, growth equities",
        what_to_watch="Treasury yields",
        source="Official source",
        source_type="Official",
        published_at=datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc),
        impact_channels=("policy", "discount_rate"),
    )


def test_event_relevance_requires_visible_cio_lineage() -> None:
    material = classify_event_cio_relevance(
        _item("Federal Reserve policy communication"),
        {
            "material_developments": [
                "Federal Reserve policy communication changed the rate outlook."
            ],
            "decision_identifier": "decision-1",
        },
    )
    advanced = classify_event_cio_relevance(
        _item("ACME earnings update"),
        {
            "candidate_symbol": "ACME",
            "candidate_identifier": "candidate:acme",
            "decision_identifier": "decision-2",
        },
    )
    monitored = classify_event_cio_relevance(
        _item("Commodity shipping disruption"),
        {
            "portfolio_decision": "Maintain cash.",
            "decision_identifier": "decision-3",
        },
    )

    assert material.startswith("Material")
    assert advanced.startswith("Advanced")
    assert monitored.startswith("Monitored")


def test_accountability_summary_separates_each_outcome_class() -> None:
    decisions = [
        {"candidate_identifier": f"candidate-{index}"}
        for index in range(1, 7)
    ]
    outcomes = [
        {"candidate_identifier": "candidate-1", "outcome": "avoided_loss"},
        {"candidate_identifier": "candidate-2", "outcome": "missed_opportunity"},
        {"candidate_identifier": "candidate-3", "outcome": "supported_gain"},
        {"candidate_identifier": "candidate-4", "outcome": "supported_loss"},
        {"candidate_identifier": "candidate-5", "outcome": "neutral"},
    ]

    summary = summarize_accountability_events(decisions, outcomes)

    assert summary.awaiting_evaluation == 1
    assert summary.avoided_losses == 1
    assert summary.missed_opportunities == 1
    assert summary.supported_gains == 1
    assert summary.supported_losses == 1
    assert summary.neutral_outcomes == 1
    assert "verified performance" not in summary.lesson.lower()


def test_freshness_strip_distinguishes_independent_information_clocks(monkeypatch) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE", "America/Los_Angeles")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_SCHEDULER_HOUR", "7")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS", "1800")
    now = datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc)
    readings = EconomicReadings(
        unemployment_rate=4.2,
        inflation_rate=3.0,
        ten_year_yield=4.3,
        two_year_yield=4.1,
        federal_funds_rate=4.5,
        evaluated_at=now - timedelta(minutes=10),
        observation_dates=(("DGS10", "2026-07-29"),),
    )
    dashboard = EconomicDashboardData(
        snapshot=load_sample_snapshot(),
        readings=readings,
        data_source="Live FRED data",
        status="Connected",
    )
    entries = build_freshness_entries(
        now=now,
        market={
            "status": "connected",
            "market_open": True,
            "latest_quote_at": (now - timedelta(minutes=2)).isoformat(),
        },
        dashboard=dashboard,
        public_snapshot=PublicEventSnapshot(
            (),
            now - timedelta(minutes=20),
            "available",
            "Available",
        ),
        briefing={"as_of": (now - timedelta(hours=2)).isoformat()},
        mandate={"as_of": (now - timedelta(hours=1)).isoformat()},
    )

    states = {item.label: item.state for item in entries}
    assert states == {
        "Market quotes": "Current",
        "Economic data": "Current",
        "Public events": "Current",
        "CIO conclusion": "Current",
        "Portfolio valuation": "Current",
    }


def test_source_traceability_and_opportunity_scan_remain_non_executing() -> None:
    source = Path("operating_intelligence_ui.py").read_text(encoding="utf-8")

    assert "Read original source" in source
    assert 'parsed.scheme not in {"http", "https"}' in source
    assert "Opportunity scan" in source
    assert "Strongest alternative to cash" in source
    assert "Counts describe process coverage, not investability or expected performance" in source
    assert "never grants candidate, sizing, construction" in source
