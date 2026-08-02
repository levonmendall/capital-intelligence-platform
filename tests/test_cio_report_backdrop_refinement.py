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
                "review_conditions": (
                    "Confirm whether lower energy prices persist",
                    "Monitor credit breadth",
                ),
            }
        },
        load_live_market_console=lambda: {
            "market_open": True,
            "quote_count": 14,
            "expected_quote_count": 15,
        },
    )


def test_current_market_backdrop_uses_governed_environment_and_live_market() -> None:
    backdrop = refinement._current_market_backdrop(_app(), briefing={})

    assert "U.S. session open" in backdrop
    assert "implementation coverage 14/15" in backdrop
    assert "Risk appetite improved" in backdrop
    assert "Oil declined" in backdrop
    assert "Disinflationary expansion" in backdrop


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

    backdrop = source.index('"Current market backdrop"')
    changed = source.index('"What changed"', backdrop)
    monitoring = source.index('"What the CIO is monitoring"', changed)
    posture = source.index('"Current portfolio posture"', monitoring)

    assert backdrop < changed < monitoring < posture


def test_shared_installer_activates_market_first_cio_report() -> None:
    source = Path("opportunity_funnel_ui_refinement.py").read_text(encoding="utf-8")

    assert "import cio_report_backdrop_refinement" in source
    assert (
        "cio_report_backdrop_refinement.install(portfolio_first_ui_refinement)"
        in source
    )
