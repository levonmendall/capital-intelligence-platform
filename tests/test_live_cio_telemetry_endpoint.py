import io
import json
import subprocess
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

from fastapi import Response, status

from api.routes import cio_diagnostic
from scripts import capture_render_production_telemetry as telemetry
from scripts import capture_render_production_telemetry_canonical as canonical_telemetry


EXPECTED_RELEASE = "release-live-telemetry"
CANONICAL_URL = "https://capital-intelligence-platform.onrender.com/v1/operations/cio-diagnostic"


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=object()))
    )


def _in_progress_payload() -> dict[str, object]:
    return {
        "ready": False,
        "state": "in_progress",
        "detail": "governed_progress=public_information_collection",
        "stage": "public_information_collection",
        "active_release": EXPECTED_RELEASE,
        "release_matches": True,
        "paper_only": True,
        "real_money_authorized": False,
        "all_market_evaluation_complete": False,
        "market_lanes": [],
    }


def test_canonical_audit_contract_remains_unchanged_when_not_recorded(monkeypatch):
    monkeypatch.setattr(
        cio_diagnostic,
        "latest_manual_cio_diagnostic",
        lambda **_kwargs: None,
    )

    payload = cio_diagnostic.build_cio_diagnostic_audit(
        settings=object(),
        values={"CAPITAL_INTELLIGENCE_RELEASE": EXPECTED_RELEASE},
    )

    assert payload["state"] == "not_recorded"
    assert "credential_safe" not in payload
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False


def test_readiness_endpoint_remains_fail_closed_but_telemetry_transport_stays_live(
    monkeypatch,
):
    payload = _in_progress_payload()
    monkeypatch.setattr(
        cio_diagnostic,
        "build_cio_diagnostic_audit",
        lambda **_kwargs: dict(payload),
    )

    response = Response()
    readiness_payload = cio_diagnostic.cio_diagnostic_status(_request(), response)
    telemetry_payload = cio_diagnostic.cio_diagnostic_telemetry(_request())

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert readiness_payload == payload
    assert telemetry_payload == {**payload, "credential_safe": True}

    snapshot = telemetry.build_snapshot(
        telemetry_payload,
        expected_release=EXPECTED_RELEASE,
    )
    assert snapshot["capture_state"] == "ok"
    assert snapshot["diagnostic"]["stage"] == "public_information_collection"
    assert snapshot["diagnostic"]["release_matches_expected"] is True


def test_canonical_transport_accepts_fail_closed_503_as_live_json(monkeypatch):
    raw = json.dumps(_in_progress_payload()).encode("utf-8")
    error = urllib.error.HTTPError(
        CANONICAL_URL,
        503,
        "Service Unavailable",
        {},
        io.BytesIO(raw),
    )

    def _raise_503(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(canonical_telemetry.urllib.request, "urlopen", _raise_503)

    payload, http_status, _latency_ms = canonical_telemetry.fetch_canonical_public_audit(
        CANONICAL_URL
    )

    assert http_status == 503
    assert payload["credential_safe"] is True
    assert payload["stage"] == "public_information_collection"

    snapshot = telemetry.build_snapshot(payload, expected_release=EXPECTED_RELEASE)
    assert snapshot["capture_state"] == "ok"
    assert snapshot["diagnostic"]["stage"] == "public_information_collection"
    assert snapshot["diagnostic"]["release_matches_expected"] is True


def test_canonical_transport_rejects_noncanonical_endpoint():
    try:
        canonical_telemetry.fetch_canonical_public_audit(
            CANONICAL_URL + "/telemetry"
        )
    except ValueError as error:
        assert "canonical CIO diagnostic endpoint" in str(error)
    else:
        raise AssertionError("noncanonical telemetry endpoint was accepted")


def test_canonical_telemetry_starts_when_executed_like_github_actions():
    repository_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "scripts/capture_render_production_telemetry_canonical.py",
            "--help",
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--expected-release" in result.stdout
    assert "ModuleNotFoundError" not in result.stderr


def test_live_telemetry_route_is_registered_as_get():
    routes = {
        getattr(route, "path", ""): route for route in cio_diagnostic.router.routes
    }
    route = routes["/v1/operations/cio-diagnostic/telemetry"]
    assert "GET" in route.methods


def test_render_telemetry_workflow_uses_canonical_dynamic_endpoint():
    workflow = Path(".github/workflows/render-production-telemetry.yml").read_text(
        encoding="utf-8"
    )
    assert "onrender.com/v1/operations/cio-diagnostic\n" in workflow
    assert "capture_render_production_telemetry_canonical.py" in workflow
    assert "/v1/operations/cio-diagnostic/telemetry" not in workflow
    assert "/app/static/cio-diagnostic.json" not in workflow
