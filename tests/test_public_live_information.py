from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from data.decision_information import InformationSourceType, PortfolioImpactChannel
from providers.public_live_information import (
    PublicLiveInformationProvider,
    PublicLiveSourceCatalog,
    PublicLiveSourceDefinition,
    load_public_live_source_catalog,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "config" / "public_live_information_sources.json"
SCHEMA_PATH = ROOT / "schemas" / "public_live_information_sources.schema.json"
NOW = datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload: Any, *, content: bytes | None = None) -> None:
        self._payload = payload
        self.content = content if content is not None else json.dumps(payload).encode("utf-8")

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _source(
    *,
    parser: str = "gdelt_doc",
    credentials: tuple[str, ...] = (),
    required: bool = True,
) -> PublicLiveSourceDefinition:
    return PublicLiveSourceDefinition(
        identifier="source:test",
        source_name="Test Source",
        parser=parser,
        endpoint="https://example.test/feed",
        source_type=InformationSourceType.OFFICIAL,
        independence_group="test-source",
        domains=("current_events_news",),
        impact_channels=(PortfolioImpactChannel.GROWTH, PortfolioImpactChannel.VOLATILITY),
        enabled=True,
        required=required,
        credential_environment_variables=credentials,
        user_agent_environment_variable=None,
        parameters={},
        headers={},
        maximum_records=10,
        reliability=0.9,
        relevance=0.8,
        materiality=0.7,
        license_identifier="license:test",
        usage_rights_identifier="rights:test",
        limitations=(("required",) if required else ()) + ("metadata only",),
    )


def test_catalog_matches_schema_and_declares_broad_public_sources() -> None:
    import jsonschema

    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)
    catalog = load_public_live_source_catalog(CATALOG_PATH)

    identifiers = {item.identifier for item in catalog.sources}
    assert {
        "gdelt-global-news-discovery",
        "federal-reserve-live",
        "ecb-live",
        "sec-press-live",
        "cftc-positioning-live",
        "nws-weather-alerts-live",
        "usgs-earthquakes-live",
        "cisa-kev-live",
        "treasury-fiscal-live",
        "world-bank-global-growth-live",
        "eia-energy-live",
    } <= identifiers
    assert all(item.endpoint.startswith("https://") for item in catalog.sources)
    assert all(item.license_identifier for item in catalog.sources)
    assert all(item.usage_rights_identifier for item in catalog.sources)


def test_gdelt_collection_preserves_metadata_without_article_body() -> None:
    payload = {
        "articles": [
            {
                "title": "Central bank signals policy change",
                "url": "https://publisher.example/story",
                "domain": "publisher.example",
                "seendate": "20260728T005500Z",
                "sourcecountry": "United States",
                "language": "English",
            }
        ]
    }
    provider = PublicLiveInformationProvider(
        PublicLiveSourceCatalog("catalog:test", (_source(),)),
        http_get=lambda *args, **kwargs: FakeResponse(payload),
        clock=lambda: NOW,
        sleeper=lambda _: None,
    )

    report = provider.collect()

    assert report.successful_source_count == 1
    assert report.live_record_count == 1
    record = report.records[0]
    assert record.topic == "Central bank signals policy change"
    assert record.provenance.source_identifier == "https://publisher.example/story"
    assert "metadata-only" in record.tags
    assert record.available_at == NOW
    safe = report.to_dict(include_records=True)
    assert safe["full_article_text_stored"] is False
    assert safe["secret_values_disclosed"] is False
    assert "article body" not in json.dumps(safe).lower()


def test_rss_atom_collection_normalizes_official_publication_time() -> None:
    xml = b"""<?xml version='1.0' encoding='UTF-8'?>
    <rss version='2.0'><channel><item>
      <title>Official policy announcement</title>
      <link>https://authority.example/release/1</link>
      <description>Policy authority issued a material announcement.</description>
      <pubDate>Tue, 28 Jul 2026 00:45:00 GMT</pubDate>
    </item></channel></rss>"""
    provider = PublicLiveInformationProvider(
        PublicLiveSourceCatalog("catalog:rss", (_source(parser="rss_atom"),)),
        http_get=lambda *args, **kwargs: FakeResponse({}, content=xml),
        clock=lambda: NOW,
        sleeper=lambda _: None,
    )

    report = provider.collect()

    assert report.live_record_count == 1
    record = report.records[0]
    assert record.published_at == datetime(2026, 7, 28, 0, 45, tzinfo=timezone.utc)
    assert record.available_at == NOW
    assert record.provenance.source_type is InformationSourceType.OFFICIAL


def test_missing_required_configuration_fails_closed_without_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PRIVATE_TEST_KEY", raising=False)
    secret = "never-emit-this-value"
    provider = PublicLiveInformationProvider(
        PublicLiveSourceCatalog(
            "catalog:missing",
            (_source(credentials=("PRIVATE_TEST_KEY",)),),
        ),
        http_get=lambda *args, **kwargs: pytest.fail("network must not be called"),
        clock=lambda: NOW,
    )

    report = provider.collect()
    payload = report.to_dict(include_records=True)

    assert report.sources[0].configured is False
    assert report.sources[0].succeeded is False
    assert "PRIVATE_TEST_KEY" in (report.sources[0].error or "")
    serialized = json.dumps(payload)
    assert secret not in serialized
    assert payload["secret_values_disclosed"] is False


def test_optional_unconfigured_source_does_not_prevent_required_only_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPTIONAL_KEY", raising=False)
    required = _source(required=True)
    optional = PublicLiveSourceDefinition(
        **{
            field: getattr(_source(required=False, credentials=("OPTIONAL_KEY",)), field)
            for field in _source(required=False, credentials=("OPTIONAL_KEY",)).__dataclass_fields__
        }
    )
    payload = {"articles": []}
    provider = PublicLiveInformationProvider(
        PublicLiveSourceCatalog("catalog:required-only", (required, optional)),
        http_get=lambda *args, **kwargs: FakeResponse(payload),
        clock=lambda: NOW,
        sleeper=lambda _: None,
    )

    report = provider.collect(include_optional=False)

    assert len(report.sources) == 1
    assert report.sources[0].source_identifier == required.identifier
    assert report.sources[0].succeeded is True


def test_catalog_rejects_insecure_endpoint() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        PublicLiveSourceDefinition(
            **{
                **{
                    field: getattr(_source(), field)
                    for field in _source().__dataclass_fields__
                },
                "endpoint": "http://example.test/feed",
            }
        )
