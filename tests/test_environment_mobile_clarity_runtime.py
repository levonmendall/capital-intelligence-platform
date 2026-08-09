from __future__ import annotations

from pathlib import Path

import environment_mobile_clarity_runtime as clarity


def _drivers() -> tuple[dict[str, object], ...]:
    return (
        {
            "name": "Growth",
            "metric": "Unemployment rate · inverse growth signal",
            "value": "4.1%",
            "state": "Supportive",
            "bias": 1.0,
            "takeaway": "Growth remains supportive while direction still matters.",
            "channel": "Labor demand → spending and earnings",
            "sensitive": "Cyclical equities, small caps, consumer sectors, and credit.",
            "feeds": ("Equities", "Credit"),
        },
        {
            "name": "Inflation",
            "metric": "Inflation rate",
            "value": "3.73%",
            "state": "Elevated pressure",
            "bias": -1.0,
            "takeaway": "Inflation remains above the common policy reference point.",
            "channel": "Prices → policy expectations and margins",
            "sensitive": "Bonds, growth equities, commodities, and inflation hedges.",
            "feeds": ("Bonds", "Equities", "Dollar & commodities"),
        },
        {
            "name": "Rates",
            "metric": "Policy rate · yield-curve spread",
            "value": "3.63% · curve +0.44 pp",
            "state": "Upward curve",
            "bias": -0.25,
            "takeaway": "Financing costs remain meaningful despite an upward curve.",
            "channel": "Financing cost → bond prices and valuations",
            "sensitive": "Treasuries, long-duration equities, housing, banks, and the dollar.",
            "feeds": ("Equities", "Bonds", "Dollar & commodities"),
        },
        {
            "name": "Liquidity",
            "metric": "Credit-and-volatility financial-conditions composite",
            "value": "+0.03",
            "state": "Mixed",
            "bias": 0.0,
            "takeaway": "Financial conditions are mixed.",
            "channel": "Funding conditions → spreads and risk appetite",
            "sensitive": "Credit spreads, smaller companies, volatility, and crowded positions.",
            "feeds": ("Credit", "Equities"),
        },
    )


def _markets() -> tuple[dict[str, str], ...]:
    return (
        {
            "name": "Equities",
            "drivers": "Growth + Rates + Liquidity",
            "copy": "Structural equity relationship.",
            "today_label": "Cautiously supportive",
            "today_tone": "positive",
            "today_copy": "Current equity interpretation.",
        },
        {
            "name": "Bonds",
            "drivers": "Inflation + Rates",
            "copy": "Structural bond relationship.",
            "today_label": "Pressured",
            "today_tone": "negative",
            "today_copy": "Current bond interpretation.",
        },
        {
            "name": "Credit",
            "drivers": "Growth + Liquidity",
            "copy": "Structural credit relationship.",
            "today_label": "Supportive",
            "today_tone": "positive",
            "today_copy": "Current credit interpretation.",
        },
        {
            "name": "Dollar & commodities",
            "drivers": "Rates + Inflation + Growth",
            "copy": "Structural currency and commodity relationship.",
            "today_label": "Mixed cross-currents",
            "today_tone": "mixed",
            "today_copy": "Current currency and commodity interpretation.",
        },
    )


def test_environment_summary_leads_with_one_integrated_conclusion() -> None:
    title, copy = clarity._environment_summary(_drivers(), _markets())

    assert title == "Growth-supportive, but rate-sensitive"
    assert "growth is supportive" in copy.lower()
    assert "inflation is elevated pressure" in copy.lower()
    assert "equities cautiously supportive" in copy.lower()
    assert "bonds pressured" in copy.lower()
    assert "credit supportive" in copy.lower()


def test_default_cards_are_compact_and_keep_full_detail_out_of_primary_grid() -> None:
    driver_html = clarity._compact_driver_cards(_drivers())
    market_html = clarity._compact_market_cards(_markets())

    assert driver_html.count('class="ci-driver"') == 4
    assert "Market takeaway" not in driver_html
    assert "Most sensitive" not in driver_html
    assert "Labor demand → spending and earnings" in driver_html
    assert market_html.count('class="ci-market"') == 4
    assert "Cautiously supportive" in market_html
    assert "Current equity interpretation" not in market_html


def test_environment_runtime_is_presentation_only_and_renders_html_explicitly() -> None:
    source = Path("environment_mobile_clarity_runtime.py").read_text(encoding="utf-8")

    assert "unsafe_allow_html=True" in source
    assert "Explore economic driver detail" in source
    assert "Explore cross-asset detail" in source
    assert "How to read this backdrop and what could change it" in source
    assert "Sources and supporting market data" in source
    assert "render_information_freshness" not in source
    assert "<section class=\"ci-learning-shell\"" not in source
    assert "st.code(" not in source
    assert "authorize real money" in source


def test_final_route_boundary_installs_environment_clarity_before_surface_guard() -> None:
    source = Path("surface_route_isolation_runtime.py").read_text(encoding="utf-8")

    install = source.index("environment_mobile_clarity_runtime.install(story_ui)")
    guard = source.index('_guard_story_renderer(story_ui, "_render_environment", "Environment")')

    assert "import environment_mobile_clarity_runtime" in source
    assert install < guard
