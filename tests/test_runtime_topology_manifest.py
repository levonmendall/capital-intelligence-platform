from __future__ import annotations

from capital_intelligence_cli import command_tokens, load_manifest, validate_manifest
from run_render_service import managed_processes


def test_every_root_command_has_exactly_one_classification() -> None:
    manifest = load_manifest()
    report = validate_manifest(manifest)
    assert report == {
        "ready": True,
        "root_script_count": 92,
        "classified_script_count": 92,
        "missing": [],
        "extra": [],
        "duplicate_classifications": 0,
        "legacy": [],
        "schema_version": "capital-intelligence-command-inventory.v1",
        "real_money_authorized": False,
    }


def test_render_runtime_matches_canonical_manifest_behaviorally() -> None:
    manifest = load_manifest()
    declared = set(manifest["topologies"]["render"]["processes"])
    actual = {
        process.name
        for process in managed_processes(port=10000, python_executable="python")
    }
    assert actual == declared
    assert command_tokens("render", manifest)[-1] == (
        "run_render_service_nonblocking.py"
    )
    assert command_tokens("headlines", manifest)[-2:] == (
        "run_public_headline_collector.py",
        "--loop",
    )


def test_canonical_commands_preserve_single_execution_authority() -> None:
    manifest = load_manifest()
    operator = command_tokens("operator", manifest)
    ui = command_tokens("ui", manifest)
    headlines = command_tokens("headlines", manifest)
    assert "run_autonomous_paper_operator.py" in operator
    assert "app.py" in ui
    assert "paper_execution" not in " ".join(ui)
    assert "paper_execution" not in " ".join(headlines)
    assert manifest["topologies"]["local"]["paper_execution_default"] == "disabled"
    assert manifest["topologies"]["docker-api"]["paper_execution_default"] == "disabled"
