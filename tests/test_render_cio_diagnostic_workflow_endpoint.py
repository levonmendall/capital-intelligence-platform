from pathlib import Path


def test_render_cio_verifier_polls_live_operational_endpoint() -> None:
    workflow = Path(".github/workflows/verify-render-cio-diagnostic.yml").read_text(
        encoding="utf-8"
    )

    assert (
        "AUDIT_URL: https://capital-intelligence-platform.onrender.com/"
        "v1/operations/cio-diagnostic"
    ) in workflow
    assert "/app/static/cio-diagnostic.json" not in workflow
    assert "--expected-release \"$EXPECTED_RELEASE\"" in workflow
    assert "--maximum-attempts 120" in workflow
