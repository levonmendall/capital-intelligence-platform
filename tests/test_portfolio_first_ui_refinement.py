from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import portfolio_first_ui_refinement as refinement


def test_portfolio_is_first_primary_surface() -> None:
    app = SimpleNamespace(
        PRIMARY_SURFACES=["Today", "Environment", "Portfolio", "History"],
        render_navigation=lambda options: (options[0], True),
        _render_portfolio=lambda dependencies, *, principal: None,
    )

    refinement.install(app)

    assert app.PRIMARY_SURFACES == ["Portfolio", "Today", "Environment", "History"]
    assert callable(app.render_navigation)
    assert callable(app._render_portfolio)


def test_portfolio_hierarchy_places_capital_before_cio_report() -> None:
    source = Path("portfolio_first_ui_refinement.py").read_text(encoding="utf-8")

    capital = source.index("_capital_structure(app_impl, mandate=mandate)")
    cio_report = source.index("_render_cio_report(", capital)
    remaining = source.index("_render_remaining_portfolio(", cio_report)

    assert capital < cio_report < remaining
    assert 'with st.expander("CIO report", expanded=False):' in source
    assert 'default="Portfolio" if "Portfolio" in choices else choices[0]' in source
    assert 'key=_NAVIGATION_KEY' in source


def test_existing_portfolio_controls_are_preserved_after_new_opening() -> None:
    source = Path("portfolio_first_ui_refinement.py").read_text(encoding="utf-8")

    assert "original(dependencies, principal=principal)" in source
    assert "Paper implementation and controls" not in source
    assert "Construction and implementation" not in source


def test_shared_entrypoint_installer_activates_portfolio_first_layer() -> None:
    source = Path("opportunity_funnel_ui_refinement.py").read_text(encoding="utf-8")

    assert "import portfolio_first_ui_refinement" in source
    assert "portfolio_first_ui_refinement.install(app_impl)" in source
