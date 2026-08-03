from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import environment_driver_education_runtime as education
import environment_story_placement_refinement as story


def _dashboard() -> SimpleNamespace:
    return SimpleNamespace(
        readings=SimpleNamespace(
            unemployment_rate=4.2,
            inflation_rate=3.73,
            federal_funds_rate=3.63,
            yield_curve_spread=0.45,
        ),
        snapshot=SimpleNamespace(
            growth=0.4,
            inflation=0.4,
            credit=0.1,
            volatility=0.1,
        ),
    )


def _market() -> dict[str, object]:
    return {
        "status": "partial",
        "quote_count": 12,
        "expected_quote_count": 15,
        "market_open": True,
    }


def test_each_number_has_a_current_market_takeaway_and_path() -> None:
    rows = education._driver_rows(story, _dashboard(), _market())
    by_name = {str(row["name"]): row for row in rows}

    growth = by_name["Growth"]
    assert growth["metric"] == "Unemployment rate · inverse growth signal"
    assert growth["value"] == "4.2%"
    assert "At 4.2%" in str(growth["takeaway"])
    assert "supports spending, earnings, cyclical equities, and credit" in str(
        growth["takeaway"]
    )
    assert growth["channel"] == "Labor demand → spending and earnings"
    assert growth["feeds"] == ("Equities", "Credit")
    assert growth["bias"] == 1.0

    inflation = by_name["Inflation"]
    assert inflation["value"] == "3.73%"
    assert "above the common 2% policy reference point" in str(
        inflation["takeaway"]
    )
    assert "Lower inflation generally supports bond" in str(
        inflation["takeaway"]
    )
    assert inflation["bias"] == -1.0

    rates = by_name["Rates"]
    assert rates["value"] == "3.63% · curve +0.45 pp"
    assert "upward sloping" in str(rates["takeaway"])
    assert "Lower rates typically support bonds" in str(rates["takeaway"])
    assert rates["bias"] == pytest.approx(-0.25)


def test_liquidity_uses_financial_conditions_not_quote_coverage_as_value() -> None:
    liquidity = next(
        row
        for row in education._driver_rows(story, _dashboard(), _market())
        if row["name"] == "Liquidity"
    )

    assert liquidity["value"] == "-0.10"
    assert liquidity["value"] != "12/15 quotes"
    assert "12/15-quote figure measures evidence coverage" in str(
        liquidity["takeaway"]
    )
    assert "not market liquidity" in str(liquidity["takeaway"])


def test_cross_asset_map_adds_a_current_market_effect_without_claiming_causation() -> None:
    drivers = education._driver_rows(story, _dashboard(), _market())
    rows = education._cross_asset_rows(drivers)
    by_name = {row["name"]: row for row in rows}

    assert by_name["Equities"]["drivers"] == "Growth + Rates + Liquidity"
    assert by_name["Bonds"]["drivers"] == "Inflation + Rates"
    assert by_name["Credit"]["drivers"] == "Growth + Liquidity"
    assert "Growth is supportive" in by_name["Equities"]["copy"]
    assert "Inflation is elevated pressure" in by_name["Bonds"]["copy"]

    assert by_name["Equities"]["today_label"] == "Cautiously supportive"
    assert by_name["Equities"]["today_tone"] == "positive"
    assert "supporting the earnings side" in by_name["Equities"]["today_copy"]

    assert by_name["Bonds"]["today_label"] == "Pressured"
    assert by_name["Bonds"]["today_tone"] == "negative"
    assert "challenging for longer-duration bonds" in by_name["Bonds"]["today_copy"]

    assert by_name["Credit"]["today_label"] == "Supportive"
    assert "corporate cash-flow" in by_name["Credit"]["today_copy"]

    assert by_name["Dollar & commodities"]["today_label"] == "Mixed cross-currents"
    assert by_name["Dollar & commodities"]["today_tone"] == "mixed"


def test_directional_labels_are_stable_at_decision_boundaries() -> None:
    assert education._bias_label(0.75) == "Supportive"
    assert education._bias_label(0.2) == "Cautiously supportive"
    assert education._bias_label(0.0) == "Mixed"
    assert education._bias_label(-0.2) == "Cautiously pressured"
    assert education._bias_label(-0.75) == "Pressured"


def test_install_replaces_the_environment_story_renderer_idempotently() -> None:
    module = ModuleType("environment_story_test_double")
    original = object()
    module._render_environment = original

    education.install(module)
    installed = module._render_environment
    assert callable(installed)
    assert installed is not original

    education.install(module)
    assert module._render_environment is installed


def test_active_entrypoints_install_education_before_surface_ownership() -> None:
    for path in (Path("app.py"), Path("render_app.py")):
        source = path.read_text(encoding="utf-8")
        assert "import environment_driver_education_runtime" in source
        education_index = source.index("environment_driver_education_runtime.install")
        surface_index = source.index("environment_story_placement_refinement.install")
        assert education_index < surface_index


def test_renderer_language_visibly_connects_cards_and_cross_asset_map() -> None:
    source = Path("environment_driver_education_runtime.py").read_text(
        encoding="utf-8"
    )

    assert "Market takeaway" in source
    assert "Market channel:" in source
    assert "Feeds into" in source
    assert "How this backdrop reaches markets" in source
    assert "Where the four readings meet" in source
    assert "point back to the driver cards above" in source
    assert "Connect the page from number to asset" in source
    assert "Affecting markets today" in source
    assert "near-term support or pressure implied by the" in source
    assert "current backdrop" in source
    assert "not proof that macro data caused" in source
    assert "every intraday price move" in source
    assert "Session " in source
    assert "live quotes" in source
