from __future__ import annotations

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/verify-render-cio-diagnostic.yml")


def test_render_verification_starts_after_successful_production_deployment() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "deployment_status:" in workflow
    assert "github.event.deployment_status.state == 'success'" in workflow
    assert (
        "github.event.deployment.environment == "
        "'main - capital-intelligence-platform'"
    ) in workflow
    assert "github.event.deployment.production_environment == true" in workflow
    assert "github.event.deployment.ref == 'main'" in workflow
    assert (
        "EXPECTED_RELEASE: ${{ github.event.deployment.sha || "
        "github.event.inputs.expected_release || github.sha }}"
    ) in workflow


def test_render_verification_does_not_block_checks_based_deployment() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "workflow_run:" not in workflow
    assert "deployment_status:" in workflow
    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
