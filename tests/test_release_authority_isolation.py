"""Release-surface isolation for retired decision authorities."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_active_release_and_deployment_surfaces_exclude_retired_entrypoints() -> None:
    files = (
        ROOT / ".github" / "workflows" / "validate.yml",
        ROOT / "Dockerfile",
        ROOT / "docker-compose.yml",
        ROOT / "run_release_validation.py",
        ROOT / "run_container_acceptance.py",
        ROOT / "deploy" / "canonical-daily-operations.json",
        ROOT / "deploy" / "canonical-daily-stage-bindings.validation.json",
    )
    prohibited = (
        "run_regime.py",
        "run_regime",
        "weighted_committee",
        "weighted-committee",
        "regime_allocation",
        "investor_memory",
        "investment_policy.db",
        "analytical_engines.db",
    )

    for path in files:
        content = path.read_text(encoding="utf-8").lower()
        for value in prohibited:
            assert value not in content, f"{value} reentered active release surface {path}"


def test_active_release_surface_names_only_canonical_decision_path() -> None:
    workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(
        encoding="utf-8"
    )
    release_command = (ROOT / "run_release_validation.py").read_text(
        encoding="utf-8"
    )
    plan = (ROOT / "deploy" / "canonical-daily-operations.json").read_text(
        encoding="utf-8"
    )

    assert "run_release_validation.py" in workflow
    assert "run_intelligence.py" in release_command
    assert "canonical_cio_cycle" in plan
    assert "complete_universe_screening" in plan
    assert "paper_construction_execution" in plan
    assert "thesis_monitoring" in plan
    assert "outcome_evaluation" in plan
