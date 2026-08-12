from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Response, status

from api.routes.provider_validation import provider_validation_status
from data.provider_dataset import ProviderDatasetType
from operations.provider_validation import (
    ProviderValidationCheck,
    ProviderValidationError,
    ProviderValidationReport,
    load_provider_validation_report,
    require_provider_validation,
    validate_live_providers,
    write_provider_validation_report,
)

NOW = datetime(2026, 7, 31, 17, 0, tzinfo=timezone.utc)


class _Snapshot:
    def __init__(self, *, payload, identifier: str):
        self.payload = payload
        self.retrieved_at = NOW
        self.provider_record_id = identifier
        self.content_hash = "a" * 64
        self.provider = "TEST"
        self.source_version = "test.v1"


class _EODHD:
    configured = True

    def fetch_dataset(self, query):
        if query.dataset_type is ProviderDatasetType.ACCOUNT_ENTITLEMENT:
            return _Snapshot(payload={"apiRequests": 10}, identifier="eodhd:account")
        if query.dataset_type is ProviderDatasetType.EXCHANGE_DIRECTORY:
            return _Snapshot(payload=[{"Code": "LSE"}], identifier="eodhd:exchanges")
        raise AssertionError(query.dataset_type)


class _MissingEODHD:
    configured = False


class _DeprecatedProvider:
    configured = False

    def __getattr__(self, name):
        raise AssertionError(f"deprecated provider must not be contacted: {name}")


class _Response:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _http_get(url, **_kwargs):
    if "/chart/" in url:
        return _Response(
            {
                "chart": {
                    "result": [
                        {
                            "timestamp": [1, 2, 3],
                            "indicators": {"quote": [{"close": [600.0, 605.0, 610.0]}]},
                        }
                    ]
                }
            }
        )
    raise AssertionError(url)


def _passed_report(*, generated_at: datetime = NOW, release: str = "release-1"):
    return ProviderValidationReport(
        release=release,
        generated_at=generated_at,
        checks=(
            ProviderValidationCheck(
                name="required",
                provider="TEST",
                required=True,
                state="passed",
                detail="passed",
                observed_at=generated_at,
                evidence_fingerprint="b" * 64,
            ),
        ),
    )


def test_live_provider_validation_is_credential_safe_and_ready():
    report = validate_live_providers(
        release="release-1",
        clock=lambda: NOW,
        http_get=_http_get,
        eodhd_provider=_EODHD(),
    )
    assert report.ready is True
    assert len(report.checks) == 3
    assert {item.name for item in report.checks if item.required} == {
        "eodhd_account_entitlement",
        "eodhd_exchange_directory",
        "yahoo_chart_evidence",
    }
    payload = report.to_dict()
    encoded = json.dumps(payload)
    assert payload["schema_version"] == "capital-intelligence-provider-validation.v1"
    assert payload["credentials_exposed"] is False
    assert payload["real_money_authorized"] is False
    assert "databento" not in encoded.lower()
    assert "secret" not in encoded.lower()


def test_missing_required_eodhd_credentials_fail_closed():
    report = validate_live_providers(
        release="release-1",
        clock=lambda: NOW,
        http_get=_http_get,
        eodhd_provider=_MissingEODHD(),
    )
    assert report.ready is False
    assert report.failed_required_checks == (
        "eodhd_account_entitlement",
        "eodhd_exchange_directory",
    )
    with pytest.raises(ProviderValidationError, match="eodhd_account_entitlement"):
        require_provider_validation(report)


def test_deprecated_databento_arguments_are_ignored_without_contact():
    report = validate_live_providers(
        release="release-1",
        clock=lambda: NOW,
        http_get=_http_get,
        eodhd_provider=_EODHD(),
        databento_provider=_DeprecatedProvider(),
        databento_options_provider=_DeprecatedProvider(),
    )
    assert report.ready is True
    assert all("databento" not in item.name for item in report.checks)


def test_provider_validation_report_round_trip(tmp_path):
    path = tmp_path / "provider-validation.json"
    report = _passed_report()
    written = write_provider_validation_report(report, path)
    assert written == path
    loaded = load_provider_validation_report(path)
    assert loaded is not None
    assert loaded["ready"] is True
    assert loaded["release"] == "release-1"


def test_provider_validation_route_requires_current_release(monkeypatch, tmp_path):
    path = tmp_path / "provider-validation.json"
    now = datetime.now(timezone.utc)
    write_provider_validation_report(_passed_report(generated_at=now, release="release-1"), path)
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_REPORT", str(path))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_RELEASE", "release-1")
    response = Response()
    payload = provider_validation_status(response)
    assert response.status_code == status.HTTP_200_OK
    assert payload["ready"] is True
    assert payload["fresh"] is True
    assert payload["release_matches"] is True


def test_provider_validation_route_blocks_stale_evidence(monkeypatch, tmp_path):
    path = tmp_path / "provider-validation.json"
    write_provider_validation_report(
        _passed_report(
            generated_at=datetime.now(timezone.utc) - timedelta(days=8),
            release="release-1",
        ),
        path,
    )
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_REPORT", str(path))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_MAX_AGE_HOURS", "24")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_RELEASE", "release-1")
    response = Response()
    payload = provider_validation_status(response)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert payload["ready"] is False
    assert payload["fresh"] is False
