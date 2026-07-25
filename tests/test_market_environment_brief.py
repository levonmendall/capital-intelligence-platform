"""Tests for the concise market-environment product surface."""

from __future__ import annotations

import json
from datetime import date

from monitoring import AlertLevel, PortfolioImpactDirection, RegimeMaterialChangeEngine
from reporting import (
    build_market_environment_brief,
    market_environment_brief_to_dict,
    render_market_environment_brief_json,
    render_market_environment_brief_markdown,
)
from tests.test_material_change_monitoring import (
    ChangedRegimeProvider,
    FIRST_AS_OF,
    SECOND_AS_OF,
    _decision,
    _run,
)


def test_daily_brief_is_simple_and_portfolio_oriented() -> None:
    run = _run(ChangedRegimeProvider(), as_of=FIRST_AS_OF)
    brief = build_market_environment_brief(run, _decision(run))

    assert brief.regime == "Goldilocks"
    assert "working view" in brief.headline
    assert brief.portfolio_direction is PortfolioImpactDirection.INCREASE_RISK
    assert brief.affected_exposures == ("diversified risk assets",)
    assert not brief.changed_materially
    assert not brief.should_alert


def test_silent_comparison_says_no_meaningful_change() -> None:
    previous = _run(ChangedRegimeProvider(), as_of=FIRST_AS_OF)
    current = _run(ChangedRegimeProvider(), as_of=SECOND_AS_OF)
    change = RegimeMaterialChangeEngine(clock=lambda: SECOND_AS_OF).compare(
        previous,
        current,
        _decision(previous),
        _decision(current),
    )

    brief = build_market_environment_brief(
        current,
        _decision(current),
        change=change,
    )

    assert brief.alert_level is AlertLevel.SILENT
    assert not brief.changed_materially
    assert brief.headline.startswith("No meaningful change")
    assert "current positioning view remains" in brief.summary


def test_material_change_surfaces_only_when_portfolio_relevant() -> None:
    previous = _run(ChangedRegimeProvider(), as_of=FIRST_AS_OF)
    current = _run(
        ChangedRegimeProvider(
            growth_value=95.0,
            current_date=date(2026, 1, 28),
        ),
        as_of=SECOND_AS_OF,
    )
    change = RegimeMaterialChangeEngine(clock=lambda: SECOND_AS_OF).compare(
        previous,
        current,
        _decision(previous),
        _decision(current),
    )

    brief = build_market_environment_brief(
        current,
        _decision(current),
        change=change,
    )

    assert brief.changed_materially
    assert brief.should_alert
    assert brief.headline == change.headline
    assert brief.summary == change.explanation
    assert brief.portfolio_direction is PortfolioImpactDirection.REDUCE_RISK


def test_environment_brief_renderers_are_schema_versioned() -> None:
    run = _run(ChangedRegimeProvider(), as_of=FIRST_AS_OF)
    brief = build_market_environment_brief(run, _decision(run))

    payload = market_environment_brief_to_dict(brief)
    assert payload["schema_version"] == "market-environment-brief.v1"
    assert json.loads(render_market_environment_brief_json(brief)) == payload

    markdown = render_market_environment_brief_markdown(brief)
    assert markdown.startswith(f"# {brief.headline}")
    assert "**Portfolio:**" in markdown
    assert "**Alert:** No" in markdown
