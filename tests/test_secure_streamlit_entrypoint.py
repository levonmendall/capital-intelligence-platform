"""Regression checks for explicit authenticated Streamlit execution."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_direct_entrypoint_configures_the_page_before_rendering() -> None:
    entrypoint = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "def render_application(" in entrypoint
    assert "if configure_page:" in entrypoint
    assert "st.set_page_config(" in entrypoint
    assert "_app_impl.render_application(**kwargs)" in entrypoint
    assert "exec(compile" not in entrypoint


def test_authenticated_entrypoint_owns_page_configuration_once() -> None:
    secure = (ROOT / "secure_app.py").read_text(encoding="utf-8")

    assert "def run_authenticated_app(" in secure
    assert "if configure_page:" in secure
    assert "st.set_page_config(" in secure
    assert "render_application(" in secure
    assert "configure_page=False" in secure
    assert "exec(compile" not in secure


def test_implementation_accepts_explicit_authorized_bindings() -> None:
    implementation = (ROOT / "app_impl.py").read_text(encoding="utf-8")

    assert "st.set_page_config(" not in implementation
    assert "def render_application(" in implementation
    assert "get_mandate_details_fn" in implementation
    assert "get_portfolio_totals_fn" in implementation
    assert "get_trade_history_fn" in implementation
    compile(implementation, "app_impl.py", "exec")
