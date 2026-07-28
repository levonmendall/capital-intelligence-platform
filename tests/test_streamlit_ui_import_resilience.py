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

    assert 'Path(__file__).with_name("app_impl.py")' in entrypoint
    assert 'if all(name in globals() for name in _authorized_names):' in entrypoint
    assert 'exec(compile(_source, str(_source_path), "exec"), globals())' in entrypoint


def test_interface_implementation_retains_four_distinct_surfaces() -> None:
    implementation = (ROOT / "app_impl.py").read_text(encoding="utf-8")

    assert 'PRIMARY_SURFACES = ["Today", "Environment", "Portfolio", "History"]' in implementation
    assert 'surface_story(' in implementation
    assert 'activity_rail(' in implementation
    assert 'variant="environment"' in implementation
    assert 'variant="portfolio"' in implementation
    assert 'variant="history"' in implementation
