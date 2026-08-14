from __future__ import annotations

from pathlib import Path

import pytest

import verify_render_cio_diagnostic as verifier


_RELEASE = "a" * 40


def _active_payload() -> dict[str, object]:
    return {
        "request_id": "request-309",
        "active_release": _RELEASE,
        "release_matches": True,
        "state": "in_progress",
        "stage": "reference_futures_contracts",
        "detail": "governed_progress=reference_futures_contracts",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _failed_payload() -> dict[str, object]:
    return {
        "request_id": "request-309",
        "active_release": _RELEASE,
        "release_matches": True,
        "state": "failed",
        "stage": "reference_futures_contracts",
        "detail": "Massive futures configured-root coverage failed for NQ",
        "completed_at": "2026-08-14T03:10:00Z",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }


def test_replacement_timeout_preserves_original_terminal_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CIO_DIAGNOSTIC_FRESH_AFTER", raising=False)
    responses = [_active_payload(), _failed_payload()]

    def fetcher(_: str) -> dict[str, object]:
        if responses:
            return responses.pop(0)
        return _failed_payload()

    with pytest.raises(verifier.RenderAuditVerificationError) as raised:
        verifier.poll_render_audit(
            url="https://example.invalid/v1/operations/cio-diagnostic",
            expected_release=_RELEASE,
            output_path=tmp_path / "diagnostic.json",
            maximum_attempts=50,
            interval_seconds=0,
            fetcher=fetcher,
            sleeper=lambda _: None,
            progress_writer=None,
        )

    detail = str(raised.value)
    assert detail.startswith("current_diagnostic_failed:")
    assert "stage=reference_futures_contracts" in detail
    assert "Massive futures configured-root coverage failed for NQ" in detail
    assert "secondary_context=replacement_attempt_not_observed" in detail
    assert "stale_diagnostic:" in detail
