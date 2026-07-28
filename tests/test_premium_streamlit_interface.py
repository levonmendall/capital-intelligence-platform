"""Regression checks for the signature canonical Streamlit experience."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_signature_interface_keeps_four_simple_surfaces() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    ui = (ROOT / "premium_ui.py").read_text(encoding="utf-8")

    assert '["Today", "Environment", "Portfolio", "History"]' in app
    assert "hero-shell" in ui
    assert "signal-core" in ui
    assert "capital-orbit" in ui
    assert "Capital Intelligence Operating System" in ui
    assert "metric-grid" in ui
    assert "signal-panel" in ui


def test_four_screen_navigation_is_visible_in_the_main_workspace() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    ui = (ROOT / "premium_ui.py").read_text(encoding="utf-8")

    assert "page, _ = render_navigation(PRIMARY_SURFACES)" in app
    assert "Capital Intelligence // Command Deck" in ui
    assert "horizontal=True" in ui
    assert 'PRIMARY_SURFACES = ["Today", "Environment", "Portfolio", "History"]' in app


def test_dark_mode_is_the_preset_and_remains_selectable() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    ui = (ROOT / "premium_ui.py").read_text(encoding="utf-8")

    assert 'st.session_state.setdefault("dark_mode", True)' in app
    assert 'apply_global_style(dark_mode=bool(st.session_state["dark_mode"]))' in app
    assert 'st.toggle("Dark", key="dark_mode")' in ui
    assert "--bg:#05070d" in ui
    assert "--bg:#eef3f9" in ui


def test_streamlit_theme_defaults_to_signature_dark_mode() -> None:
    theme = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")

    assert 'base = "dark"' in theme
    assert 'primaryColor = "#56E0FF"' in theme
    assert 'backgroundColor = "#05070D"' in theme
    assert 'secondaryBackgroundColor = "#0D1320"' in theme
    assert 'textColor = "#F8FAFC"' in theme


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
