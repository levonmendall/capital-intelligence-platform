from __future__ import annotations

import json
from datetime import datetime, timezone

from cio_decision_export import (
    build_cio_decision_export,
    cio_decision_export_filename,
    cio_decision_export_json,
)


GENERATED_AT = datetime(2026, 8, 5, 15, 0, tzinfo=timezone.utc)


def _bundle(**overrides):
    values = {
        "cio_decision": {
            "decision_identifier": "decision:2026-08-05:ABC",
            "cycle_identifier": "canonical-cio:America/Los_Angeles:2026-08-05",
            "as_of": "2026-08-05T14:00:00+00:00",
            "action": "no_superior_opportunity",
        },
        "daily_cio_briefing": {
            "decision_identifier": "decision:2026-08-05:ABC",
            "cycle_identifier": "canonical-cio:America/Los_Angeles:2026-08-05",
            "snapshot_identifier": "snapshot:2026-08-05:ABC",
            "as_of": "2026-08-05T14:00:00+00:00",
            "portfolio_decision": "Remain in cash.",
        },
        "decision_evidence_snapshot": {
            "snapshot_identifier": "snapshot:2026-08-05:ABC",
            "cycle_identifier": "canonical-cio:America/Los_Angeles:2026-08-05",
            "as_of": "2026-08-05T14:00:00+00:00",
        },
        "portfolio_construction": {
            "decision_identifier": "decision:2026-08-05:ABC",
            "as_of": "2026-08-05T14:00:00+00:00",
            "target_cash_weight": 1.0,
            "trades": [],
        },
        "decision_evaluation": {
            "decision_identifier": "decision:2026-08-05:ABC",
            "as_of": "2026-08-05T14:00:00+00:00",
            "status": "pending_outcome",
        },
    }
    values.update(overrides)
    return build_cio_decision_export(**values, generated_at=GENERATED_AT)


def test_export_contains_all_governed_records_and_authority_limits() -> None:
    bundle = _bundle()

    assert bundle["schema_version"] == "cio-decision-export.v1"
    assert bundle["decision_identifier"] == "decision:2026-08-05:ABC"
    assert bundle["snapshot_identifier"] == "snapshot:2026-08-05:ABC"
    assert bundle["record_consistency"]["state"] == "aligned"
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
            "decision_identifier": "decision:2026-08-05:ABC",
            "api_token": "do-not-export",
            "secret_values_disclosed": False,
            "real_money_authorized": False,
        }
    )

    decision = bundle["records"]["cio_decision"]
    assert decision["api_token"] == "[REDACTED]"
    assert decision["secret_values_disclosed"] is False
    assert decision["real_money_authorized"] is False


def test_export_marks_mixed_latest_records_without_dropping_them() -> None:
    bundle = _bundle(
        decision_evaluation={
            "decision_identifier": "older-decision",
            "cycle_identifier": "canonical-cio:America/Los_Angeles:2026-08-04",
            "as_of": "2026-08-04T14:00:00+00:00",
        }
    )

    assert bundle["record_consistency"]["state"] == "mixed_latest_records"
    assert bundle["records"]["decision_evaluation"]["decision_identifier"] == "older-decision"


def test_json_and_filename_are_mobile_friendly_and_deterministic() -> None:
    bundle = _bundle()
    encoded = cio_decision_export_json(bundle)

    assert json.loads(encoded)["decision_identifier"] == "decision:2026-08-05:ABC"
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
