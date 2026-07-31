from __future__ import annotations

from pathlib import Path


def test_app_uses_synopsis_first_operating_presenter() -> None:
    source = Path("app_impl.py").read_text(encoding="utf-8")

    assert "from concise_operating_intelligence_ui import (" in source
    assert "render_today_market_brief" in source
    assert "render_environment_economic_brief" in source
    assert "render_today_opportunity_scan" in source
    assert "render_history_decision_accountability" in source
    assert "render_information_freshness" in source


def test_information_heavy_sections_are_collapsed_by_default() -> None:
    source = Path("concise_operating_intelligence_ui.py").read_text(encoding="utf-8")

    assert 'with st.expander("Explore today\'s investment context", expanded=False)' in source
    assert 'with st.expander("Explore the economic investment context", expanded=False)' in source
    assert 'with st.expander("View opportunity scan detail")' in source
    assert 'with st.expander("View decision-accountability detail")' in source
    assert 'with st.expander("Information freshness details")' in source


def test_every_visible_synopsis_is_portfolio_first() -> None:
    source = Path("concise_operating_intelligence_ui.py").read_text(encoding="utf-8")

    assert '"Daily investment synopsis"' in source
    assert '"Economic synopsis"' in source
    assert '"Opportunity synopsis"' in source
    assert '"Accountability synopsis"' in source
    assert source.count("Portfolio impact:") >= 4
    assert source.count("CIO action:") >= 3
    assert "headlines cannot alter the CIO conclusion or authorize a paper trade" in source
    assert "it cannot" in source
    assert "change current holdings or authorize execution" in source
