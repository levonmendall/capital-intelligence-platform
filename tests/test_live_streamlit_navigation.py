"""Regression checks for the deployed Streamlit navigation contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_live_entrypoint_installs_navigation_before_application_execution() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")

    import_position = source.index(
        "from navigation_ui import install as _install_navigation_ui"
    )
    install_position = source.index("_install_navigation_ui(_premium_ui)")
    execute_position = source.index(
        'exec(compile(_source, str(_source_path), "exec"), globals())'
    )

    assert import_position < install_position < execute_position


def test_primary_navigation_is_one_permanent_dark_segmented_control() -> None:
    source = (ROOT / "navigation_ui.py").read_text(encoding="utf-8")

    assert "st.segmented_control(" in source
    assert 'selection_mode="single"' in source
    assert "required=True" in source
    assert 'width="stretch"' in source
    assert "repeat(4, minmax(0, 1fr))" in source
    assert "original_apply_global_style(dark_mode=True)" in source
    assert "st.toggle(" not in source
    assert "st.radio(" not in source


def test_deployed_sidebar_no_longer_exposes_a_theme_option() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    runtime_sidebar = source[source.index("def _safe_render_sidebar"):source.index("def _safe_render_app_header")]

    assert "Dark command mode" not in runtime_sidebar
    assert "Four distinct surfaces. One governed portfolio." in runtime_sidebar
