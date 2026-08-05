from __future__ import annotations

import json
from datetime import datetime, timezone

from cio_decision_export import (
    build_cio_decision_export,
    cio_decision_export_filename,
    cio_decision_export_json,
    select_cio_decision_records,
)


GENERATED_AT = datetime(2026, 8, 5, 15, 0, tzinfo=timezone.utc)
DECISION_ID = "decision:2026-08-05:ABC"
CYCLE_ID = "canonical-cio:America/Los_Angeles:2026-08-05"


def _bundle(**overrides):
    values = {
        "cio_decision": {
            "identifier": DECISION_ID,
            "cycle_identifier": CYCLE_ID,
            "as_of": "2026-08-05T14:00:00+00:00",
            "action": "no_superior_opportunity",
            "code_version": "abc123",
            "decision_horizon_days": 365,
        },
        "daily_cio_briefing": {
            "decision_identifier": DECISION_ID,
            "cycle_identifier": CYCLE_ID,
            "snapshot_identifier": "snapshot:2026-08-05:ABC",
            "as_of": "2026-08-05T14:00:00+00:00",
            "portfolio_decision": "Remain in cash.",
        },
        "decision_evidence_snapshot": {
            "decision_identifier": DECISION_ID,
            "snapshot_identifier": "snapshot:2026-08-05:ABC",
            "cycle_identifier": CYCLE_ID,
            "as_of": "2026-08-05T14:00:00+00:00",
        },
        "portfolio_construction": {
            "decision_identifier": DECISION_ID,
            "cycle_identifier": CYCLE_ID,
            "as_of": "2026-08-05T14:00:00+00:00",
            "target_cash_weight": 1.0,
            "trades": [],
        },
        "decision_evaluation": {
            "decision_identifier": DECISION_ID,
            "as_of": "2026-08-05T14:00:00+00:00",
            "status": "pending_outcome",
        },
        "release_identifier": "abc123",
    }
    values.update(overrides)
    return build_cio_decision_export(**values, generated_at=GENERATED_AT)


