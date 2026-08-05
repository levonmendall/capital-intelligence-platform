from __future__ import annotations

import json
from pathlib import Path

import pytest

from verify_render_cio_diagnostic import (
    RenderAuditVerificationError,
    poll_render_audit,
    verify_complete_all_market_evaluation,
)


def _complete_payload(release: str) -> dict[str, object]:
    return {
        "schema_version": "public-cio-diagnostic-audit.v1",
        "credential_safe": True,
        "active_release": release,
        "release_matches": True,
        "state": "completed",
        "completed_at": "2026-08-05T19:00:00+00:00",
        "ready": True,
        "context_cycle_matches": True,
        "comprehensive_discovery_required": True,
        "comprehensive_discovery_complete": True,
        "scheduled_market_coverage_complete": True,
        "terminal_screening_complete": True,
        "all_market_evaluation_complete": True,
        "market_lanes": [
            {
                "asset_class": "crypto",
                "scheduled": True,
                "represented": True,
                "catalog_count": 5,
                "deep_analyzed_count": 5,
                "selected_count": 2,
            },
            {
                "asset_class": "fixed_income",
                "scheduled": True,
                "represented": True,
                "catalog_count": 7,
                "deep_analyzed_count": 7,
                "selected_count": 3,
            },
        ],
        "paper_only": True,
        "real_money_authorized": False,
    }


def _failed_payload(release: str, detail: str = "provider throttled") -> dict[str, object]:
    return {
        **_complete_payload(release),
        "state": "failed",
        "ready": False,
        "context_cycle_matches": False,
        "comprehensive_discovery_complete": False,
        "scheduled_market_coverage_complete": False,
        "terminal_screening_complete": False,
        "all_market_evaluation_complete": False,
        "market_lanes": [],
        "detail": detail,
    }


def test_poll_ignores_stale_release_and_persists_current_final_audit(
    tmp_path: Path,
) -> None:
    release = "release-current"
    payloads = iter(
        (
            {**_complete_payload("release-old"), "release_matches": False},
            _complete_payload(release),
        )
    )
    sleeps: list[float] = []
    output = tmp_path / "audit.json"

    result = poll_render_audit(
        url="https://example.test/app/static/cio-diagnostic.json",
        expected_release=release,
        output_path=output,
        maximum_attempts=2,
        interval_seconds=0.25,
        fetcher=lambda _url: next(payloads),
        sleeper=sleeps.append,
    )

    assert result["active_release"] == release
    assert sleeps == [0.25]
    assert json.loads(output.read_text(encoding="utf-8")) == result


def test_poll_treats_failed_attempt_as_provisional_until_later_success(
    tmp_path: Path,
) -> None:
    release = "release-current"
    payloads = iter(
        (
            _failed_payload(release, "HK fallback returned HTTP 429"),
            _complete_payload(release),
        )
    )
    sleeps: list[float] = []
    output = tmp_path / "audit.json"

    result = poll_render_audit(
        url="https://example.test/app/static/cio-diagnostic.json",
        expected_release=release,
        output_path=output,
        maximum_attempts=2,
        interval_seconds=0.25,
        fetcher=lambda _url: next(payloads),
        sleeper=sleeps.append,
    )

    assert result["state"] == "completed"
    assert sleeps == [0.25]
    assert json.loads(output.read_text(encoding="utf-8")) == result


def test_poll_remains_bounded_when_all_attempts_stay_failed(
    tmp_path: Path,
) -> None:
    release = "release-current"
    failed = _failed_payload(release, "HK fallback returned HTTP 429")
    sleeps: list[float] = []
    output = tmp_path / "audit.json"

    with pytest.raises(
        RenderAuditVerificationError,
        match="did not publish a current successful aggregate audit",
    ):
        poll_render_audit(
            url="https://example.test/app/static/cio-diagnostic.json",
            expected_release=release,
            output_path=output,
            maximum_attempts=2,
            interval_seconds=0.25,
            fetcher=lambda _url: failed,
            sleeper=sleeps.append,
        )

    assert sleeps == [0.25]
    assert json.loads(output.read_text(encoding="utf-8")) == failed


def test_complete_all_market_audit_passes() -> None:
    payload = _complete_payload("release-current")

    verify_complete_all_market_evaluation(
        payload,
        expected_release="release-current",
    )


def test_degraded_market_scope_fails_closed() -> None:
    payload = {
        **_complete_payload("release-current"),
        "ready": False,
        "comprehensive_discovery_complete": False,
        "all_market_evaluation_complete": False,
        "detail": "fixed-income provider evidence was unavailable",
        "comprehensive_discovery_limitations": ["fixed_income unavailable"],
    }

    with pytest.raises(RenderAuditVerificationError, match="failed closed"):
        verify_complete_all_market_evaluation(
            payload,
            expected_release="release-current",
        )


def test_unrepresented_scheduled_market_fails_closed() -> None:
    payload = _complete_payload("release-current")
    payload["market_lanes"] = [
        {
            "asset_class": "fx",
            "scheduled": True,
            "represented": False,
            "catalog_count": 0,
            "deep_analyzed_count": 0,
            "selected_count": 0,
        }
    ]

    with pytest.raises(RenderAuditVerificationError, match="unrepresented_market_lanes=fx"):
        verify_complete_all_market_evaluation(
            payload,
            expected_release="release-current",
        )


def test_sensitive_field_is_rejected_even_when_nested() -> None:
    payload = _complete_payload("release-current")
    payload["internal"] = {"target_weights": {"BTC-USD": 0.1}}

    with pytest.raises(RenderAuditVerificationError, match="forbidden fields"):
        verify_complete_all_market_evaluation(
            payload,
            expected_release="release-current",
        )
