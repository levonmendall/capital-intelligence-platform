"""Regression checks for the deployed Streamlit navigation contract."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import premium_ui
from app_impl import PRIMARY_SURFACES


ROOT = Path(__file__).resolve().parents[1]


def test_live_entrypoints_use_normal_imports_and_one_factory() -> None:
    for relative in ("app.py", "render_app.py"):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "secure_app"
            for alias in node.names
        }
        assert "create_streamlit_application" in imported


def test_primary_navigation_is_one_permanent_dark_segmented_control() -> None:
    source = inspect.getsource(premium_ui.render_navigation)
    assert PRIMARY_SURFACES == ["Today", "Environment", "Portfolio", "History"]
    assert "st.segmented_control(" in source
    assert 'selection_mode="single"' in source
    assert "required=True" in source
    assert 'width="stretch"' in source
    assert "st.toggle(" not in source
    assert "st.radio(" not in source


def test_deployed_sidebar_has_no_theme_mutation() -> None:
    source = inspect.getsource(premium_ui.render_sidebar)
    assert "Dark command mode" not in source
    assert "Four distinct surfaces. One governed portfolio." in source
