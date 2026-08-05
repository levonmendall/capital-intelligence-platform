from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/verify-render-cio-diagnostic.yml")


def test_verifier_runs_after_successful_deployment_without_becoming_a_deploy_gate() -> None:
    content = WORKFLOW.read_text(encoding="utf-8")

    assert "deployment_status:" in content
    assert "github.event.deployment_status.state == 'success'" in content
    assert "github.event.deployment.sha" in content
    assert "push:" not in content
    assert "workflow_run:" not in content


def test_verifier_retains_deferred_and_manual_recovery_paths() -> None:
    content = WORKFLOW.read_text(encoding="utf-8")

    assert "schedule:" in content
    assert "workflow_dispatch:" in content
    assert "cancel-in-progress: true" in content
