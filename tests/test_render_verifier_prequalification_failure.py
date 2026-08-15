from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import verify_render_cio_diagnostic as verifier


def test_fresh_prequalification_failure_is_terminal_without_replacement_wait(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    boundary = datetime.now(timezone.utc) - timedelta(seconds=5)
    monkeypatch.setenv("CIO_DIAGNOSTIC_FRESH_AFTER", boundary.isoformat())
    payload = {
        "request_id": "prequal-1",
        "request_kind": "evidence_prequalification",
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "active_release": "release-123",
        "release_matches": True,
        "state": "failed",
        "stage": "evidence_prequalification_failed",
        "detail": "future component is stale",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }
    fetches = 0

    def fetcher(_url):
        nonlocal fetches
        fetches += 1
        return payload

    with pytest.raises(
        verifier.RenderAuditVerificationError,
        match="current_diagnostic_failed:.*evidence_prequalification_failed",
    ):
        verifier.poll_render_audit(
            url="https://example.invalid/cio-diagnostic.json",
            expected_release="release-123",
            output_path=tmp_path / "audit.json",
            maximum_attempts=10,
            interval_seconds=0,
            fetcher=fetcher,
            sleeper=lambda _seconds: None,
            progress_writer=None,
        )

    assert fetches == 1
