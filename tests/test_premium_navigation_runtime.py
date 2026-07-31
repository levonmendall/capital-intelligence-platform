"""Focused source contracts for visible navigation and runtime appearance controls."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_main_workspace_exposes_all_four_screens() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    ui = (ROOT / "premium_ui.py").read_text(encoding="utf-8")

    assert 'PRIMARY_SURFACES = ["Today", "Environment", "Portfolio", "History"]' in app
    assert "render_navigation(PRIMARY_SURFACES)" in app
    assert "st.radio(" in ui
    assert "horizontal=True" in ui


def test_dark_mode_palette_is_default_and_runtime_selectable() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    ui = (ROOT / "premium_ui.py").read_text(encoding="utf-8")

    assert 'st.toggle("Dark", key="dark_mode")' in ui
    assert 'st.session_state.setdefault("dark_mode", True)' in app
    assert "--bg:#05070d" in ui
    assert "--bg:#eef3f9" in ui
    assert 'st.markdown(f"<style>{palette}{css}</style>"' in ui


def test_signature_components_are_present() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    ui = (ROOT / "premium_ui.py").read_text(encoding="utf-8")

    assert "metric_grid(" in app
    assert "signal_panel(" in app
    assert "Capital Deployment Orbit" in ui
    assert "A governed investment-intelligence system" in ui
