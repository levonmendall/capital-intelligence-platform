from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import cio_report_backdrop_refinement as refinement


def _app() -> SimpleNamespace:
    return SimpleNamespace(
        _diagnostic_environment=lambda: {
            "environment": {
                "headline": "Risk appetite improved as geopolitical pressure eased",
                "summary": "Oil declined while equities and credit stabilized.",
                "regime": "Disinflationary expansion",
                "portfolio_impact": (
                    "Lower energy pressure helps margins, but the portfolio should wait "
                    "for breadth and credit confirmation."
                ),
                "review_conditions": (
                    "Confirm whether lower energy prices persist",
                    "Monitor credit breadth",
                ),
            }
        },
        load_live_market_console=lambda: {
            "status": "connected",
            "market_open": True,
            "quote_count": 14,
            "expected_quote_count": 15,
            "latest_quote_at": "2026-08-05T15:19:31+00:00",
            "detail": "Current provider-backed paper-market evidence is available.",
        },
        load_dashboard_data=lambda: SimpleNamespace(
            readings=SimpleNamespace(
                unemployment_rate=4.1,
                inflation_rate=2.35,
                federal_funds_rate=4.75,
                yield_curve_spread=0.28,
            ),
            data_source="FRED",
            status="Current",
        ),
    )


def _briefing() -> dict[str, object]:
    return {
        "material_developments": (
            "Energy prices eased after geopolitical pressure declined",
            "Credit markets stabilized while equity participation improved",
            "CIO action is no material change",
        ),
        "what_changed": "Market and economic evidence became more constructive",
        "why_it_matters": (
            "The environment is improving, but confirmation is not yet strong enough "
            "to justify a portfolio change."
        ),
        "what_to_watch": ("Watch equity breadth",),
        "evidence_that_changes_conclusion": (
            "A sustained improvement in credit and earnings expectations",
        ),
    }


def test_current_market_backdrop_discusses_governed_market_conditions() -> None:
    backdrop = refinement._current_market_backdrop(_app(), briefing=_briefing())

    assert "What's happening in markets now" in backdrop
    assert "U.S. session is open" in backdrop
    assert "14 of 15 governed implementation instruments" in backdrop
    assert "Aug 05, 2026 15:19 UTC" in backdrop
    assert "Risk appetite improved" in backdrop
    assert "Oil declined" in backdrop
    assert "Disinflationary expansion" in backdrop
    assert "inflation 2.35%" in backdrop
    assert "unemployment 4.1%" in backdrop
    assert "federal funds rate 4.75%" in backdrop
    assert "10-year minus 2-year curve +0.28 percentage points" in backdrop
    assert "Energy prices eased" in backdrop
    assert "Credit markets stabilized" in backdrop
    assert "Portfolio relevance" in backdrop
    assert "What to watch next" in backdrop
    assert "CIO action is no material change" not in backdrop


def test_market_discussion_labels_quote_coverage_as_implementation_data() -> None:
    backdrop = refinement._current_market_backdrop(_app(), briefing={})

    assert "implementation instruments have usable live quotes" in backdrop
    assert "market breadth 14/15" not in backdrop
    assert "rallied" not in backdrop
    assert "sold off" not in backdrop


def test_market_discussion_discloses_partial_provider_state() -> None:
    app = _app()
    app.load_live_market_console = lambda: {
        "status": "partial",
        "market_open": False,
        "quote_count": 9,
        "expected_quote_count": 15,
        "evaluated_at": "2026-08-05T16:00:00+00:00",
        "detail": "Only 9 of 15 instruments have usable top-of-book evidence.",
    }

    backdrop = refinement._current_market_backdrop(app, briefing={})

    assert "U.S. session is closed" in backdrop
    assert "9 of 15 governed implementation instruments" in backdrop
    assert "Data-status note" in backdrop
    assert "Only 9 of 15 instruments" in backdrop


def test_monitoring_combines_briefing_environment_and_existing_conditions() -> None:
    monitoring = refinement._monitoring_summary(
        _app(),
        {
            "what_to_watch": ("Monitor credit breadth", "Watch oil volatility"),
            "evidence_that_changes_conclusion": (
                "Confirm whether lower energy prices persist",
            ),
        },
        "Monitor credit breadth",
    )

    assert monitoring.count("Monitor credit breadth") == 1
    assert "Watch oil volatility" in monitoring
    assert "Confirm whether lower energy prices persist" in monitoring


def test_cio_report_starts_with_backdrop_change_and_monitoring() -> None:
    source = Path("cio_report_backdrop_refinement.py").read_text(encoding="utf-8")

    reordered = source.index("reordered = (")
    backdrop = source.index('"Current market backdrop"', reordered)
    changed_row = source.index("\n                changed,", backdrop)
    monitoring = source.index('"What the CIO is monitoring"', changed_row)
    posture = source.index('"Current portfolio posture"', monitoring)

    assert reordered < backdrop < changed_row < monitoring < posture


def test_shared_installer_activates_market_first_cio_report() -> None:
    source = Path("opportunity_funnel_ui_refinement.py").read_text(encoding="utf-8")

    assert "import cio_report_backdrop_refinement" in source
    assert (
        "cio_report_backdrop_refinement.install(portfolio_first_ui_refinement)"
        in source
    )
