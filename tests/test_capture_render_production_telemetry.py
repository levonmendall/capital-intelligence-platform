from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from scripts import capture_render_production_telemetry as telemetry


def _payload(release: str = "release-current") -> dict[str, object]:
    return {
        "schema_version": "public-cio-diagnostic-audit.v1",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        "active_release": release,
        "release_matches": True,
        "state": "in_progress",
        "ready": False,
        "requested_at": "2026-08-10T17:00:00+00:00",
        "completed_at": None,
        "detail": "governed_progress=market_lane_screening; lane=crypto; count=25",
        "comprehensive_discovery_required": True,
        "comprehensive_discovery_complete": False,
        "scheduled_market_coverage_complete": False,
        "terminal_screening_complete": False,
        "all_market_evaluation_complete": False,
    }


def test_in_progress_snapshot_exposes_stage_without_raw_detail() -> None:
    payload = _payload()
    snapshot = telemetry.build_snapshot(
        payload,
        expected_release="release-current",
        captured_at=datetime(2026, 8, 10, 17, 15, tzinfo=timezone.utc),
        http_status=200,
        latency_ms=12.3456,
    )

    diagnostic = snapshot["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["state"] == "in_progress"
    assert diagnostic["stage"] == "market_lane_screening"
    assert diagnostic["elapsed_seconds"] == 900.0
    assert diagnostic["release_matches_expected"] is True
    assert "detail" not in diagnostic
    assert "crypto" not in json.dumps(snapshot)
    assert snapshot["http"] == {"status": 200, "latency_ms": 12.346}


def test_completed_exact_release_reports_all_market_state() -> None:
    payload = {
        **_payload(),
        "state": "completed",
        "ready": True,
        "completed_at": "2026-08-10T17:06:00+00:00",
        "detail": "completed",
        "comprehensive_discovery_complete": True,
        "scheduled_market_coverage_complete": True,
        "terminal_screening_complete": True,
        "all_market_evaluation_complete": True,
        "market_lanes": [
            {
                "asset_class": "crypto",
                "scheduled": True,
                "represented": True,
                "catalog_count": 20,
                "deep_analyzed_count": 5,
                "selected_count": 2,
                "internal_note": "must never propagate",
            }
        ],
    }

    snapshot = telemetry.build_snapshot(
        payload,
        expected_release="release-current",
        captured_at=datetime(2026, 8, 10, 17, 20, tzinfo=timezone.utc),
    )

    diagnostic = snapshot["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["elapsed_seconds"] == 360.0
    assert diagnostic["all_market_evaluation_complete"] is True
    assert diagnostic["market_lanes"] == [
        {
            "asset_class": "crypto",
            "scheduled": True,
            "represented": True,
            "catalog_count": 20,
            "deep_analyzed_count": 5,
            "selected_count": 2,
        }
    ]
    assert "internal_note" not in json.dumps(snapshot)


def test_release_mismatch_is_reported_truthfully() -> None:
    payload = {**_payload("release-old"), "release_matches": False}

    snapshot = telemetry.build_snapshot(
        payload,
        expected_release="release-current",
    )

    diagnostic = snapshot["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["active_release"] == "release-old"
    assert diagnostic["release_matches_expected"] is False


def test_nested_sensitive_source_field_is_rejected_without_propagation() -> None:
    payload = _payload()
    payload["internal"] = {"target_weights": {"BTC-USD": 0.15}}

    snapshot, unsafe = telemetry.capture_once(
        url="https://example.test/cio-diagnostic.json",
        expected_release="release-current",
        fetcher=lambda _url: (payload, 200, 1.0),
    )

    assert unsafe is True
    assert snapshot["capture_state"] == "unsafe_payload"
    encoded = json.dumps(snapshot)
    assert "target_weights" not in encoded
    assert "BTC-USD" not in encoded
    assert "internal" not in encoded


def test_network_failure_writes_only_generic_error_type() -> None:
    def broken(_url: str):
        raise OSError("private backend hostname and credential-like detail")

    snapshot, unsafe = telemetry.capture_once(
        url="https://example.test/cio-diagnostic.json",
        expected_release="release-current",
        fetcher=broken,
    )

    assert unsafe is False
    assert snapshot["capture_state"] == "unavailable"
    assert snapshot["error_type"] == "OSError"
    assert "private backend" not in json.dumps(snapshot)


def test_fetch_uses_get_without_authorization_or_cookie(monkeypatch) -> None:
    observed: dict[str, object] = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(_payload()).encode("utf-8")

    def urlopen(request, timeout):
        observed["method"] = request.get_method()
        observed["headers"] = {key.lower(): value for key, value in request.header_items()}
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr(telemetry.urllib.request, "urlopen", urlopen)
    payload, status, latency = telemetry.fetch_public_audit(
        "https://example.test/cio-diagnostic.json",
        timeout_seconds=3.5,
    )

    assert payload["credential_safe"] is True
    assert status == 200
    assert latency >= 0
    assert observed["method"] == "GET"
    headers = observed["headers"]
    assert isinstance(headers, dict)
    assert "authorization" not in headers
    assert "cookie" not in headers
    assert observed["timeout"] == 3.5


def test_cli_watch_writes_safe_timeline_and_stops_on_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshots = iter(
        (
            telemetry.build_snapshot(
                _payload(),
                expected_release="release-current",
            ),
            telemetry.build_snapshot(
                {
                    **_payload(),
                    "state": "completed",
                    "ready": True,
                    "completed_at": "2026-08-10T17:06:00+00:00",
                    "comprehensive_discovery_complete": True,
                    "scheduled_market_coverage_complete": True,
                    "terminal_screening_complete": True,
                    "all_market_evaluation_complete": True,
                },
                expected_release="release-current",
            ),
        )
    )

    monkeypatch.setattr(
        telemetry,
        "capture_once",
        lambda **_kwargs: (next(snapshots), False),
    )
    monotonic_values = iter((0.0, 0.0, 0.0, 1.0, 1.0))
    monkeypatch.setattr(telemetry.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(telemetry.time, "sleep", lambda _seconds: None)
    output = tmp_path / "snapshot.json"
    timeline = tmp_path / "timeline.json"

    result = telemetry.main(
        (
            "--url",
            "https://example.test/cio-diagnostic.json",
            "--expected-release",
            "release-current",
            "--output",
            str(output),
            "--timeline-output",
            str(timeline),
            "--watch-seconds",
            "60",
            "--interval-seconds",
            "1",
        )
    )

    assert result == 0
    assert json.loads(output.read_text(encoding="utf-8"))["diagnostic"]["state"] == "completed"
    assert len(json.loads(timeline.read_text(encoding="utf-8"))) == 2
