from __future__ import annotations

from pathlib import Path

from governance.runtime_convergence_contracts import (
    CONVERGENCE_CONTRACTS,
    validate_convergence_contracts,
)


ROOT = Path(__file__).resolve().parents[1]


def test_high_meaning_live_influence_contracts_are_connected() -> None:
    issues = validate_convergence_contracts(ROOT)

    assert not issues, "\n".join(issues)
    by_name = {item.name: item for item in CONVERGENCE_CONTRACTS}
    assert "global_rotation_production_cycle" in by_name
    assert "governed_historical_learning_feedback" in by_name
    assert by_name["governed_historical_learning_feedback"].feedback_path
    assert "canonical_cio_decision" in by_name["global_rotation_production_cycle"].influence_targets
