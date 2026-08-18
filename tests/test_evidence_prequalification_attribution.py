from __future__ import annotations

from datetime import datetime, timezone

import publish_cio_diagnostic_audit as audit
from operations.evidence_prequalification_attribution import (
    EvidencePrequalificationReason,
    failed_prequalification_attribution,
    ready_prequalification_attribution,
)
from operations.release_evidence_prequalification import (
    load_release_evidence_prequalification,
    write_release_evidence_prequalification,
)


def _child_detail(*, stage: str, error_type: str, detail: str) -> str:
    return (
        "bounded evidence qualification returned code 2; "
        f"child_stage={stage}; child_error_type={error_type}; child_detail={detail}"
    )


def test_ready_attribution_is_the_only_advancing_state() -> None:
    context = ready_prequalification_attribution()

    assert context.state.value == "ready"
    assert context.reason is EvidencePrequalificationReason.READY
    assert context.completeness == "complete"
    assert context.terminal is False
    assert context.as_dict()["paper_only"] is True
    assert context.as_dict()["real_money_authorized"] is False


def test_stale_provider_evidence_is_attributed_with_freshness() -> None:
    context = failed_prequalification_attribution(
        detail=_child_detail(
            stage="component_qualified_evidence_maintenance",
            error_type="ContinuousEvidencePlaneError",
            detail=(
                "Alpaca paper evidence is stale; freshness_age_seconds=901; "
                "freshness_limit_seconds=900; affected_instrument_count=17"
            ),
        ),
        metrics={"qualifier_return_code": 2, "qualifier_return_code_negative": 0},
    )

    assert context.reason is EvidencePrequalificationReason.STALE
    assert context.capability == "paper_evidence"
    assert context.provider == "alpaca"
    assert context.freshness_age_seconds == 901.0
    assert context.freshness_limit_seconds == 900.0
    assert context.affected_instrument_count == 17
    assert context.completeness == "incomplete"
    assert context.terminal is True


def test_missing_provider_and_fallback_exhaustion_are_distinct() -> None:
    missing = failed_prequalification_attribution(
        detail=_child_detail(
            stage="component_qualified_evidence_maintenance",
            error_type="ReferenceReadinessError",
            detail="EODHD API token is required; provider not configured",
        ),
        metrics={"qualifier_return_code": 2},
    )
    exhausted = failed_prequalification_attribution(
        detail=_child_detail(
            stage="component_qualified_evidence_maintenance",
            error_type="RuntimeError",
            detail=(
                "all providers failed after fallback; primary_provider=alpaca; "
                "fallback_providers=tradier,massive"
            ),
        ),
        metrics={"qualifier_return_code": 2},
    )

    assert missing.reason is EvidencePrequalificationReason.MISSING_PROVIDER
    assert missing.provider == "eodhd"
    assert exhausted.reason is EvidencePrequalificationReason.FALLBACK_EXHAUSTED
    assert exhausted.provider == "alpaca"
    assert exhausted.fallback_providers_attempted == ("tradier", "massive")


def test_deadline_resource_and_invalid_payload_have_typed_reasons() -> None:
    deadline = failed_prequalification_attribution(
        detail="bounded evidence qualification returned code 124",
        metrics={"qualifier_return_code": 124},
    )
    memory = failed_prequalification_attribution(
        detail="bounded evidence qualification returned code 125",
        metrics={"qualifier_return_code": 125},
    )
    invalid = failed_prequalification_attribution(
        detail=_child_detail(
            stage="qualified_global_discovery_snapshot",
            error_type="JSONDecodeError",
            detail="global discovery snapshot contains an invalid payload",
        ),
        metrics={"qualifier_return_code": 2},
    )

    assert deadline.reason is EvidencePrequalificationReason.DEADLINE_EXCEEDED
    assert memory.reason is EvidencePrequalificationReason.RESOURCE_EXHAUSTED
    assert invalid.reason is EvidencePrequalificationReason.INVALID_PAYLOAD
    assert invalid.capability == "global_discovery_snapshot"


