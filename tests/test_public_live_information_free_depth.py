from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data.decision_information import InformationSourceType, PortfolioImpactChannel
from providers.public_live_information import PublicLiveSourceCatalog, PublicLiveSourceDefinition
from providers.public_live_information_free_depth import FreeDecisionDepthInformationProvider
from providers.public_live_source_catalogs import load_operating_public_live_source_catalog


ROOT = Path(__file__).resolve().parents[1]
BASE_CATALOG = ROOT / "config" / "public_live_information_sources.json"
NOW = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(
        self,
        payload: Any | None = None,
        *,
        text: str | None = None,
    ) -> None:
        self._payload = payload if payload is not None else {}
        self.text = text if text is not None else json.dumps(self._payload)
        self.content = self.text.encode("utf-8")

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _source(parser: str) -> PublicLiveSourceDefinition:
    return PublicLiveSourceDefinition(
        identifier=f"test:{parser}",
        source_name=f"Test {parser}",
        parser=parser,
        endpoint="https://example.test/data",
        source_type=InformationSourceType.RESEARCH,
        independence_group=f"test-{parser}",
        domains=("test",),
        impact_channels=(PortfolioImpactChannel.EARNINGS,),
        enabled=True,
        required=False,
        credential_environment_variables=(),
        user_agent_environment_variable=None,
        parameters={},
        headers={},
        maximum_records=500,
        reliability=0.9,
        relevance=0.9,
        materiality=0.8,
        license_identifier="test-license",
        usage_rights_identifier="test-rights",
        limitations=(),
    )


def _provider(source: PublicLiveSourceDefinition, response: FakeResponse) -> FreeDecisionDepthInformationProvider:
    return FreeDecisionDepthInformationProvider(
        PublicLiveSourceCatalog(f"catalog:{source.parser}", (source,)),
        http_get=lambda *args, **kwargs: response,
        clock=lambda: NOW,
        sleeper=lambda _: None,
    )


def test_operating_catalog_adds_only_keyless_active_depth_sources() -> None:
    catalog = load_operating_public_live_source_catalog(BASE_CATALOG)
    sources = {source.identifier: source for source in catalog.sources}

    assert "xbrl-global-filings-live" in sources
    assert "treasury-tic-slt-live" in sources
    assert "coinmetrics-community-onchain-shadow" in sources
    assert sources["xbrl-global-filings-live"].credential_environment_variables == ()
    assert sources["treasury-tic-slt-live"].credential_environment_variables == ()
    assert sources["xbrl-global-filings-live"].enabled is True
    assert sources["treasury-tic-slt-live"].enabled is True
    assert sources["coinmetrics-community-onchain-shadow"].enabled is False


def test_xbrl_global_filing_index_preserves_conservative_availability() -> None:
    source = _source("xbrl_filings")
    response = FakeResponse(
        {
            "data": [
                {
                    "type": "filing",
                    "id": "filing-123",
                    "attributes": {
                        "country": "GB",
                        "period_end": "2025-12-31",
                        "processed": "2026-03-15T11:30:00Z",
                        "filing_system": "UKSEF",
                        "language": "en",
                    },
                    "relationships": {
                        "entity": {"data": {"type": "entity", "id": "LEI123"}}
                    },
                }
            ],
            "included": [
                {
                    "type": "entity",
                    "id": "LEI123",
                    "attributes": {"name": "Example plc", "lei": "LEI123"},
                }
            ],
        }
    )

    report = _provider(source, response).collect()

    assert report.live_record_count == 1
    record = report.records[0]
    assert record.topic == "Structured company filing: Example plc"
    assert record.geographies == ("GB",)
    assert "global-fundamental-disclosure" in record.tags
    assert record.event_at == datetime(2025, 12, 31, tzinfo=timezone.utc)
    assert record.published_at == datetime(2026, 3, 15, 11, 30, tzinfo=timezone.utc)
    assert record.available_at == NOW


