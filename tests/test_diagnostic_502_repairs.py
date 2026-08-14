from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from providers.massive_futures_reference import MassiveFuturesReferenceProvider
from providers.massive_multi_asset import MassiveMultiAssetError
from scripts.enrich_render_production_telemetry import enrich_snapshot


class _FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers: dict[str, str] = {}
        self.text = ""

    def json(self) -> object:
        return self._payload


class _SequentialGet:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, url: str, *, params: dict[str, object], timeout: int):
        self.calls.append((url, dict(params)))
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        return self.responses.pop(0)


def _provider(response: _FakeResponse) -> MassiveFuturesReferenceProvider:
    return MassiveFuturesReferenceProvider(
        api_key="super-secret-key",
        http_get=_SequentialGet([response]),
        sleeper=lambda _: None,
        minimum_call_interval_seconds=0,
        reference_max_attempts=1,
    )


def test_futures_reference_empty_response_is_attributable_and_credential_safe() -> None:
    provider = _provider(_FakeResponse(200, {"results": []}))

    with pytest.raises(MassiveMultiAssetError) as raised:
        provider.futures_contracts(
            as_of=datetime(2026, 8, 13, tzinfo=timezone.utc),
            product_codes=("ES",),
            maximum_pages=1,
        )

    detail = str(raised.value)
    assert '"reason":"empty_provider_response"' in detail
    assert '"root":"ES"' in detail
    assert "super-secret-key" not in detail
    telemetry = provider.reference_telemetry[0]
    assert telemetry["http_status"] == 200
    assert telemetry["raw_result_count"] == 0
    assert telemetry["usable_count"] == 0
    assert "apiKey" not in telemetry["request_params"]


def test_futures_reference_entitlement_failure_preserves_safe_root_telemetry() -> None:
    provider = _provider(_FakeResponse(403, {"error": "forbidden"}))

    with pytest.raises(MassiveMultiAssetError) as raised:
        provider.futures_contracts(
            as_of=datetime(2026, 8, 13, tzinfo=timezone.utc),
            product_codes=("ES",),
            maximum_pages=1,
        )

    detail = str(raised.value)
    assert '"status":403' in detail
    assert '"reason":"provider_auth_or_entitlement"' in detail
    assert "super-secret-key" not in detail


def test_futures_reference_root_mismatch_is_distinguished_from_empty_provider() -> None:
    provider = _provider(
        _FakeResponse(
            200,
            {
                "results": [
                    {
                        "ticker": "NQZ6",
                        "product_code": "NQ",
                        "trading_venue": "XCME",
                        "first_trade_date": "2026-01-01",
                        "last_trade_date": "2026-12-31",
                        "active": True,
                    }
                ]
            },
        )
    )

    with pytest.raises(MassiveMultiAssetError) as raised:
        provider.futures_contracts(
            as_of=datetime(2026, 8, 13, tzinfo=timezone.utc),
            product_codes=("ES",),
            maximum_pages=1,
        )

    detail = str(raised.value)
    assert '"raw":1' in detail
    assert '"parsed":1' in detail
    assert '"matched":0' in detail
    assert '"reason":"root_mismatch"' in detail


def test_telemetry_enrichment_keeps_reference_metrics_and_root_breakdown() -> None:
    snapshot = {
        "expected_release": "abc123",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        "diagnostic": {
            "diagnostic_id": "req-1",
            "progress_metrics": {},
        },
    }
    public_payload = {
        "active_release": "abc123",
        "release_matches": True,
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        "request_id": "req-1",
        "progress_metrics": {
            "configured_futures_roots": 13,
            "catalog_records": 0,
            "reused": 0,
            "not_allowlisted": 999,
        },
        "detail": (
            "Reference readiness failed; massive_futures_telemetry="
            '[{"root":"ES","status":200,"raw":0,"parsed":0,'
            '"matched":0,"valid":0,"usable":0,"reason":"empty_provider_response"}]'
        ),
    }

    enriched = enrich_snapshot(
        snapshot,
        public_payload,
        expected_release="abc123",
    )

    diagnostic = enriched["diagnostic"]
    assert diagnostic["progress_metrics"] == {
        "configured_futures_roots": 13,
        "catalog_records": 0,
        "reused": 0,
    }
    assert diagnostic["futures_reference_failure_roots"] == 1
    assert diagnostic["futures_reference_telemetry"][0]["reason"] == "empty_provider_response"
    assert "detail" not in diagnostic


def test_deployment_verifier_ignores_stale_same_release_request(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CIO_DIAGNOSTIC_FRESH_AFTER", "2026-08-14T00:40:00+00:00")
    import verify_render_cio_diagnostic as verifier

    stale = {
        "active_release": "abc123",
        "release_matches": True,
        "state": "failed",
        "request_id": "old-request",
        "requested_at": "2026-08-14T00:30:00+00:00",
        "completed_at": "2026-08-14T00:31:00+00:00",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }
    fresh = {
        "active_release": "abc123",
        "release_matches": True,
        "state": "completed",
        "request_id": "new-request",
        "requested_at": "2026-08-14T00:41:00+00:00",
        "completed_at": "2026-08-14T00:42:00+00:00",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }
    responses = iter((stale, fresh))
    messages: list[str] = []

    result = verifier.poll_render_audit(
        url="https://example.invalid/audit.json",
        expected_release="abc123",
        output_path=tmp_path / "audit.json",
        maximum_attempts=5,
        interval_seconds=0,
        fetcher=lambda _: next(responses),
        sleeper=lambda _: None,
        progress_writer=messages.append,
    )

    assert result["request_id"] == "new-request"
    assert any("fresh_request_observed" in message for message in messages)


def test_deployment_verifier_reports_machine_readable_stale_snapshot(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CIO_DIAGNOSTIC_FRESH_AFTER", "2026-08-14T00:40:00+00:00")
    import verify_render_cio_diagnostic as verifier

    wrapper_globals = verifier.poll_render_audit.__globals__
    monkeypatch.setitem(wrapper_globals, "_SERVER_REPLACEMENT_GRACE_ATTEMPTS", 3)
    stale = {
        "active_release": "abc123",
        "release_matches": True,
        "state": "failed",
        "request_id": "old-request",
        "requested_at": "2026-08-14T00:30:00+00:00",
        "completed_at": "2026-08-14T00:31:00+00:00",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }

    with pytest.raises(verifier.RenderAuditVerificationError) as raised:
        verifier.poll_render_audit(
            url="https://example.invalid/audit.json",
            expected_release="abc123",
            output_path=tmp_path / "audit.json",
            maximum_attempts=5,
            interval_seconds=0,
            fetcher=lambda _: stale,
            sleeper=lambda _: None,
            progress_writer=None,
        )

    assert str(raised.value).startswith("stale_diagnostic_snapshot:")
    assert "request_id=old-request" in str(raised.value)