def test_export_contains_one_governed_lineage_and_authority_limits() -> None:
    bundle = _bundle()

    assert bundle["schema_version"] == "cio-decision-export.v2"
    assert bundle["decision_identifier"] == DECISION_ID
    assert bundle["snapshot_identifier"] == "snapshot:2026-08-05:ABC"
    assert bundle["record_consistency"]["state"] == "aligned"
    assert bundle["auditability"] == {
        "status": "auditable",
        "issues": [],
        "mixed_records_included": False,
        "target_decision_identifier": DECISION_ID,
        "target_cycle_identifier": CYCLE_ID,
    }
    assert all(bundle["record_presence"].values())
    assert bundle["authority"] == {
        "read_only_export": True,
        "candidate_authority": False,
        "ranking_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def test_export_redacts_sensitive_keys_but_preserves_governance_flags() -> None:
    bundle = _bundle(
        cio_decision={
            "identifier": DECISION_ID,
            "cycle_identifier": CYCLE_ID,
            "action": "hold",
            "code_version": "abc123",
            "api_token": "do-not-export",
            "secret_values_disclosed": False,
            "real_money_authorized": False,
        }
    )

    decision = bundle["records"]["cio_decision"]
    assert decision["api_token"] == "[REDACTED]"
    assert decision["secret_values_disclosed"] is False
    assert decision["real_money_authorized"] is False


def test_export_drops_mismatched_records_and_marks_non_auditable() -> None:
    bundle = _bundle(
        decision_evaluation={
            "decision_identifier": "older-decision",
            "cycle_identifier": "canonical-cio:America/Los_Angeles:2026-08-04",
            "as_of": "2026-08-04T14:00:00+00:00",
        }
    )

    assert bundle["record_consistency"]["state"] == "non_auditable"
    assert bundle["records"]["decision_evaluation"] is None
    assert bundle["record_presence"]["decision_evaluation"] is False
    assert bundle["auditability"]["mixed_records_included"] is False
    assert "decision_evaluation:decision_identifier_mismatch" in bundle["auditability"]["issues"]


def test_unproven_construction_is_not_substituted_from_an_older_cycle() -> None:
    bundle = _bundle(
        portfolio_construction={
            "as_of": "2026-08-04T14:00:00+00:00",
            "target_cash_weight": 0.95,
            "trades": [{"symbol": "OLD"}],
        }
    )

    assert bundle["records"]["portfolio_construction"] is None
    assert bundle["component_status"]["portfolio_construction"] == (
        "not_applicable_no_executable_action"
    )
    assert "portfolio_construction:lineage_unproven" in bundle["auditability"]["issues"]


def test_selector_uses_exact_briefing_identifiers_not_latest_event_type() -> None:
    briefing = {
        "decision_identifier": "decision:mcd",
        "cycle_identifier": "cycle:current",
    }
    selected = select_cio_decision_records(
        daily_cio_briefing=briefing,
        cio_decisions=(
            {"identifier": "decision:klac", "action": "hold"},
            {"identifier": "decision:mcd", "action": "no_material_change"},
        ),
        decision_evidence_snapshots=(
            {"decision_identifier": "decision:klac"},
            {"decision_identifier": "decision:mcd"},
        ),
        portfolio_constructions=(
            {"cycle_identifier": "cycle:older"},
            {"cycle_identifier": "cycle:current", "trades": []},
        ),
        decision_evaluations=(
            {"decision_identifier": "decision:klac"},
        ),
    )

    assert selected["cio_decision"]["identifier"] == "decision:mcd"
    assert selected["decision_evidence_snapshot"]["decision_identifier"] == "decision:mcd"
    assert selected["portfolio_construction"]["cycle_identifier"] == "cycle:current"
    assert selected["decision_evaluation"] is None


def test_deferred_action_distinguishes_selected_and_effective_action() -> None:
    bundle = _bundle(
        cio_decision={
            "identifier": DECISION_ID,
            "cycle_identifier": CYCLE_ID,
            "as_of": "2026-08-05T14:00:00+00:00",
            "action": "hold",
            "deferred_action": "reduce",
            "hysteresis_applied": True,
            "persistence_cycles": 7,
            "rationale": "The three-day cooldown remains active.",
            "code_version": "abc123",
            "decision_horizon_days": 365,
        }
    )

    assert bundle["decision_actions"] == {
        "selected_action": "reduce",
        "effective_action": "hold",
        "deferred": True,
        "hysteresis_applied": True,
        "persistence_cycles": 7,
        "rationale": "The three-day cooldown remains active.",
    }


def test_missing_evaluation_has_explicit_pending_horizon_status() -> None:
    bundle = _bundle(decision_evaluation=None)

    status = bundle["component_status"]["decision_evaluation"]
    assert status["status"] == "pending_horizon"
    assert status["recorded"] is False
    assert status["due_at"] == "2027-08-05T14:00:00+00:00"


def test_unknown_decision_code_version_blocks_auditable_status() -> None:
    bundle = _bundle(
        cio_decision={
            "identifier": DECISION_ID,
            "cycle_identifier": CYCLE_ID,
            "action": "hold",
            "code_version": "unknown",
        }
    )

    assert bundle["release_identity"]["export_runtime_release"] == "abc123"
    assert bundle["release_identity"]["decision_release_recorded"] is False
    assert bundle["auditability"]["status"] == "non_auditable"
    assert "cio_decision:code_version_not_recorded" in bundle["auditability"]["issues"]


def test_json_and_filename_are_mobile_friendly_and_deterministic() -> None:
    bundle = _bundle()
    encoded = cio_decision_export_json(bundle)

    assert json.loads(encoded)["decision_identifier"] == DECISION_ID
    assert encoded.endswith("\n")
    assert cio_decision_export_filename(bundle) == (
        "cio-decision-decision-2026-08-05-ABC.json"
    )


def test_generated_at_must_be_timezone_aware() -> None:
    try:
        build_cio_decision_export(
            cio_decision=None,
            daily_cio_briefing=None,
            decision_evidence_snapshot=None,
            portfolio_construction=None,
            decision_evaluation=None,
            generated_at=datetime(2026, 8, 5, 15, 0),
        )
    except ValueError as error:
        assert "timezone-aware" in str(error)
    else:
        raise AssertionError("naive generated_at should fail")
