from __future__ import annotations

from pathlib import Path

import pytest

from verify_render_cio_diagnostic import (
    RenderAuditVerificationError,
    _progress_fields,
    poll_render_audit,
)


EXPECTED_RELEASE = "release-live-progress"


def _running_payload(*, detail: str = "governed_progress=comprehensive_discovery") -> dict[str, object]:
    return {
        "active_release": EXPECTED_RELEASE,
        "release_matches": True,
        "state": "running",
        "detail": detail,
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _clock(values: list[float]):
    iterator = iter(values)
    return lambda: next(iterator)


def test_progress_fields_expose_only_allowlisted_phase_state_and_release_match() -> None:
    payload = _running_payload(
        detail="governed_progress=comprehensive_discovery; provider_error=TOP_SECRET_VALUE"
    )

    assert _progress_fields(payload, expected_release=EXPECTED_RELEASE) == (
        "comprehensive_discovery",
        "running",
        "yes",
    )


def test_poller_emits_live_heartbeat_without_raw_detail(tmp_path: Path) -> None:
    lines: list[str] = []
    payload = _running_payload(
        detail="governed_progress=evidence_collection; raw_error=DO_NOT_PRINT_ME"
    )

    with pytest.raises(RenderAuditVerificationError):
        poll_render_audit(
            url="https://example.invalid/audit.json",
            expected_release=EXPECTED_RELEASE,
            output_path=tmp_path / "audit.json",
            maximum_attempts=3,
            interval_seconds=15,
            fetcher=lambda _url: payload,
            sleeper=lambda _seconds: None,
            clock=_clock([0.0, 0.0, 15.0, 30.0]),
            progress_writer=lines.append,
        )

    joined = "\n".join(lines)
    assert "stage=evidence_collection" in joined
    assert '"stage": "evidence_collection"' in joined
    assert "elapsed=30s" in joined
    assert "release_match=yes" in joined
    assert "DO_NOT_PRINT_ME" not in joined
    assert "raw_error" not in joined


def test_poller_warns_when_phase_has_not_changed_for_five_minutes(tmp_path: Path) -> None:
    lines: list[str] = []
    payload = _running_payload(detail="governed_progress=instrument_catalog")

    with pytest.raises(RenderAuditVerificationError):
        poll_render_audit(
            url="https://example.invalid/audit.json",
            expected_release=EXPECTED_RELEASE,
            output_path=tmp_path / "audit.json",
            maximum_attempts=2,
            interval_seconds=15,
            fetcher=lambda _url: payload,
            sleeper=lambda _seconds: None,
            clock=_clock([0.0, 0.0, 301.0]),
            progress_writer=lines.append,
        )

    joined = "\n".join(lines)
    assert "::warning title=Render CIO diagnostic phase unchanged::" in joined
    assert "stage=instrument_catalog" in joined
    assert "unchanged_for=301s" in joined


def test_phase_change_resets_stale_warning_timer(tmp_path: Path) -> None:
    lines: list[str] = []
    payloads = iter(
        [
            _running_payload(detail="governed_progress=instrument_catalog"),
            _running_payload(detail="governed_progress=evidence_collection"),
        ]
    )

    with pytest.raises(RenderAuditVerificationError):
        poll_render_audit(
            url="https://example.invalid/audit.json",
            expected_release=EXPECTED_RELEASE,
            output_path=tmp_path / "audit.json",
            maximum_attempts=2,
            interval_seconds=15,
            fetcher=lambda _url: next(payloads),
            sleeper=lambda _seconds: None,
            clock=_clock([0.0, 0.0, 301.0]),
            progress_writer=lines.append,
        )

    joined = "\n".join(lines)
    assert "stage=instrument_catalog" in joined
    assert "stage=evidence_collection" in joined
    assert "phase unchanged" not in joined
