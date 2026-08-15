from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from operations import continuous_evidence_plane
import run_continuous_evidence_plane as evidence_runner
import run_render_service_memory_safe as render_runtime
from verify_render_cio_diagnostic import RenderAuditVerificationError, poll_render_audit


def test_evidence_failure_detail_redacts_configured_secrets() -> None:
    secret = "provider-secret-value"
    detail = evidence_runner._credential_safe_error_detail(
        RuntimeError(
            "provider failed api_key=" + secret + " Authorization: Bearer abcdefghijklmnop"
        ),
        {"CAPITAL_INTELLIGENCE_PROVIDER_API_KEY": secret},
    )

    assert secret not in detail
    assert "abcdefghijklmnop" not in detail
    assert "[REDACTED]" in detail


def test_release_prequalification_persists_structured_child_failure(
    monkeypatch,
) -> None:
    writes: list[dict[str, object]] = []
    logs: list[tuple[str, dict[str, object]]] = []

    def write(_values, **kwargs):
        writes.append(dict(kwargs))
        return {
            "prequalification_id": kwargs.get("prequalification_id") or "prequal-585",
        }

    failure_context = {
        "event": "continuous_evidence_plane_failure_context",
        "error_type": "RuntimeError",
        "failure_stage": "component_qualified_evidence_maintenance",
        "error_detail": "reference manifest publication rejected catalog generation",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }

    monkeypatch.setattr(render_runtime, "write_release_evidence_prequalification", write)
    monkeypatch.setattr(
        render_runtime.render_bootstrap,
        "_publish_release_diagnostic_audit",
        lambda _values: None,
    )
    monkeypatch.setattr(
        render_runtime.render_bootstrap,
        "_log",
        lambda event, **kwargs: logs.append((event, dict(kwargs))),
    )
    monkeypatch.setattr(
        render_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=("evidence",),
            returncode=2,
            stderr=json.dumps(failure_context) + "\n",
        ),
    )
    monkeypatch.setattr(
        continuous_evidence_plane,
        "load_latest_evidence_plane",
        lambda _values: (_ for _ in ()).throw(
            AssertionError("failed qualifier must not load a generation")
        ),
    )

    values = {
        "CAPITAL_INTELLIGENCE_RELEASE": "release-585",
        "CAPITAL_INTELLIGENCE_RELEASE_EVIDENCE_PREQUALIFICATION_ATTEMPTS": "1",
        "CAPITAL_INTELLIGENCE_RELEASE_EVIDENCE_PREQUALIFICATION_RETRY_SECONDS": "0",
    }

    assert render_runtime._prequalify_release_evidence(values) is False
    failed = writes[-1]
    assert failed["state"] == "failed"
    assert failed["stage"] == "evidence_prequalification_failed"
    assert "child_stage=component_qualified_evidence_maintenance" in failed["detail"]
    assert "child_error_type=RuntimeError" in failed["detail"]
    assert "reference manifest publication rejected catalog generation" in failed["detail"]
    assert logs[-1][0] == "release_evidence_prequalification_failed"
    assert logs[-1][1]["failure_stage"] == "component_qualified_evidence_maintenance"
    assert logs[-1][1]["error_type"] == "RuntimeError"


def _terminal_prequalification_payload(release: str) -> dict[str, object]:
    return {
        "schema_version": "public-cio-diagnostic-audit.v2-end-to-end",
        "request_id": "old-request-before-prequalification",
        "requested_at": "2026-08-15T14:00:00+00:00",
        "active_release": release,
        "release_matches": True,
        "state": "failed",
        "stage": "evidence_prequalification_failed",
        "completed_at": "2026-08-15T18:00:00+00:00",
        "detail": (
            "bounded evidence qualification returned code 2; "
            "child_stage=component_qualified_evidence_maintenance; "
            "child_error_type=RuntimeError; child_detail=catalog publication rejected"
        ),
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }


def test_scheduled_verifier_preserves_prequalification_failure_instead_of_stale(
    monkeypatch,
    tmp_path: Path,
) -> None:
    release = "release-585"
    payload = _terminal_prequalification_payload(release)
    sleeps: list[float] = []
    monkeypatch.delenv("CIO_DIAGNOSTIC_FRESH_AFTER", raising=False)

    with pytest.raises(
        RenderAuditVerificationError,
        match="current_diagnostic_failed:.*evidence_prequalification_failed",
    ):
        poll_render_audit(
            url="https://example.test/app/static/cio-diagnostic.json",
            expected_release=release,
            output_path=tmp_path / "audit.json",
            maximum_attempts=8,
            interval_seconds=0.25,
            fetcher=lambda _url: payload,
            sleeper=sleeps.append,
        )

    assert sleeps == []
    persisted = json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))
    assert persisted["stage"] == "evidence_prequalification_failed"


def test_deployment_freshness_does_not_mask_prequalification_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    release = "release-585"
    payload = _terminal_prequalification_payload(release)
    sleeps: list[float] = []
    monkeypatch.setenv("CIO_DIAGNOSTIC_FRESH_AFTER", "2026-08-15T17:30:00+00:00")

    with pytest.raises(
        RenderAuditVerificationError,
        match="current_diagnostic_failed:.*evidence_prequalification_failed",
    ):
        poll_render_audit(
            url="https://example.test/app/static/cio-diagnostic.json",
            expected_release=release,
            output_path=tmp_path / "audit.json",
            maximum_attempts=8,
            interval_seconds=0.25,
            fetcher=lambda _url: payload,
            sleeper=sleeps.append,
        )

    assert sleeps == []
