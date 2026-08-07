from pathlib import Path


def test_render_cio_verifier_polls_public_static_audit_surface() -> None:
    workflow = Path(".github/workflows/verify-render-cio-diagnostic.yml").read_text(
        encoding="utf-8"
    )

    assert (
        "AUDIT_URL: https://capital-intelligence-platform.onrender.com/"
        "app/static/cio-diagnostic.json"
    ) in workflow
    assert "v1/operations/cio-diagnostic" not in workflow
    assert "--expected-release \"$EXPECTED_RELEASE\"" in workflow
    assert "--maximum-attempts 120" in workflow
