"""Presentation contracts for portfolio-first market and economic education."""

from pathlib import Path


def test_today_explains_daily_events_through_an_investment_lens() -> None:
    source = Path("concise_operating_intelligence_ui.py").read_text(encoding="utf-8")

    for phrase in (
        "Investment world today",
        "Daily investment synopsis",
        "Why investors care",
        "Portfolio connection",
        "What to watch next",
        "expected return, risk, or liquidity",
    ):
        assert phrase in source


def test_environment_connects_economic_data_to_the_portfolio() -> None:
    source = Path("concise_operating_intelligence_ui.py").read_text(encoding="utf-8")

    for phrase in (
        "Economy and investing",
        "Economic synopsis",
        "Inflation",
        "Unemployment",
        "Federal funds",
        "10Y − 2Y",
        "company earnings",
        "discount rates and financing costs",
    ):
        assert phrase in source


def test_reusable_lens_preserves_event_to_portfolio_hierarchy() -> None:
    source = Path("premium_ui.py").read_text(encoding="utf-8")

    assert "def investment_lens_card(" in source
    for label in (
        "What changed",
        "Why investors care",
        "Portfolio effect",
        "CIO response",
        "What to watch next",
    ):
        assert label in source


def test_history_research_is_compact_and_governance_first() -> None:
    source = Path("historical_replay_ui.py").read_text(encoding="utf-8")

    assert 'ui.page_header(' in source
    assert 'ui.metric_grid(' in source
    assert '"Governance boundary"' in source
    assert "cannot authorize execution or override the live CIO process" in source
    assert 'with st.expander("Replay cutoff detail", expanded=False)' in source
