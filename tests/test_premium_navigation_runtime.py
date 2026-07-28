"""Focused source contracts for visible navigation and runtime appearance controls."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_main_workspace_exposes_all_four_screens() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    ui = (ROOT / "premium_ui.py").read_text(encoding="utf-8")

    assert 'PRIMARY_SURFACES = ["Today", "Environment", "Portfolio", "History"]' in app
    assert "render_navigation(PRIMARY_SURFACES)" in app
    assert 'st.radio(' in ui
    assert 'horizontal=True' in ui


def test_dark_mode_palette_is_runtime_selectable() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    ui = (ROOT / "premium_ui.py").read_text(encoding="utf-8")

    assert 'st.toggle("Dark mode", key="dark_mode")' in ui
    assert 'st.session_state.get("dark_mode", False)' in app
    assert "--app-bg:#070b14" in ui
    assert "--app-bg:#f6f8fb" in ui
    assert 'st.markdown(f"<style>{palette}{common}</style>"' in ui
