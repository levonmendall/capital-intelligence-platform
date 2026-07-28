"""Regression checks for the premium, minimal canonical Streamlit experience."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_premium_interface_keeps_four_simple_surfaces() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    ui = (ROOT / "premium_ui.py").read_text(encoding="utf-8")

    assert '["Today", "Environment", "Portfolio", "History"]' in app
    assert "hero-card" in ui
    assert "hero-monogram" in ui
    assert "allocation-shell" in ui
    assert "Capital deployed" in ui
    assert "AI Chief Investment Officer · Paper mode" in ui


def test_four_screen_navigation_is_visible_in_the_main_workspace() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    ui = (ROOT / "premium_ui.py").read_text(encoding="utf-8")

    assert "page, dark_mode = render_navigation(PRIMARY_SURFACES)" in app
    assert "Four-screen workspace" in ui
    assert 'horizontal=True' in ui
    assert "Use the four-screen navigation at the top" in ui


def test_runtime_dark_mode_is_available_and_persistent() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    ui = (ROOT / "premium_ui.py").read_text(encoding="utf-8")

    assert 'st.session_state.get("dark_mode", False)' in app
    assert "apply_global_style(dark_mode=dark_mode)" in app
    assert 'st.toggle("Dark mode", key="dark_mode")' in ui
    assert "--app-bg:#070b14" in ui
    assert "--surface:#111827" in ui


def test_streamlit_theme_is_versioned_with_the_application() -> None:
    theme = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")

    assert 'base = "light"' in theme
    assert 'primaryColor = "#2563EB"' in theme
    assert 'backgroundColor = "#F6F8FB"' in theme
    assert 'textColor = "#0F172A"' in theme


def test_secure_app_source_adapter_remains_compatible() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    secure = (ROOT / "secure_app.py").read_text(encoding="utf-8")

    expected_import = '''from core.portfolio import (
    get_mandate_details,
    get_portfolio_totals,
    get_trade_history,
)
'''
    assert expected_import in app
    assert expected_import in secure
    assert 'exec(compile(_authorized_source(), "app.py", "exec"), execution_globals)' in secure


def test_optional_dashboard_reads_fail_soft_in_streamlit_surface() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert app.count("except (RuntimeError, OSError):") >= 4
