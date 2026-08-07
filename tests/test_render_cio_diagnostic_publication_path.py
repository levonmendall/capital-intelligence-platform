"""Regression coverage for the public Render CIO diagnostic certification path."""

from pathlib import Path


def test_render_verifier_reads_streamlit_static_audit() -> None:
    workflow = Path(
        ".github/workflows/verify-render-cio-diagnostic.yml"
    ).read_text(encoding="utf-8")
    streamlit_config = Path(".streamlit/config.toml").read_text(encoding="utf-8")

    assert "enableStaticServing = true" in streamlit_config
    assert (
        "AUDIT_URL: https://capital-intelligence-platform.onrender.com/"
        "app/static/cio-diagnostic.json"
    ) in workflow
    assert (
        "AUDIT_URL: https://capital-intelligence-platform.onrender.com/"
        "v1/operations/cio-diagnostic"
    ) not in workflow


def test_render_api_child_is_not_the_public_listener() -> None:
    supervisor = Path("run_render_service.py").read_text(encoding="utf-8")

    assert '"--host",\n                "127.0.0.1"' in supervisor
    assert '"--port",\n                "8000"' in supervisor
    assert '"--server.address=0.0.0.0"' in supervisor
