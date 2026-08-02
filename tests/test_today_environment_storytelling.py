from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import environment_story_placement_refinement as storytelling


ROOT = Path(__file__).resolve().parents[1]


def test_final_storytelling_layer_owns_both_surfaces() -> None:
    source = (ROOT / "environment_story_placement_refinement.py").read_text(
        encoding="utf-8"
    )
    render_source = (ROOT / "render_app.py").read_text(encoding="utf-8")

    assert "app_impl._render_today = render_today" in source
    assert "app_impl._render_environment = render_environment" in source
    assert (
        render_source.index("surface_content_refinement.install(app_impl)")
        < render_source.index("environment_story_placement_refinement.install(app_impl)")
    )


def test_today_and_environment_have_distinct_information_ownership() -> None:
    source = (ROOT / "environment_story_placement_refinement.py").read_text(
        encoding="utf-8"
    )

    assert "What is moving the investment conversation" in source
    assert "What happened" in source
    assert "Why it matters" in source
    assert "How markets may react" in source
    assert "What to watch next" in source
    assert "Investor lesson" in source

    assert "Environment // structural conditions" in source
    assert "Growth" in source
    assert "Inflation" in source
    assert "Rates" in source
    assert "Liquidity" in source
    assert "How this backdrop reaches markets" in source
    assert "What would change the view" in source


def test_age_label_is_truthful_and_human_readable() -> None:
    now = datetime(2026, 8, 2, 15, 0, tzinfo=timezone.utc)

    assert storytelling._age_label(now - timedelta(minutes=18), now) == "verified 18m ago"
    assert storytelling._age_label(now - timedelta(hours=4), now) == "verified 4h ago"
    assert storytelling._age_label(None, now) == "time unavailable"


def test_investor_lesson_matches_transmission_channel() -> None:
    title, explanation = storytelling._lesson(
        SimpleNamespace(impact_channels=("policy", "discount_rate"))
    )

    assert title == "Discount rates"
    assert "future cash flows" in explanation


def test_environment_drivers_explain_market_sensitivity() -> None:
    readings = SimpleNamespace(
        unemployment_rate=4.2,
        inflation_rate=2.6,
        federal_funds_rate=4.5,
        yield_curve_spread=0.3,
    )
    snapshot = SimpleNamespace(
        growth=0.3,
        inflation=0.2,
        credit=-0.1,
        volatility=0.2,
    )
    dashboard = SimpleNamespace(readings=readings, snapshot=snapshot)
    market = {
        "status": "connected",
        "quote_count": 15,
        "expected_quote_count": 15,
    }

    cards = storytelling._drivers(dashboard, market)

    assert tuple(card[0] for card in cards) == ("Growth", "Inflation", "Rates", "Liquidity")
    assert cards[2][1] == "4.50% · curve +0.30 pp"
    assert cards[3][1] == "15/15 quotes"
    assert all(card[4] for card in cards)
