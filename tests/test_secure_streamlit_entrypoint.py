"""Regression checks for the normally composed authenticated UI."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app_impl import ApplicationDependencies, render_surfaces
from secure_app import create_streamlit_application


ROOT = Path(__file__).resolve().parents[1]


def test_page_configuration_has_one_owner() -> None:
    assert "st.set_page_config" in inspect.getsource(create_streamlit_application)
    assert "st.set_page_config" not in inspect.getsource(render_surfaces)


def test_authorized_portfolio_access_uses_typed_dependencies() -> None:
    assert tuple(ApplicationDependencies.__dataclass_fields__) == (
        "get_mandate_details",
        "get_portfolio_totals",
        "get_trade_history",
    )
    assert "dependencies" in inspect.signature(render_surfaces).parameters


def test_active_ui_modules_compile_without_dynamic_execution() -> None:
    for relative in ("app.py", "render_app.py", "secure_app.py", "app_impl.py"):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"exec", "eval", "compile"}
            for node in ast.walk(tree)
        ), relative
