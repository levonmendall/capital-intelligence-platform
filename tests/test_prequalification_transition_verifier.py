from __future__ import annotations

from pathlib import Path

import pytest

import verify_render_cio_diagnostic_core as verifier


def _prequalifying_payload(release: str) -> dict[str, object]:
    return {
        "request_id": "old-request-before-prequalification",
        "requested_at": "2026-08-28T04:44:08+00:00",
        "active_release": release,
        "release_matches": True,
        "state": "prequalifying",
        "stage": "evidence_refresh",
        "completed_at": None,
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _terminal_prequalification_payload(release: str) -> dict[str, object]:
    return {
        "request_id": "old-request-before-prequalification",
        "requested_at": "2026-08-28T04:44:08+00:00",
        "active_release": release,
        "release_matches": True,
        "state": "failed",
        "stage": "evidence_prequalification_failed",
        "completed_at": "2026-08-28T05:34:05+00:00",
        "detail": (
            "bounded evidence qualification failed; "
            "child_stage=stage_isolated_evidence:comprehensive_discovery; "
            "child_error_type=EvidenceFreshnessExpired"
        ),
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }


def test_terminal_prequalification_transition_wins_stale_request_timer(
    tmp_path: Path,
) -> None:
    release = "release-transition"
    payloads = iter(
        (
            _prequalifying_payload(release),
            _terminal_prequalification_payload(release),
        )
    )
    fetch_count = 0
    sleeps: list[float] = []

    def fetch(_url: str):
        nonlocal fetch_count
        fetch_count += 1
        return next(payloads)

    with pytest.raises(
        verifier.RenderAuditVerificationError,
        match="current_diagnostic_failed:.*evidence_prequalification_failed",
    ):
        verifier.poll_render_audit(
            url="https://example.test/app/static/cio-diagnostic.json",
            expected_release=release,
            output_path=tmp_path / "audit.json",
            maximum_attempts=12,
            interval_seconds=0.25,
            fresh_attempt_grace_attempts=8,
            fetcher=fetch,
            sleeper=sleeps.append,
            progress_writer=None,
        )

    assert fetch_count == 2
    assert sleeps == [0.25]
