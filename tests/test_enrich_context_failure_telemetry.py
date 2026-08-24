from __future__ import annotations

import json

import pytest

from scripts import enrich_context_failure_telemetry as telemetry


def _snapshot() -> dict[str, object]:
    return {
        "schema_version": "render-production-telemetry.v1",
        "expected_release": "release-current",
        "diagnostic": {
            "diagnostic_id": "diagnostic-1",
            "state": "failed",
            "stage": "production_context_portfolio_finalized",
        },
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _public(detail: str) -> dict[str, object]:
    return {
        "active_release": "release-current",
        "diagnostic_id": "diagnostic-1",
        "detail": detail,
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }


def test_specific_inner_evidence_failure_wins_over_outer_boundary() -> None:
    detail = (
        "Candidate or holding evidence failed closed: ProductionPaperEvidenceError: "
        "point-in-time capital-flow evidence is unavailable for REDACTED"
    )

    enriched = telemetry.enrich_snapshot(
        _snapshot(),
        _public(detail),
        expected_release="release-current",
    )

    diagnostic = enriched["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["context_failure_code"] == "capital_flow_evidence_missing"
    assert enriched["enriched_from_context_failure"] is True
    encoded = json.dumps(enriched)
    assert "REDACTED" not in encoded
    assert "detail" not in encoded


def test_mandatory_closed_market_holding_has_distinct_code() -> None:
    code = telemetry.classify_context_failure(
        "Candidate or holding evidence failed closed: ProductionPaperEvidenceError: "
        "mandatory holding evidence is unavailable while the instrument's market is scheduled closed"
    )
    assert code == "mandatory_holding_market_scheduled_closed"


def test_unknown_detail_is_not_copied_or_inferred() -> None:
    enriched = telemetry.enrich_snapshot(
        _snapshot(),
        _public("opaque provider text with a symbol and implementation detail"),
        expected_release="release-current",
    )

    assert "enriched_from_context_failure" not in enriched
    assert "context_failure_code" not in enriched["diagnostic"]
    assert "opaque provider text" not in json.dumps(enriched)


def test_release_or_diagnostic_mismatch_is_not_enriched() -> None:
    wrong_release = _public("candidate or holding evidence failed closed")
    wrong_release["active_release"] = "release-old"
    assert telemetry.enrich_snapshot(
        _snapshot(), wrong_release, expected_release="release-current"
    ) == _snapshot()

    wrong_id = _public("candidate or holding evidence failed closed")
    wrong_id["diagnostic_id"] = "diagnostic-2"
    assert telemetry.enrich_snapshot(
        _snapshot(), wrong_id, expected_release="release-current"
    ) == _snapshot()


def test_forbidden_public_operational_fields_remain_fail_closed() -> None:
    unsafe = _public("candidate or holding evidence failed closed")
    unsafe["positions"] = [{"symbol": "PRIVATE"}]

    with pytest.raises(ValueError, match="forbidden fields"):
        telemetry.enrich_snapshot(
            _snapshot(), unsafe, expected_release="release-current"
        )
