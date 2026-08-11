from pathlib import Path
from types import SimpleNamespace

from fastapi import Response, status

from api.routes import cio_diagnostic
from scripts import capture_render_production_telemetry as telemetry


EXPECTED_RELEASE = "release-live-telemetry"


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


def test_live_telemetry_route_is_registered_as_get():
    routes = {
        getattr(route, "path", ""): route for route in cio_diagnostic.router.routes
    }
    route = routes["/v1/operations/cio-diagnostic/telemetry"]
    assert "GET" in route.methods


def test_render_telemetry_workflow_reads_live_endpoint_not_static_snapshot():
    workflow = Path(".github/workflows/render-production-telemetry.yml").read_text(
        encoding="utf-8"
    )
    assert "/v1/operations/cio-diagnostic/telemetry" in workflow
    assert "/app/static/cio-diagnostic.json" not in workflow
