from __future__ import annotations

from pathlib import Path

from governance.runtime_influence_registry import audit_repository
from governance.runtime_module_dispositions import MODULE_DISPOSITION_BY_NAME
from scripts.audit_runtime_connectivity import _converged_payload


ROOT = Path(__file__).resolve().parents[1]


def test_repository_has_zero_ambiguous_runtime_orphans() -> None:
    audit = audit_repository(ROOT)
    payload, issues = _converged_payload(audit)

    assert not issues, "\n".join(issues)
    assert payload["passed"] is True
    assert payload["ambiguous_orphan_count"] == 0
    assert payload["lifecycle_counts"].get("orphaned", 0) == 0
    assert len(MODULE_DISPOSITION_BY_NAME) >= 1


def test_new_unclassified_decision_module_fails_convergence(tmp_path: Path) -> None:
    (tmp_path / "run_worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    intelligence = tmp_path / "intelligence"
    intelligence.mkdir()
    (intelligence / "unused.py").write_text("VALUE = 2\n", encoding="utf-8")

    audit = audit_repository(tmp_path)
    payload, issues = _converged_payload(audit)

    assert payload["passed"] is False
    assert payload["ambiguous_orphan_count"] == 1
    assert any("intelligence.unused" in issue for issue in issues)
