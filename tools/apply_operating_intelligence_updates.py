from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def update_app() -> None:
    path = Path("app.py")
    replace_once(
        path,
        '''from educational_market_briefing_ui import (
    render_environment_economic_brief,
    render_today_market_brief,
)
''',
        '''from operating_intelligence_ui import (
    render_environment_economic_brief,
    render_history_decision_accountability,
    render_information_freshness,
    render_today_market_brief,
    render_today_opportunity_scan,
)
''',
        "operating intelligence import",
    )
    replace_once(
        path,
        '''render_today_market_brief(
render_environment_economic_brief(
authenticated_principal
''',
        '''render_today_market_brief(
render_environment_economic_brief(
render_today_opportunity_scan(
render_history_decision_accountability(
render_information_freshness(
authenticated_principal
''',
        "entrypoint contract",
    )
    replace_once(
        path,
        '''# Put the daily educational brief immediately below the hero on the two
# information surfaces. The original function anchor remains in the replacement so
# the live-fragment decorator can still be installed later in this entrypoint.
_educational_briefing_insertions = (
    (
        "def _render_today() -> None:\\n",
        "def _render_today() -> None:\\n"
        "    render_today_market_brief()\\n\\n",
    ),
    (
        "def _render_environment() -> None:\\n",
        "def _render_environment() -> None:\\n"
        "    render_environment_economic_brief()\\n\\n",
    ),
)
for _brief_anchor, _brief_replacement in _educational_briefing_insertions:
    _replace_source_once(
        _brief_anchor,
        _brief_replacement,
        "educational briefing insertion point is unavailable",
    )

''',
        '''# Place connected educational and operating intelligence immediately after
# each surface loads its canonical records. The hero is rendered before the surface
# function is called, so these blocks are the first information beneath it.
_operating_intelligence_insertions = (
    (
        '    _today_construction = _latest("portfolio_construction")\\n\\n',
        '    _today_construction = _latest("portfolio_construction")\\n'
        '    _today_mandate = get_mandate_details(CANONICAL_PORTFOLIO_CODE)\\n'
        '    render_today_market_brief(briefing=briefing)\\n'
        '    render_information_freshness(\\n'
        '        briefing=briefing, surface="today", mandate=_today_mandate\\n'
        '    )\\n'
        '    render_today_opportunity_scan(briefing=briefing)\\n\\n',
    ),
    (
        '    latest_briefing = _latest("daily_cio_briefing")\\n\\n',
        '    latest_briefing = _latest("daily_cio_briefing")\\n'
        '    _environment_mandate = get_mandate_details(CANONICAL_PORTFOLIO_CODE)\\n'
        '    render_environment_economic_brief(briefing=latest_briefing)\\n'
        '    render_information_freshness(\\n'
        '        briefing=latest_briefing, surface="environment", mandate=_environment_mandate\\n'
        '    )\\n\\n',
    ),
    (
        '    briefing = _latest("daily_cio_briefing")\\n'
        '    mandate = get_mandate_details(CANONICAL_PORTFOLIO_CODE)\\n',
        '    briefing = _latest("daily_cio_briefing")\\n'
        '    mandate = get_mandate_details(CANONICAL_PORTFOLIO_CODE)\\n'
        '    render_information_freshness(\\n'
        '        briefing=briefing, surface="portfolio", mandate=mandate\\n'
        '    )\\n',
    ),
    (
        '    trades = get_trade_history(limit=250)\\n\\n',
        '    trades = get_trade_history(limit=250)\\n'
        '    _history_mandate = get_mandate_details(CANONICAL_PORTFOLIO_CODE)\\n'
        '    render_information_freshness(\\n'
        '        briefing=(briefings[0] if briefings else None),\\n'
        '        surface="history",\\n'
        '        mandate=_history_mandate,\\n'
        '    )\\n\\n',
    ),
    (
        '    with st.expander("How the History surface works"):\\n',
        '    render_history_decision_accountability()\\n\\n'
        '    with st.expander("How the History surface works"):\\n',
    ),
)
for _intelligence_anchor, _intelligence_replacement in _operating_intelligence_insertions:
    _replace_source_once(
        _intelligence_anchor,
        _intelligence_replacement,
        "operating intelligence insertion point is unavailable",
    )

''',
        "operating intelligence insertion block",
    )