def test_terminal_release_record_persists_typed_failure_context(tmp_path) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-under-test",
    }
    started = datetime(2026, 8, 16, 1, 2, tzinfo=timezone.utc)
    detail = _child_detail(
        stage="qualified_paper_evidence_snapshot",
        error_type="PaperEvidenceSnapshotError",
        detail="paper evidence snapshot is incomplete; affected_instrument_count=4",
    )

    written = write_release_evidence_prequalification(
        values,
        state="failed",
        stage="evidence_prequalification_failed",
        prequalification_id="prequalification-test",
        started_at=started,
        detail=detail,
        metrics={
            "attempt": 6,
            "maximum_attempts": 6,
            "qualifier_return_code": 2,
            "qualifier_return_code_negative": 0,
        },
    )
    loaded = load_release_evidence_prequalification(values)

    assert loaded is not None
    assert loaded["integrity_sha256"] == written["integrity_sha256"]
    failure = loaded["failure_context"]
    assert isinstance(failure, dict)
    assert failure["state"] == "failed"
    assert failure["reason"] == "incomplete"
    assert failure["capability"] == "paper_evidence_snapshot"
    assert failure["failure_stage"] == "qualified_paper_evidence_snapshot"
    assert failure["error_type"] == "PaperEvidenceSnapshotError"
    assert failure["affected_instrument_count"] == 4
    assert failure["terminal"] is True
    assert failure["credential_safe"] is True


def test_public_audit_surfaces_failure_context_and_reference_component(monkeypatch) -> None:
    started = "2026-08-16T01:02:00+00:00"
    failure = {
        "state": "failed",
        "reason": "provider_error",
        "capability": "reference_components",
        "failure_stage": "component_qualified_evidence_maintenance",
        "error_type": "ReferenceReadinessError",
        "provider": "cme",
        "terminal": True,
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }
    monkeypatch.setattr(
        audit,
        "load_release_evidence_prequalification",
        lambda values: {
            "prequalification_id": "prequal-1",
            "release": "release-1",
            "state": "failed",
            "stage": "evidence_prequalification_failed",
            "started_at": started,
            "completed_at": "2026-08-16T01:05:00+00:00",
            "detail": "credential-safe detail",
            "metrics": {"attempt": 6, "maximum_attempts": 6},
            "generation_id": "",
            "failure_context": failure,
        },
    )
    monkeypatch.setattr(
        audit,
        "load_reference_readiness_progress",
        lambda values: {
            "updated_at": "2026-08-16T01:04:00+00:00",
            "stage": "futures_contracts",
            "progress_metrics": {"configured_futures_roots": 13},
        },
    )

    published = audit._with_release_prequalification(
        {
            "active_release": "old-release",
            "release_matches": False,
            "state": "pending",
            "stage": "awaiting_progress",
        },
        values={"CAPITAL_INTELLIGENCE_RELEASE": "release-1"},
    )

    assert published["state"] == "failed"
    assert published["stage"] == "evidence_prequalification_failed"
    assert published["prequalification_failure_reason"] == "provider_error"
    assert published["prequalification_failure_capability"] == "reference_components"
    assert published["prequalification_failure_provider"] == "cme"
    assert published["prequalification_failure_error_type"] == "ReferenceReadinessError"
    context = published["prequalification_failure_context"]
    assert isinstance(context, dict)
    assert context["component_stage"] == "futures_contracts"
    assert context["component_metrics"] == {"configured_futures_roots": 13}


