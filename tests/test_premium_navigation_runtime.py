"""Architecture contracts for navigation and permanent-dark presentation."""

from __future__ import annotations

import inspect

import premium_ui
from app_impl import PRIMARY_SURFACES, render_surfaces


def test_main_workspace_exposes_only_four_primary_screens() -> None:
    assert PRIMARY_SURFACES == ["Today", "Environment", "Portfolio", "History"]
    assert callable(render_surfaces)


def test_navigation_uses_one_required_segmented_control() -> None:
    source = inspect.getsource(premium_ui.render_navigation)
    assert "segmented_control" in source
    assert 'selection_mode="single"' in source
    assert "required=True" in source
    assert "st.radio" not in source
    assert "st.toggle" not in source


def test_signature_components_are_real_functions() -> None:
    for name in (
        "metric_grid",
        "signal_panel",
        "allocation_bar",
        "render_app_header",
        "render_sidebar",
    ):
        assert callable(getattr(premium_ui, name))
