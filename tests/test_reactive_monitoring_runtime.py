from __future__ import annotations

from datetime import datetime, timezone

import pytest

from operations.reactive_monitoring_runtime import (
    load_latest_reactive_monitoring_plan,
    match_reactive_dependencies,
)
from portfolio.active_investor import SQLiteActiveInvestorStore


NOW = datetime(2026, 8, 15, 20, 0, tzinfo=timezone.utc)


def _plan(*, evidence_input: str = "guidance cut", authority: bool = False) -> dict[str, object]:
    return {
        "identifier": "reactive-monitoring-plan:test",
        "as_of": NOW.isoformat(),
        "model_version": "reactive-monitoring-plan.v1",
        "reassessment_authority": authority,
        "dependencies": [
            {
                "identifier": "reactive:lifecycle:ABC",
                "kind": "thesis_invalidation",
                "affected_candidates": ["ABC"],
                "affected_sleeves": ["position_lifecycle"],
                "evidence_inputs": [evidence_input],
                "material_change": "guidance invalidates the thesis",
                "incremental_reassessment": True,
                "full_cycle_required": False,
                "priority": 0.9,
                "reassessment_authority": False,
            }
        ],
    }


def _record() -> dict[str, object]:
    return {
        "identifier": "record:guidance-cut",
        "available_at": NOW.isoformat(),
        "topic": "Management announces a material guidance cut",
        "reliability": 0.9,
        "relevance": 0.9,
        "materiality": 0.8,
        "provenance": {"quality_state": "verified"},
        # Deliberately omit generic impact channels. This proves that the stored
        # thesis-specific dependency adds an influence path beyond the broad
        # content-materiality channel classifier.
        "impact_channels": [],
    }


def test_reactive_dependency_changes_reassessment_match_counterfactually() -> None:
    matched = match_reactive_dependencies(
        plan=_plan(evidence_input="guidance cut"),
        records=(_record(),),
        as_of=NOW,
    )
    disconnected_counterfactual = match_reactive_dependencies(
        plan=_plan(evidence_input="unrelated weather condition"),
        records=(_record(),),
        as_of=NOW,
    )

    assert len(matched) == 1
    assert matched[0].dependency_identifier == "reactive:lifecycle:ABC"
    assert matched[0].reassessment_authority is False
    assert matched[0].real_money_authorized is False
    assert "guidance cut" in matched[0].reason().lower()
    assert disconnected_counterfactual == ()


def test_reactive_monitoring_rejects_any_claim_of_reassessment_authority() -> None:
    with pytest.raises(ValueError, match="deny reassessment authority"):
        match_reactive_dependencies(
            plan=_plan(authority=True),
            records=(_record(),),
            as_of=NOW,
        )


def test_reactive_monitoring_requires_qualified_point_in_time_evidence() -> None:
    stale = _record()
    stale["provenance"] = {"quality_state": "stale"}
    low_quality = _record()
    low_quality["reliability"] = 0.2
    low_quality["relevance"] = 0.2
    low_quality["materiality"] = 0.2

    assert (
        match_reactive_dependencies(
            plan=_plan(),
            records=(stale, low_quality),
            as_of=NOW,
        )
        == ()
    )


def test_latest_reactive_plan_is_read_from_verified_append_only_chain(tmp_path) -> None:
    database = tmp_path / "journal.db"
    store = SQLiteActiveInvestorStore(database)
    store._append(
        event_identifier="reactive-monitoring-plan:test",
        cycle_identifier="cycle:test",
        event_type="reactive_monitoring",
        occurred_at=NOW,
        payload=_plan(),
    )

    loaded = load_latest_reactive_monitoring_plan(database)

    assert loaded is not None
    assert loaded["identifier"] == "reactive-monitoring-plan:test"
    assert loaded["reassessment_authority"] is False
    assert store.verify_integrity() is True