def update_economic_snapshot() -> None:
    path = Path("providers/economic_snapshot.py")
    replace_once(
        path,
        "from dataclasses import dataclass\n",
        "from dataclasses import dataclass\nfrom datetime import datetime, timezone\n",
        "economic datetime import",
    )
    replace_once(
        path,
        '''    federal_funds_rate: float

    @property
''',
        '''    federal_funds_rate: float
    evaluated_at: datetime | None = None
    observation_dates: tuple[tuple[str, str], ...] = ()

    @property
''',
        "economic metadata fields",
    )
    replace_once(
        path,
        '''    unemployment = fred.get_latest_value(
        SERIES["unemployment"]
    ).value

    inflation_observations = fred.get_observations(
        SERIES["inflation"],
        limit=14,
    )

    ten_year = fred.get_latest_value(
        SERIES["ten_year"]
    ).value

    two_year = fred.get_latest_value(
        SERIES["two_year"]
    ).value

    fed_funds = fred.get_latest_value(
        SERIES["fed_funds"]
    ).value

    latest_cpi = inflation_observations[0].value
''',
        '''    unemployment_observation = fred.get_latest_value(SERIES["unemployment"])
    unemployment = unemployment_observation.value

    inflation_observations = fred.get_observations(
        SERIES["inflation"],
        limit=14,
    )

    ten_year_observation = fred.get_latest_value(SERIES["ten_year"])
    ten_year = ten_year_observation.value

    two_year_observation = fred.get_latest_value(SERIES["two_year"])
    two_year = two_year_observation.value

    fed_funds_observation = fred.get_latest_value(SERIES["fed_funds"])
    fed_funds = fed_funds_observation.value

    latest_cpi = inflation_observations[0].value
''',
        "economic observation capture",
    )
    replace_once(
        path,
        '''        federal_funds_rate=fed_funds,
    )
''',
        '''        federal_funds_rate=fed_funds,
        evaluated_at=datetime.now(timezone.utc),
        observation_dates=(
            (SERIES["unemployment"], unemployment_observation.date),
            (SERIES["inflation"], inflation_observations[0].date),
            (SERIES["ten_year"], ten_year_observation.date),
            (SERIES["two_year"], two_year_observation.date),
            (SERIES["fed_funds"], fed_funds_observation.date),
        ),
    )
''',
        "economic reading metadata",
    )


def update_educational_module() -> None:
    path = Path("educational_market_briefing_ui.py")
    replace_once(
        path,
        '''_RECENT_WINDOW = timedelta(hours=24)
_DAILY_TIMEZONE = ZoneInfo("America/Los_Angeles")
_DAILY_ROLLOVER_HOUR = 5
''',
        '''_RECENT_WINDOW = timedelta(hours=24)
try:
    _DAILY_TIMEZONE = ZoneInfo(
        os.getenv("CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE", "America/Los_Angeles")
    )
except Exception:
    _DAILY_TIMEZONE = ZoneInfo("America/Los_Angeles")
try:
    _DAILY_ROLLOVER_HOUR = int(
        os.getenv("CAPITAL_INTELLIGENCE_SCHEDULER_HOUR", "7")
    )
except ValueError:
    _DAILY_ROLLOVER_HOUR = 7
if not 0 <= _DAILY_ROLLOVER_HOUR <= 23:
    _DAILY_ROLLOVER_HOUR = 7
''',
        "educational scheduler settings",
    )
    replace_once(
        path,
        '''    """Return the Pacific operating date that rolls at the 5:00 AM CIO cycle."""
''',
        '''    """Return the scheduler-local operating date for the configured CIO cycle."""
''',
        "educational date docstring",
    )
    replace_once(
        path,
        '''        "The daily operating date rolls at 5:00 AM Pacific and the source file is re-read as new governed records arrive."
''',
        '''        f"The daily operating date rolls at {_DAILY_ROLLOVER_HOUR:02d}:00 in {_DAILY_TIMEZONE.key} and the source file is re-read as new governed records arrive."
''',
        "educational caption schedule",
    )


def update_production_state() -> None:
    path = Path("production_context_publication_governed.py")
    replace_once(
        path,
        '''                "screened_asset_count": discovery.screened_asset_count,
                "snapshot_covered_count": discovery.snapshot_covered_count,
                "selected_count": len(discovery.selected),
''',
        '''                "screened_asset_count": discovery.screened_asset_count,
                "snapshot_covered_count": discovery.snapshot_covered_count,
                "deep_shortlist_count": discovery.deep_shortlist_count,
                "selected_count": len(discovery.selected),
''',
        "deep shortlist publication",
    )


