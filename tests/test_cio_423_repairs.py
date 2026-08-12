from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import operations.manual_cio_diagnostic as manual
from verify_render_cio_diagnostic import RenderAuditVerificationError, poll_render_audit


NOW = datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc)


def _active_payload(release: str, request_id: str) -> dict[str, object]:
    return {
        "schema_version": "public-cio-diagnostic-audit.v1",
        "credential_safe": True,
        "active_release": release,
        "release_matches": True,
        "request_id": request_id,
        "state": "in_progress",
        "stage": "provider_preselection_fallback_probe",
        "paper_only": True,
        "real_money_authorized": False,
    }


def _failed_payload(release: str, request_id: str) -> dict[str, object]:
    return {
        **_active_payload(release, request_id),
        "state": "failed",
        "stage": "terminal_screening_finalize_rankings:international_equity",
        "completed_at": "2026-08-12T20:05:00+00:00",
        "detail": "Resource Governor memory pressure",
    }


def test_verifier_adopts_active_exact_release_and_reports_its_terminal_failure(
    tmp_path: Path,
) -> None:
    release = "release-current"
    request_id = "fresh-active-request"
    payloads = iter(
        (
            _active_payload(release, request_id),
            _failed_payload(release, request_id),
        )
    )
    sleeps: list[float] = []

    with pytest.raises(RenderAuditVerificationError, match="current_diagnostic_failed"):
        poll_render_audit(
            url="https://example.test/app/static/cio-diagnostic.json",
            expected_release=release,
            output_path=tmp_path / "audit.json",
            maximum_attempts=10,
            interval_seconds=0.25,
            fetcher=lambda _url: next(payloads),
            sleeper=sleeps.append,
            progress_writer=None,
        )

    assert sleeps == [0.25]


def test_production_style_catalog_stage_records_resource_metrics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED", "true"
    )
    monkeypatch.setattr(
        manual,
        "_terminal_screening_resource_metrics",
        lambda _values: {
            "rss_kib": 200000,
            "service_rss_kib": 400000,
            "container_current_kib": 500000,
            "container_limit_kib": 2097152,
            "container_anon_kib": 420000,
            "container_file_kib": 70000,
            "container_kernel_kib": 10000,
            "memory_reserve_kib": 655360,
            "governed_boundary_kib": 1441792,
            "governed_headroom_kib": 941792,
        },
    )

    manual.request_manual_cio_diagnostic(
        requested_by="render-release:test", now=NOW
    )
    claimed = manual.claim_manual_cio_diagnostic(now=NOW)
    assert claimed is not None

    progressed = manual.record_manual_cio_diagnostic_progress("catalog_options")
    assert progressed is not None
    assert progressed.progress_stage == "catalog_options"
    metrics = dict(progressed.progress_metrics)
    assert metrics["container_current_kib"] == 500000
    assert metrics["container_anon_kib"] == 420000
    assert metrics["governed_headroom_kib"] == 941792
    assert progressed.detail == "governed_progress=catalog_options"


def test_finalization_stage_names_are_governed_and_resource_attributed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "true",
    }
    monkeypatch.setattr(
        manual,
        "_terminal_screening_resource_metrics",
        lambda _values: {"rss_kib": 123456, "governed_headroom_kib": 654321},
    )
    manual.request_manual_cio_diagnostic(
        requested_by="render-release:test", now=NOW, values=values
    )
    claimed = manual.claim_manual_cio_diagnostic(now=NOW, values=values)
    assert claimed is not None

    progressed = manual.record_manual_cio_diagnostic_progress(
        "terminal_screening_finalize_rankings:international_equity",
        metrics={"processed_records": 45286, "total_records": 45286},
        values=values,
    )
    assert progressed is not None
    assert progressed.progress_stage == (
        "terminal_screening_finalize_rankings:international_equity"
    )
    assert dict(progressed.progress_metrics)["rss_kib"] == 123456
    assert dict(progressed.progress_metrics)["processed_records"] == 45286
