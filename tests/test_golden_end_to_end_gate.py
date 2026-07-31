from __future__ import annotations

import json
from pathlib import Path

import pytest

from operations.golden_end_to_end import load_golden_manifest, run_golden_gate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "golden_end_to_end_scenarios.json"


def test_manifest_covers_required_behavior_and_live_denial() -> None:
    payload, scenarios = load_golden_manifest(MANIFEST)
    categories = {item.category for item in scenarios}
    assert set(payload["required_categories"]) <= categories
    assert len(scenarios) >= 15
    assert any("canonical_cio_cycle" in item.test_node_id for item in scenarios)
    assert any("paper_execution_orchestration" in item.test_node_id for item in scenarios)
    assert any("recovery_drill" in item.test_node_id for item in scenarios)
    assert any(item.identifier == "alpaca-live-endpoint-denied" for item in scenarios)
    assert payload["real_money_authorized"] is False


def test_gate_status_is_derived_from_behavioral_process(tmp_path, monkeypatch) -> None:
    payload = {
        "schema_version": "capital-intelligence-golden-scenarios.v1",
        "invariant": "test invariant",
        "scenarios": [
            {
                "identifier": "behavior",
                "category": "decision",
                "test_node_id": "tests/test_golden_end_to_end_gate.py::test_manifest_covers_required_behavior_and_live_denial",
            }
        ],
        "required_categories": ["decision"],
        "real_money_authorized": False,
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    report = run_golden_gate(
        manifest_path=manifest,
        repository_root=ROOT,
        report_path=tmp_path / "report.json",
    )
    assert report["status"] == "passed"
    assert report["pytest_return_code"] == 0
    assert report["real_money_authorized"] is False


def test_manifest_rejects_self_declared_or_missing_test(tmp_path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["scenarios"][0]["test_node_id"] = "not-a-behavioral-result"
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="explicit behavioral test"):
        load_golden_manifest(invalid)