def test_xbrl_follows_bounded_json_link_and_extracts_real_fundamental_facts() -> None:
    source = _source("xbrl_filings")
    index_payload = {
        "data": [
            {
                "type": "filing",
                "id": "filing-456",
                "attributes": {
                    "country": "FR",
                    "period_end": "2025-12-31",
                    "publication_date": "2026-03-20T07:00:00Z",
                    "processed": "2026-03-20T08:00:00Z",
                    "filing_system": "ESEF",
                    "language": "en",
                    "json_url": "https://example.test/filing-456.json",
                },
                "relationships": {
                    "entity": {"data": {"type": "entity", "id": "LEI456"}}
                },
            }
        ],
        "included": [
            {
                "type": "entity",
                "id": "LEI456",
                "attributes": {"name": "Global Example SA", "identifier": "LEI456"},
            }
        ],
    }
    fact_payload = {
        "facts": {
            "f1": {
                "value": 1250000000,
                "dimensions": {
                    "concept": "ifrs-full:Revenue",
                    "entity": "LEI456",
                    "period": "2025-01-01T00:00:00/2026-01-01T00:00:00",
                    "unit": "iso4217:EUR",
                },
            },
            "f2": {
                "value": 210000000,
                "dimensions": {
                    "concept": "ifrs-full:ProfitLoss",
                    "entity": "LEI456",
                    "period": "2025-01-01T00:00:00/2026-01-01T00:00:00",
                    "unit": "iso4217:EUR",
                },
            },
            "ignored": {
                "value": "Example text",
                "dimensions": {
                    "concept": "ifrs-full:NameOfReportingEntityOrOtherMeansOfIdentification",
                    "entity": "LEI456",
                    "period": "2025-12-31T00:00:00",
                },
            },
        }
    }

    def http_get(url: str, **_kwargs: object) -> FakeResponse:
        if url == source.endpoint:
            return FakeResponse(index_payload)
        assert url == "https://example.test/filing-456.json"
        return FakeResponse(fact_payload)

    provider = FreeDecisionDepthInformationProvider(
        PublicLiveSourceCatalog("catalog:xbrl-facts", (source,)),
        http_get=http_get,
        clock=lambda: NOW,
        sleeper=lambda _: None,
    )
    report = provider.collect()

    fundamental_records = [
        record for record in report.records if "structured-global-fundamentals" in record.tags
    ]
    assert {record.topic for record in fundamental_records} == {
        "Global Example SA revenue",
        "Global Example SA net-income",
    }
    assert all(record.published_at == datetime(2026, 3, 20, 7, 0, tzinfo=timezone.utc) for record in fundamental_records)
    assert all(record.available_at == NOW for record in fundamental_records)
    assert all("LEI456" in record.entities for record in fundamental_records)


def test_treasury_tic_emits_latest_country_cross_border_capital_rows() -> None:
    source = _source("treasury_tic_slt")
    text = "\n".join(
        [
            "Table 1: U.S. Long-Term Securities Held by Foreign Residents",
            "Millions of dollars",
            "Country\tCountry Code\tDate\tHoldings\tNet U.S. Sales\tValuation Change\tHoldings",
            "country\tcountry_code\tdate\tfor_lt_total_pos\tfor_lt_total_net\tfor_lt_total_valchg\tfor_lt_treas_pos\tfor_lt_treas_net\tfor_lt_treas_valchg\tfor_lt_agcy_pos\tfor_lt_agcy_net\tfor_lt_agcy_valchg\tfor_lt_corp_pos\tfor_lt_corp_net\tfor_lt_corp_valchg\tfor_lt_eqty_pos\tfor_lt_eqty_net\tfor_lt_eqty_valchg",
            "Japan\t58800\t2026-05\t2500000\t1000\t5000\t1100000\t500\t1000\t100000\t0\t0\t600000\t200\t500\t700000\t300\t3500",
            "Japan\t58800\t2026-04\t2400000\t900\t4000\t1050000\t400\t900\t100000\t0\t0\t580000\t200\t400\t670000\t300\t2700",
            "Canada\t15600\t2026-05\t1800000\t-250\t2000\t500000\t-100\t100\t150000\t0\t0\t450000\t-50\t300\t700000\t-100\t1600",
        ]
    )

    report = _provider(source, FakeResponse(text=text)).collect()

    assert report.live_record_count == 2
    assert {record.geographies[0] for record in report.records} == {"Japan", "Canada"}
    assert all(record.event_at == datetime(2026, 5, 1, tzinfo=timezone.utc) for record in report.records)
    assert all(record.published_at == NOW for record in report.records)
    assert all("cross-border-capital" in record.tags for record in report.records)


def test_coinmetrics_parser_is_shadow_network_evidence_not_price_authority() -> None:
    source = _source("coinmetrics_asset_metrics")
    response = FakeResponse(
        {
            "data": [
                {
                    "asset": "btc",
                    "time": "2026-08-09T00:00:00Z",
                    "AdrActCnt": "812345",
                    "TxCnt": "510000",
                    "FeeTotUSD": "7200000",
                }
            ]
        }
    )

    report = _provider(source, response).collect()

    assert report.live_record_count == 1
    record = report.records[0]
    assert record.entities == ("BTC",)
    assert "onchain-crypto-network" in record.tags
    assert "shadow-research-only" in record.tags
    assert record.published_at == NOW
