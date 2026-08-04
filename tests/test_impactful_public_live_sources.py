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
        "bls-labor-inflation-live",
        "nyfed-sofr-live",
        "treasury-yield-curve-live",
        "ecb-data-portal-live",
        "eurostat-gdp-live",
        "bea-national-accounts-live",
        "census-economic-indicators-live",
    } <= identifiers
    assert len(catalog.sources) >= 28


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



def test_bls_series_normalizes_official_observation() -> None:
    response = FakeResponse(
        {
            "status": "REQUEST_SUCCEEDED",
            "Results": {
                "series": [
                    {
                        "seriesID": "CUSR0000SA0",
                        "data": [{"year": "2026", "period": "M06", "value": "329.1"}],
                    }
                ]
            },
        }
    )

    record = _provider(_source("bls_series"), response).collect().records[0]

    assert record.provenance.source_identifier == "CUSR0000SA0:2026:M06"
    assert record.event_at == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert "329.1" in record.summary


def test_new_york_fed_reference_rate_normalizes_effective_date() -> None:
    response = FakeResponse(
        {
            "refRates": [
                {
                    "type": "SOFR",
                    "effectiveDate": "2026-07-27",
                    "percentRate": 4.31,
                    "revisionIndicator": "",
                }
            ]
        }
    )

    record = _provider(_source("nyfed_rates"), response).collect().records[0]

    assert record.event_at == datetime(2026, 7, 27, tzinfo=timezone.utc)
    assert record.topic == "New York Fed SOFR"


def test_treasury_yield_xml_preserves_curve_observation() -> None:
    xml = b'''<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
          xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
      <entry><content type="application/xml"><m:properties>
        <d:NEW_DATE>2026-07-27T00:00:00</d:NEW_DATE>
        <d:BC_1MONTH>4.30</d:BC_1MONTH><d:BC_10YEAR>4.12</d:BC_10YEAR>
      </m:properties></content></entry>
    </feed>'''

    record = _provider(
        _source("treasury_yield_xml"), FakeResponse(content=xml)
    ).collect().records[0]

    assert record.topic == "U.S. Treasury yield curve"
    assert "10YEAR=4.12%" in record.summary


def test_sdmx_csv_normalizes_ecb_observation() -> None:
    csv_text = "FREQ,REF_AREA,MEASURE,UNIT_MEASURE,TIME_PERIOD,OBS_VALUE\nD,EA,EXR,USD,2026-07-27,1.17\n"

    record = _provider(
        _source("sdmx_csv"), FakeResponse(text=csv_text)
    ).collect().records[0]

    assert record.event_at == datetime(2026, 7, 27, tzinfo=timezone.utc)
    assert record.geographies == ("EA",)


def test_eurostat_jsonstat_normalizes_latest_period() -> None:
    response = FakeResponse(
        {
            "value": {"0": 3210000.0},
            "dimension": {"time": {"category": {"index": {"2026-Q1": 0}}}},
        }
    )

    record = _provider(_source("eurostat_jsonstat"), response).collect().records[0]

    assert "3210000.0" in record.summary
    assert "eurostat" in record.tags


def test_bea_api_normalizes_national_accounts() -> None:
    response = FakeResponse(
        {
            "BEAAPI": {
                "Results": {
                    "Data": [
                        {
                            "TimePeriod": "2026Q2",
                            "DataValue": "30,000.0",
                            "LineDescription": "Gross domestic product",
                            "TableName": "T10101",
                        }
                    ]
                }
            }
        }
    )

    record = _provider(_source("bea_api"), response).collect().records[0]

    assert record.topic == "BEA Gross domestic product"
    assert "30,000.0" in record.summary


def test_census_eits_normalizes_tabular_payload() -> None:
    response = FakeResponse(
        [["cell_value", "time", "seasonally_adj"], ["720000", "2026-06", "yes"]]
    )

    record = _provider(_source("census_eits"), response).collect().records[0]

    assert record.topic == "Census cell_value"
    assert record.event_at == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_runtime_date_placeholders_are_rendered_without_credentials() -> None:
    source = _source(
        "sdmx_csv",
        endpoint="https://example.test/${CURRENT_YEAR}/source",
    )
    captured: dict[str, Any] = {}

    def get(url: str, **kwargs: Any) -> FakeResponse:
        captured["url"] = url
        return FakeResponse(text="TIME_PERIOD,OBS_VALUE\n2026-07-01,1.0\n")

    provider = ImpactfulPublicLiveInformationProvider(
        PublicLiveSourceCatalog("catalog:runtime", (source,)),
        http_get=get,
        clock=lambda: NOW,
        sleeper=lambda _: None,
    )

    report = provider.collect()

    assert report.sources[0].succeeded is True
    assert captured["url"] == "https://example.test/2026/source"
