from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import requests

from data.decision_information import InformationSourceType, PortfolioImpactChannel
from providers.public_live_information import (
    PublicLiveSourceCatalog,
    PublicLiveSourceDefinition,
    load_public_live_source_catalog,
)
from providers.public_live_information_extended import (
    ImpactfulPublicLiveInformationProvider,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "public_live_information_sources.json"
NOW = datetime(2026, 7, 28, 2, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(
        self,
        payload: Any | None = None,
        *,
        text: str | None = None,
        content: bytes | None = None,
    ) -> None:
        self._payload = payload
        if text is None:
            text = "" if payload is None else json.dumps(payload)
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")

    def json(self) -> Any:
        if self._payload is None:
            raise json.JSONDecodeError("not json", self.text, 0)
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _source(
    parser: str,
    *,
    identifier: str | None = None,
    endpoint: str = "https://example.test/source",
    credentials: tuple[str, ...] = (),
) -> PublicLiveSourceDefinition:
    return PublicLiveSourceDefinition(
        identifier=identifier or f"source:{parser}",
        source_name=f"Test {parser}",
        parser=parser,
        endpoint=endpoint,
        source_type=InformationSourceType.OFFICIAL,
        independence_group=f"group:{parser}",
        domains=("current_events_news",),
        impact_channels=(
            PortfolioImpactChannel.GROWTH,
            PortfolioImpactChannel.VOLATILITY,
        ),
        enabled=True,
        required=True,
        credential_environment_variables=credentials,
        user_agent_environment_variable=None,
        parameters={},
        headers={},
        maximum_records=100,
        reliability=0.99,
        relevance=0.8,
        materiality=0.7,
        license_identifier="license:test",
        usage_rights_identifier="rights:test",
        limitations=("required",),
    )


def _provider(
    source: PublicLiveSourceDefinition,
    response: FakeResponse,
) -> ImpactfulPublicLiveInformationProvider:
    return ImpactfulPublicLiveInformationProvider(
        PublicLiveSourceCatalog("catalog:test", (source,)),
        http_get=lambda *args, **kwargs: response,
        clock=lambda: NOW,
        sleeper=lambda _: None,
    )


def test_catalog_declares_high_impact_omissions() -> None:
    catalog = load_public_live_source_catalog(CATALOG)
    identifiers = {item.identifier for item in catalog.sources}

    assert {
        "federal-register-live",
        "ofac-sdn-live",
        "ofac-consolidated-live",
        "fema-disasters-live",
        "openfda-food-recalls-live",
        "openfda-drug-recalls-live",
        "openfda-device-recalls-live",
        "who-disease-outbreaks-live",
        "nasa-firms-fire-live",
        "imf-global-growth-live",
    } <= identifiers
    assert len(catalog.sources) >= 20


def test_federal_register_normalizes_agency_and_blank_optional_tag() -> None:
    response = FakeResponse(
        {
            "results": [
                {
                    "document_number": "2026-12345",
                    "title": "Material rule affecting financial markets",
                    "abstract": "An agency adopted a material final rule.",
                    "publication_date": "2026-07-28",
                    "type": "Rule",
                    "presidential_document_type": None,
                    "agencies": [{"name": "Securities and Exchange Commission"}],
                }
            ]
        }
    )

    report = _provider(_source("federal_register"), response).collect()

    assert report.live_record_count == 1
    record = report.records[0]
    assert record.provenance.source_identifier == "2026-12345"
    assert record.entities == ("Securities and Exchange Commission",)
    assert record.tags == ("current_events_news", "Rule")


def test_ofac_csv_creates_governed_sanctions_record() -> None:
    csv_text = (
        "ent_num,SDN_Name,SDN_Type,Program,Remarks\n"
        "12345,Example Holdings Ltd.,Entity,TEST-PROGRAM,Subject to blocking restrictions\n"
    )

    report = _provider(
        _source("ofac_csv"),
        FakeResponse(text=csv_text),
    ).collect()

    assert report.live_record_count == 1
    record = report.records[0]
    assert record.topic == "OFAC sanctions listing: Example Holdings Ltd."
    assert record.entities == ("Example Holdings Ltd.",)
    assert "TEST-PROGRAM" in record.tags
    assert "sanctions-list" in record.tags


def test_openfda_compact_dates_and_recall_exposure_are_normalized() -> None:
    response = FakeResponse(
        {
            "results": [
                {
                    "recall_number": "F-1234-2026",
                    "recalling_firm": "Example Foods Inc.",
                    "product_description": "Packaged food product",
                    "reason_for_recall": "Potential contamination",
                    "classification": "Class I",
                    "status": "Ongoing",
                    "recall_initiation_date": "20260720",
                    "report_date": "20260728",
                    "state": "CA",
                    "country": "United States",
                    "distribution_pattern": "Nationwide",
                }
            ]
        }
    )

    report = _provider(_source("openfda_enforcement"), response).collect()

    record = report.records[0]
    assert record.event_at == datetime(2026, 7, 20, tzinfo=timezone.utc)
    assert record.published_at == datetime(2026, 7, 28, tzinfo=timezone.utc)
    assert record.entities == ("Example Foods Inc.",)
    assert record.geographies == ("CA", "United States", "Nationwide")


def test_fema_declaration_preserves_incident_and_declaration_boundaries() -> None:
    response = FakeResponse(
        {
            "DisasterDeclarationsSummaries": [
                {
                    "disasterNumber": 4999,
                    "declarationTitle": "SEVERE STORMS",
                    "incidentType": "Severe Storm",
                    "declarationType": "DR",
                    "state": "TX",
                    "designatedArea": "Example County",
                    "incidentBeginDate": "2026-07-20T00:00:00.000Z",
                    "declarationDate": "2026-07-27T00:00:00.000Z",
                }
            ]
        }
    )

    report = _provider(_source("fema_open"), response).collect()

    record = report.records[0]
    assert record.event_at == datetime(2026, 7, 20, tzinfo=timezone.utc)
    assert record.published_at == datetime(2026, 7, 27, tzinfo=timezone.utc)
    assert record.geographies == ("TX", "Example County")


def test_who_markup_is_removed_before_persistence() -> None:
    response = FakeResponse(
        {
            "value": [
                {
                    "DonId": "DON-999",
                    "Title": "International health event",
                    "Summary": "<p>Confirmed <strong>public health</strong> event.</p>",
                    "PublicationDateAndTime": "2026-07-27T18:00:00Z",
                    "WhoRegionCode": "AFRO",
                }
            ]
        }
    )

    report = _provider(
        _source("who_disease_outbreaks"),
        response,
    ).collect()

    record = report.records[0]
    assert record.summary == "Confirmed public health event."
    assert "<" not in record.summary
    assert record.geographies == ("AFRO",)


def test_path_secret_is_substituted_but_redacted_from_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "firms-key-do-not-emit"
    monkeypatch.setenv("NASA_FIRMS_MAP_KEY", secret)
    source = _source(
        "firms_csv",
        endpoint=(
            "https://firms.example/api/${NASA_FIRMS_MAP_KEY}/world.csv"
        ),
        credentials=("NASA_FIRMS_MAP_KEY",),
    )

    def fail(url: str, **kwargs: Any) -> Any:
        assert secret in url
        raise requests.RequestException(f"failed URL {url}")

    provider = ImpactfulPublicLiveInformationProvider(
        PublicLiveSourceCatalog("catalog:secret", (source,)),
        http_get=fail,
        clock=lambda: NOW,
        sleeper=lambda _: None,
        max_attempts=1,
    )

    report = provider.collect()
    serialized = json.dumps(report.to_dict(include_records=True))

    assert report.sources[0].succeeded is False
    assert secret not in serialized
    assert "***" in (report.sources[0].error or "")