def update_operating_module() -> None:
    path = Path("operating_intelligence_ui.py")
    replace_once(
        path,
        "from core.portfolio import get_mandate_details\n",
        "",
        "remove direct portfolio import",
    )
    replace_once(
        path,
        '''            if source_url is not None:
                st.markdown(f"[Read original source]({source_url})")
''',
        '''            if source_url is not None:
                st.link_button("Read original source", source_url)
''',
        "safe source link",
    )
    replace_once(
        path,
        '''        companies_deepened=_safe_int(equity_map.get("selected_count")),
''',
        '''        companies_deepened=(
            _safe_int(equity_map.get("deep_shortlist_count"))
            or _safe_int(equity_map.get("selected_count"))
        ),
''',
        "deep shortlist read",
    )
    replace_once(
        path,
        '''def render_information_freshness(
    *,
    briefing: Mapping[str, Any] | None,
    surface: str,
) -> None:
''',
        '''def render_information_freshness(
    *,
    briefing: Mapping[str, Any] | None,
    surface: str,
    mandate: Mapping[str, Any] | None = None,
) -> None:
''',
        "freshness mandate parameter",
    )
    replace_once(
        path,
        '''    try:
        mandate = get_mandate_details(CANONICAL_PORTFOLIO_CODE)
    except (OSError, RuntimeError, TypeError, ValueError):
        mandate = None
    entries = build_freshness_entries(
''',
        '''    entries = build_freshness_entries(
''',
        "remove direct mandate lookup",
    )
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        "from portfolio.constants import CANONICAL_PORTFOLIO_CODE\n",
        "",
        1,
    )
    path.write_text(source, encoding="utf-8")


def update_existing_tests() -> None:
    path = Path("tests/test_educational_market_briefing.py")
    replace_once(
        path,
        '''def test_app_places_briefs_immediately_at_surface_entry() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert "render_today_market_brief" in source
    assert "render_environment_economic_brief" in source
    assert "educational briefing insertion point is unavailable" in source
    today_anchor = '"def _render_today() -> None:\\n"'
    environment_anchor = '"def _render_environment() -> None:\\n"'
    assert today_anchor in source
    assert environment_anchor in source
    assert source.index(today_anchor) < source.index(
        "# Refresh the active operating surface"
    )
    assert 'render_today_market_brief()\\n\\n' in source
    assert 'render_environment_economic_brief()\\n\\n' in source


def test_daily_briefing_operating_date_rolls_at_five_pacific() -> None:
    before = datetime(2026, 7, 30, 11, 59, tzinfo=timezone.utc)
    after = datetime(2026, 7, 30, 12, 1, tzinfo=timezone.utc)

    assert daily_briefing_date(before) == "2026-07-29"
    assert daily_briefing_date(after) == "2026-07-30"
''',
        '''def test_app_places_connected_briefs_immediately_at_surface_entry() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert "render_today_market_brief" in source
    assert "render_environment_economic_brief" in source
    assert "render_today_opportunity_scan" in source
    assert "render_history_decision_accountability" in source
    assert "render_information_freshness" in source
    assert "operating intelligence insertion point is unavailable" in source
    assert 'render_today_market_brief(briefing=briefing)\\n' in source
    assert 'render_environment_economic_brief(briefing=latest_briefing)\\n' in source


def test_daily_briefing_operating_date_rolls_at_configured_seven_pacific(monkeypatch) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_SCHEDULER_HOUR", "7")
    before = datetime(2026, 7, 30, 13, 59, tzinfo=timezone.utc)
    after = datetime(2026, 7, 30, 14, 1, tzinfo=timezone.utc)

    assert daily_briefing_date(before) == "2026-07-29"
    assert daily_briefing_date(after) == "2026-07-30"
''',
        "existing integration and schedule tests",
    )
    replace_once(
        path,
        '''    source = Path("educational_market_briefing_ui.py").read_text(encoding="utf-8")
''',
        '''    source = Path("operating_intelligence_ui.py").read_text(encoding="utf-8")
''',
        "copy source module",
    )
    replace_once(
        path,
        '''    assert "rolls at 5:00 AM Pacific" in source
''',
        '''    assert "rolls at {_schedule_label()}" in source
''',
        "copy schedule assertion",
    )


def main() -> None:
    update_app()
    update_economic_snapshot()
    update_educational_module()
    update_production_state()
    update_operating_module()
    update_existing_tests()


if __name__ == "__main__":
    main()
