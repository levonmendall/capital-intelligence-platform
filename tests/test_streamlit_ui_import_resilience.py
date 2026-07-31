"""Regression checks for deployment-safe Streamlit presentation startup."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_entrypoint_reloads_presentation_module() -> None:
    entrypoint = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "import premium_ui as _premium_ui" in entrypoint
    assert "_premium_ui = importlib.reload(_premium_ui)" in entrypoint
    assert 'hasattr(_premium_ui, "activity_rail")' in entrypoint
    assert 'hasattr(_premium_ui, "surface_story")' in entrypoint


def test_streamlit_entrypoint_preserves_secure_portfolio_bindings() -> None:
    entrypoint = (ROOT / "app.py").read_text(encoding="utf-8")
    implementation = (ROOT / "app_impl.py").read_text(encoding="utf-8")
    secure = (ROOT / "secure_app.py").read_text(encoding="utf-8")

    assert "import app_impl as _app_impl" in entrypoint
    assert "_app_impl.render_application(**kwargs)" in entrypoint
    assert "get_mandate_details_fn" in implementation
    assert "get_portfolio_totals_fn" in implementation
    assert "get_trade_history_fn" in implementation
    assert "_authorized_bindings(principal)" in secure
    assert "exec(compile" not in entrypoint
    assert "exec(compile" not in secure

def test_premium_html_helpers_are_rebound_to_non_indented_renderers() -> None:
    entrypoint = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "def _safe_render_app_header(active_page: str)" in entrypoint
    assert "def _safe_render_sidebar()" in entrypoint
    assert "def _safe_allocation_bar(*, cash: float, nav: float)" in entrypoint
    assert "_premium_ui.render_app_header = _safe_render_app_header" in entrypoint
    assert "_premium_ui.render_sidebar = _safe_render_sidebar" in entrypoint
    assert "_premium_ui.allocation_bar = _safe_allocation_bar" in entrypoint


def test_surface_hero_markup_starts_with_html_not_markdown_indentation() -> None:
    entrypoint = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "markup = (\n        f'<style>:root" in entrypoint
    assert "_premium_ui.st.markdown(markup, unsafe_allow_html=True)" in entrypoint
    assert 'f"""\n        <style>' not in entrypoint
    assert 'f"""\n        <div class="capital-orbit">' not in entrypoint


def test_interface_implementation_retains_four_distinct_surfaces() -> None:
    implementation = (ROOT / "app_impl.py").read_text(encoding="utf-8")

    assert 'PRIMARY_SURFACES = ["Today", "Environment", "Portfolio", "History"]' in implementation
    assert "surface_story(" in implementation
    assert "activity_rail(" in implementation
    assert 'variant="environment"' in implementation
    assert 'variant="portfolio"' in implementation
    assert 'variant="history"' in implementation
