from __future__ import annotations

from urllib.error import HTTPError

import pytest

import verify_render_cio_diagnostic as verifier


_FRESH_AFTER = "2026-08-14T21:22:35Z"
_FRESH_REQUESTED_AT = "2026-08-14T21:23:05+00:00"


def _successful_payload(release: str = "abc123") -> dict[str, object]:
    return {
        "request_id": "fresh-request-1",
        "requested_at": _FRESH_REQUESTED_AT,
        "active_release": release,
        "release_matches": True,
        "state": "completed",
        "stage": "complete",
        "completed_at": "2026-08-14T21:24:00+00:00",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _bad_gateway() -> HTTPError:
    return HTTPError(
        "https://example.invalid/cio-diagnostic.json",
        502,
        "Bad Gateway",
        hdrs=None,
        fp=None,
    )


def test_freshness_preflight_retries_transient_http_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CIO_DIAGNOSTIC_FRESH_AFTER", _FRESH_AFTER)
    calls = 0
    progress: list[str] = []
    sleeps: list[float] = []
    payload = _successful_payload()

    def fetcher(_url: str) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _bad_gateway()
        return payload

    result = verifier.poll_render_audit(
        url="https://example.invalid/cio-diagnostic.json",
        expected_release="abc123",
        output_path=tmp_path / "audit.json",
        maximum_attempts=3,
        interval_seconds=0.0,
        fetcher=fetcher,
        sleeper=sleeps.append,
        progress_writer=progress.append,
    )

    assert result == payload
    assert calls == 2
    assert sleeps == [0.0]
    assert any("render_cio_diagnostic_freshness_unavailable" in item for item in progress)
    assert any("render_cio_diagnostic_fresh_request_observed" in item for item in progress)


def test_freshness_preflight_fails_closed_after_transient_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CIO_DIAGNOSTIC_FRESH_AFTER", _FRESH_AFTER)
    calls = 0

    def fetcher(_url: str) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise _bad_gateway()

    with pytest.raises(
        verifier.RenderAuditVerificationError,
        match="stale_diagnostic_snapshot:.*could not read",
    ):
        verifier.poll_render_audit(
            url="https://example.invalid/cio-diagnostic.json",
            expected_release="abc123",
            output_path=tmp_path / "audit.json",
            maximum_attempts=1,
            interval_seconds=0.0,
            fetcher=fetcher,
            sleeper=lambda _seconds: None,
            progress_writer=None,
        )

    assert calls > 1


def test_freshness_preflight_still_rejects_wrong_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CIO_DIAGNOSTIC_FRESH_AFTER", _FRESH_AFTER)
    payload = _successful_payload("wrong-release")

    with pytest.raises(
        verifier.RenderAuditVerificationError,
        match="stale_diagnostic_snapshot:",
    ):
        verifier.poll_render_audit(
            url="https://example.invalid/cio-diagnostic.json",
            expected_release="abc123",
            output_path=tmp_path / "audit.json",
            maximum_attempts=1,
            interval_seconds=0.0,
            fetcher=lambda _url: payload,
            sleeper=lambda _seconds: None,
            progress_writer=None,
        )
