from __future__ import annotations

import json

import pytest

from scripts import enrich_context_failure_telemetry as telemetry


def _snapshot(*, stage: str = "production_context_portfolio_finalized") -> dict[str, object]:
    return {
        "schema_version": "render-production-telemetry.v1",
        "expected_release": "release-current",
        "diagnostic": {
            "diagnostic_id": "diagnostic-1",
            "state": "failed",
            "stage": stage,
        },
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _public(detail: str, *, stage: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "active_release": "release-current",
        "diagnostic_id": "diagnostic-1",
        "detail": detail,
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }
    if stage is not None:
        payload["stage"] = stage
    return payload


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


def test_typed_screening_resource_failure_survives_as_fixed_safe_code() -> None:
    stage = "production_context_screening_start_persisted"
    detail = (
        "ScreeningResourceDeferred: insufficient_runtime_memory_for_screening: "
        "container_current_bytes=1493106688; governed_headroom_bytes=0"
    )

    enriched = telemetry.enrich_snapshot(
        _snapshot(stage=stage),
        _public(detail, stage=stage),
        expected_release="release-current",
    )

    diagnostic = enriched["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["screening_failure_code"] == "screening_memory_boundary"
    assert diagnostic["screening_failure_substage"] == "post_screening_start_resource_guard"
    assert diagnostic["screening_failure_source"] == "governed_resource_guard"
    assert enriched["enriched_from_screening_failure"] is True
    encoded = json.dumps(enriched)
    assert "container_current_bytes" not in encoded
    assert "1493106688" not in encoded
    assert "detail" not in encoded


def test_supervisor_memory_boundary_survives_as_fixed_safe_code() -> None:
    stage = "production_context_screening_graph_released"
    detail = (
        "Manual CIO diagnostic reached the operational container-memory boundary "
        "(70% fractional ceiling with 640 MB service reserve) and was terminated "
        "fail-closed before the hosting kernel could OOM-kill the service; "
        "last_governed_progress=production_context_screening_graph_released."
    )

    enriched = telemetry.enrich_snapshot(
        _snapshot(stage=stage),
        _public(detail, stage=stage),
        expected_release="release-current",
    )

    diagnostic = enriched["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["screening_failure_code"] == "screening_memory_boundary"
    assert diagnostic["screening_failure_substage"] == "bounded_cio_supervisor_memory_guard"
    assert diagnostic["screening_failure_source"] == "bounded_cio_supervisor"
    assert enriched["enriched_from_screening_failure"] is True
    encoded = json.dumps(enriched)
    assert "640 MB" not in encoded
    assert "container-memory boundary" not in encoded
    assert "detail" not in encoded


def test_supervisor_timeout_survives_as_fixed_safe_code() -> None:
    stage = "production_context_screening_graph_released"
    detail = (
        "Manual CIO diagnostic exceeded its governed operational deadline of 1800 seconds "
        "and was terminated fail-closed; "
        "last_governed_progress=production_context_screening_graph_released."
    )

    enriched = telemetry.enrich_snapshot(
        _snapshot(stage=stage),
        _public(detail, stage=stage),
        expected_release="release-current",
    )

    diagnostic = enriched["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["screening_failure_code"] == "screening_timeout"
    assert diagnostic["screening_failure_substage"] == "bounded_cio_supervisor_timeout"
    assert diagnostic["screening_failure_source"] == "bounded_cio_supervisor"
    assert "1800" not in json.dumps(enriched)


def test_interrupted_screening_child_survives_as_fixed_safe_code() -> None:
    stage = "production_context_screening_graph_released"
    detail = (
        "Diagnostic execution was interrupted by a prior service process; "
        "no live owner lease remains, so a replacement request may proceed."
    )

    enriched = telemetry.enrich_snapshot(
        _snapshot(stage=stage),
        _public(detail, stage=stage),
        expected_release="release-current",
    )

    diagnostic = enriched["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["screening_failure_code"] == "screening_child_terminated"
    assert diagnostic["screening_failure_substage"] == "bounded_cio_supervisor_child_exit"
    assert diagnostic["screening_failure_source"] == "bounded_cio_supervisor"
    assert "prior service process" not in json.dumps(enriched)


def test_screening_reason_is_not_promoted_outside_screening_boundary() -> None:
    for detail in (
        "insufficient_runtime_memory_for_screening",
        "reached the operational container-memory boundary",
        "exceeded its governed operational deadline",
        "diagnostic execution was interrupted by a prior service process",
    ):
        enriched = telemetry.enrich_snapshot(
            _snapshot(stage="production_context_portfolio_finalized"),
            _public(detail),
            expected_release="release-current",
        )
        assert "enriched_from_screening_failure" not in enriched
        assert "screening_failure_code" not in enriched["diagnostic"]


def test_unknown_screening_failure_is_not_copied_or_inferred() -> None:
    stage = "production_context_screening_start_persisted"
    enriched = telemetry.enrich_snapshot(
        _snapshot(stage=stage),
        _public(
            "opaque screening exception with sensitive implementation detail",
            stage=stage,
        ),
        expected_release="release-current",
    )
    assert "enriched_from_screening_failure" not in enriched
    assert "screening_failure_code" not in enriched["diagnostic"]
    assert "opaque screening exception" not in json.dumps(enriched)


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