def test_public_audit_promotes_granular_futures_root_dag(monkeypatch) -> None:
    started = "2026-08-18T02:22:00+00:00"
    failure = {
        "state": "failed",
        "reason": "incomplete",
        "capability": "reference_components",
        "failure_stage": "component_qualified_evidence_maintenance",
        "error_type": "ContinuousEvidencePlaneError",
        "provider": "cme-massive",
        "terminal": True,
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }
    monkeypatch.setattr(
        audit,
        "load_release_evidence_prequalification",
        lambda values: {
            "prequalification_id": "prequal-futures",
            "release": "release-futures",
            "state": "failed",
            "stage": "evidence_prequalification_failed",
            "started_at": started,
            "completed_at": "2026-08-18T02:25:00+00:00",
            "detail": "credential-safe futures failure",
            "metrics": {"attempt": 1, "maximum_attempts": 1},
            "generation_id": "",
            "failure_context": failure,
        },
    )
    monkeypatch.setattr(audit, "load_reference_readiness_progress", lambda values: None)
    monkeypatch.setattr(
        audit,
        "load_futures_reference_progress",
        lambda values: {
            "schema_version": "futures-reference-prequalification-progress.v1",
            "release": "release-futures",
            "cutoff": "2026-08-18T02:22:00+00:00",
            "updated_at": "2026-08-18T02:24:45+00:00",
            "state": "incomplete",
            "required_root_count": 2,
            "qualified_root_count": 1,
            "unresolved_root_count": 1,
            "required_roots": ["ES", "CL"],
            "qualified_roots": ["ES"],
            "unresolved_roots": ["CL"],
            "active_unit": None,
            "units": [
                {
                    "unit": "cme-venue-cme",
                    "provider": "cme_fprf",
                    "state": "qualified",
                    "venue": "CME",
                    "root": None,
                    "roots": ["ES"],
                    "duration_ms": 1200,
                    "failure_type": None,
                    "fallback": False,
                },
                {
                    "unit": "cme-venue-nymex",
                    "provider": "cme_fprf",
                    "state": "timed-out",
                    "venue": "NYMEX",
                    "root": None,
                    "roots": ["CL"],
                    "duration_ms": 45000,
                    "failure_type": "timeout",
                    "fallback": False,
                },
                {
                    "unit": "massive-root-CL",
                    "provider": "massive",
                    "state": "timed-out",
                    "venue": "NYMEX",
                    "root": "CL",
                    "roots": ["CL"],
                    "duration_ms": 45000,
                    "failure_type": "timeout",
                    "fallback": True,
                },
            ],
            "credential_safe": True,
            "paper_only": True,
            "real_money_authorized": False,
        },
    )

    values = {
        "CAPITAL_INTELLIGENCE_RELEASE": "release-futures",
        "CAPITAL_INTELLIGENCE_FUTURES_REFERENCE_UNIT_TIMEOUT_SECONDS": "45",
    }
    progress = audit._safe_futures_reference_progress(values)

    assert progress is not None
    assert progress["required_root_count"] == 2
    assert progress["qualified_root_count"] == 1
    assert progress["unresolved_roots"] == ["CL"]
    assert progress["blocking_unit"] == "massive-root-CL"
    assert progress["blocking_provider"] == "massive"
    assert progress["blocking_venue"] == "NYMEX"
    assert progress["blocking_root"] == "CL"
    assert progress["blocking_failure_type"] == "timeout"
    assert progress["nodes"] == [
        {
            "root": "ES",
            "state": "qualified",
            "unit": "cme-venue-cme",
            "provider": "cme_fprf",
            "venue": "CME",
            "failure_type": None,
            "duration_ms": 1200,
            "fallback": False,
        },
        {
            "root": "CL",
            "state": "timed-out",
            "unit": "massive-root-CL",
            "provider": "massive",
            "venue": "NYMEX",
            "failure_type": "timeout",
            "duration_ms": 45000,
            "fallback": True,
        },
    ]

    published = audit._with_release_prequalification(
        {
            "active_release": "old-release",
            "release_matches": False,
            "state": "pending",
            "stage": "awaiting_progress",
        },
        values=values,
    )

    assert published["prequalification_failure_unit"] == "massive-root-CL"
    assert published["prequalification_failure_venue"] == "NYMEX"
    assert published["prequalification_failure_root"] == "CL"
    assert published["prequalification_unresolved_futures_roots"] == ["CL"]
    context = published["prequalification_failure_context"]
    assert isinstance(context, dict)
    futures_context = context["futures_reference"]
    assert isinstance(futures_context, dict)
    assert futures_context["blocking_root"] == "CL"
    assert futures_context["qualified_roots"] == ["ES"]