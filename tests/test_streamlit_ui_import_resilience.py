"""Architecture checks for normal Streamlit imports and explicit composition."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app_impl import ApplicationDependencies, render_surfaces
from secure_app import create_streamlit_application


ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ("app.py", "render_app.py", "secure_app.py", "app_impl.py")


def test_active_entrypoints_do_not_execute_or_rewrite_source() -> None:
    for relative in ACTIVE:
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"exec", "eval", "compile"}, relative
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"read_text", "reload"}, relative


def test_portfolio_access_is_explicitly_injected() -> None:
    assert tuple(ApplicationDependencies.__dataclass_fields__) == (
        "get_mandate_details",
        "get_portfolio_totals",
        "get_trade_history",
    )
    assert "dependencies" in inspect.signature(render_surfaces).parameters


def test_one_factory_composes_authentication_and_surfaces() -> None:
    source = inspect.getsource(create_streamlit_application)
    assert "_principal()" in source
    assert "_authorized_dependencies(principal)" in source
    assert "render_surfaces(" in source
