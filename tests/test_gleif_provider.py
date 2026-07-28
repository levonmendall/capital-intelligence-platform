"""Tests for the free GLEIF legal-entity adapter."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data import IdentifierScheme
from providers.gleif import GLEIF_LEI_RECORD_URL, GleifProvider, GleifProviderError

UTC = timezone.utc
NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
LEI = "HWUPKR0MPOU8FGXBT394"


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self._payload


def _payload(*, record_id: str = LEI) -> dict[str, object]:
    return {
        "data": {
            "type": "lei-records",
            "id": record_id,
            "attributes": {
                "lei": LEI,
                "bic": ["APPLEUS33"],
                "entity": {
                    "legalName": {"name": "APPLE INC."},
                    "status": "ACTIVE",
                    "legalJurisdiction": "US-CA",
                    "legalAddress": {"country": "US"},
                    "headquartersAddress": {"country": "US"},
                },
                "registration": {"status": "ISSUED"},
            },
        }
    }


def test_fetch_lei_preserves_legal_identity_and_lineage() -> None:
    captured: dict[str, object] = {}

    def get(url: str, **kwargs: object) -> _Response:
        captured.update({"url": url, **kwargs})
        return _Response(_payload())

    record = GleifProvider(clock=lambda: NOW, http_get=get).fetch_lei(LEI.lower())

    assert captured["url"] == GLEIF_LEI_RECORD_URL.format(lei=LEI)
    assert captured["headers"] == {"Accept": "application/vnd.api+json"}
    assert record.lei == LEI
    assert record.legal_name == "APPLE INC."
    assert record.entity_status == "ACTIVE"
    assert record.registration_status == "ISSUED"
    assert record.legal_jurisdiction == "US-CA"
    assert record.bic_codes == ("APPLEUS33",)
    assert len(record.content_hash) == 64
    assert record.retrieved_at == NOW
    assert record.issuer.issuer_id == f"GLEIF:LEI:{LEI}"
    assert all(
        identifier.scheme is IdentifierScheme.PROVIDER
        for identifier in record.issuer.identifiers
    )
    assert {item.value for item in record.issuer.identifiers} == {
        f"LEI:{LEI}",
        "BIC:APPLEUS33",
    }


def test_fetch_lei_rejects_mismatched_or_invalid_documents() -> None:
    provider = GleifProvider(
        clock=lambda: NOW,
        http_get=lambda *args, **kwargs: _Response(_payload(record_id="X" * 20)),
    )
    with pytest.raises(GleifProviderError, match="different LEI"):
        provider.fetch_lei(LEI)

    invalid = GleifProvider(
        clock=lambda: NOW,
        http_get=lambda *args, **kwargs: _Response({"data": {}}, status_code=200),
    )
    with pytest.raises(GleifProviderError, match="missing attributes"):
        invalid.fetch_lei(LEI)


def test_fetch_lei_rejects_http_failure_and_malformed_identifier() -> None:
    provider = GleifProvider(
        clock=lambda: NOW,
        http_get=lambda *args, **kwargs: _Response({}, status_code=503),
    )
    with pytest.raises(GleifProviderError, match="HTTP 503"):
        provider.fetch_lei(LEI)

    with pytest.raises(ValueError, match="20-character"):
        provider.fetch_lei("too-short")
