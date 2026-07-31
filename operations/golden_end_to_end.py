"""Executable golden-path and chaos release gate.

The manifest points at behavioral tests.  Passing is derived only from the
pytest process result; it cannot be asserted by a scenario payload.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "capital-intelligence-golden-scenarios.v1"


@dataclass(frozen=True, slots=True)
class GoldenScenario:
    identifier: str
    category: str
    test_node_id: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "GoldenScenario":
        values = {}
        for field in ("identifier", "category", "test_node_id"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"golden scenario {field} must be non-empty text")
            values[field] = value.strip()
        node_id = values["test_node_id"]
        if not node_id.startswith("tests/") or "::test_" not in node_id:
            raise ValueError("golden scenario must reference an explicit behavioral test")
        return cls(**values)


def load_golden_manifest(path: str | Path) -> tuple[dict[str, Any], tuple[GoldenScenario, ...]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported golden scenario manifest")
    if payload.get("real_money_authorized") is not False:
        raise ValueError("golden gate cannot authorize real money")
    scenarios = tuple(GoldenScenario.from_payload(item) for item in payload.get("scenarios", ()))
    if not scenarios:
        raise ValueError("golden gate requires scenarios")
    identifiers = tuple(item.identifier for item in scenarios)
    node_ids = tuple(item.test_node_id for item in scenarios)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("golden scenario identifiers must be unique")
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("golden scenario behavioral tests must be unique")
    required = payload.get("required_categories")
    if not isinstance(required, list) or not required or not all(isinstance(item, str) for item in required):
        raise ValueError("required_categories must be a non-empty text list")
    missing = sorted(set(required) - {item.category for item in scenarios})
    if missing:
        raise ValueError(f"golden scenario categories missing: {', '.join(missing)}")
    return payload, scenarios


def run_golden_gate(
    *,
    manifest_path: str | Path,
    repository_root: str | Path,
    report_path: str | Path,
    python: str = sys.executable,
    extra_pytest_args: Sequence[str] = (),
) -> dict[str, Any]:
    manifest, scenarios = load_golden_manifest(manifest_path)
    root = Path(repository_root).resolve()
    for scenario in scenarios:
        test_path = root / scenario.test_node_id.split("::", 1)[0]
        if not test_path.is_file():
            raise ValueError(f"golden scenario test does not exist: {scenario.test_node_id}")
    command = (
        python,
        "-m",
        "pytest",
        "-q",
        "--maxfail=1",
        *extra_pytest_args,
        *(scenario.test_node_id for scenario in scenarios),
    )
    completed = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    evaluated_at = datetime.now(timezone.utc).isoformat()
    report = {
        "schema_version": "capital-intelligence-golden-gate-report.v1",
        "evaluated_at": evaluated_at,
        "status": "passed" if completed.returncode == 0 else "failed",
        "invariant": manifest["invariant"],
        "scenario_count": len(scenarios),
        "scenario_identifiers": [item.identifier for item in scenarios],
        "behavioral_test_node_ids": [item.test_node_id for item in scenarios],
        "pytest_return_code": completed.returncode,
        "stdout": completed.stdout[-20_000:],
        "stderr": completed.stderr[-20_000:],
        "cio_authority_changed": False,
        "construction_authority_changed": False,
        "governance_authority_changed": False,
        "execution_authority_changed": False,
        "real_money_authorized": False,
    }
    destination = Path(report_path)
    if not destination.is_absolute():
        destination = root / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


__all__ = ["GoldenScenario", "load_golden_manifest", "run_golden_gate"]
