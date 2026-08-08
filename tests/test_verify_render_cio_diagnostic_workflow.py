from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "verify-render-cio-diagnostic.yml"
)


def test_render_cio_verifier_allows_comprehensive_diagnostic_to_finish() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "timeout-minutes: 70" in workflow
    assert "--maximum-attempts 240" in workflow
    assert "--interval-seconds 15" in workflow


def test_render_cio_verifier_preserves_exact_release_audit_contract() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "AUDIT_URL: https://capital-intelligence-platform.onrender.com/"
        "app/static/cio-diagnostic.json"
    ) in workflow
    assert '--expected-release "$EXPECTED_RELEASE"' in workflow
    assert "persist-credentials: false" in workflow
