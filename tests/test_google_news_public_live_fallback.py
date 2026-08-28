from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import requests

from operations import public_live_requirement_qualification as qualification
from providers import public_live_information as public_live
from providers.public_live_information import PublicLiveSourceCatalog
from providers.public_live_information_extended import ImpactfulPublicLiveInformationProvider
from providers.public_live_source_catalogs import load_operating_public_live_source_catalog


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "config" / "public_live_information_sources.json"
NOW = datetime(2026, 8, 28, 1, 30, tzinfo=timezone.utc)
_REQUIREMENT_GROUP = "gdelt-global-news-discovery"


class FakeResponse:
    def __init__(self, payload: Any = None, *, content: bytes | None = None) -> None:
        self._payload = payload
        self.content = (
            content
            if content is not None
            else json.dumps(payload).encode("utf-8")
        )

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _global_news_members():
    catalog = load_operating_public_live_source_catalog(CATALOG_PATH)
    return tuple(
        source
        for source in catalog.sources
        if source.requirement_group == _REQUIREMENT_GROUP
    )


def test_google_news_is_third_independent_global_news_fallback() -> None:
    members = _global_news_members()

    assert [source.identifier for source in members] == [
        "gdelt-global-news-discovery",
        "gdelt-global-context-discovery",
        "google-news-global-discovery",
    ]
    google = members[2]
    assert google.parser == "rss_atom"
    assert google.endpoint == "https://news.google.com/rss/search"
    assert google.credential_environment_variables == ()
    assert google.independence_group == "google-news-discovery"
    assert google.usage_rights_identifier == (
        "metadata-and-links-only.no-article-body-storage"
    )


def test_google_news_fallback_satisfies_group_after_both_gdelt_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    members = _global_news_members()
    scoped = PublicLiveSourceCatalog("catalog:global-news-fallback", members)
    xml = b"""<?xml version='1.0' encoding='UTF-8'?>
    <rss version='2.0'><channel><item>
      <title>Global markets react to policy shift</title>
      <link>https://news.google.com/rss/articles/example</link>
      <description>Publisher headline metadata</description>
      <pubDate>Fri, 28 Aug 2026 01:20:00 GMT</pubDate>
    </item></channel></rss>"""
    calls: list[str] = []

    def get(endpoint: str, **_kwargs):
        calls.append(endpoint)
        if "gdeltproject.org" in endpoint:
            raise requests.Timeout("simulated GDELT timeout")
        return FakeResponse(content=xml)

    monkeypatch.setattr(
        public_live,
        "collect_finra_fixed_income_context",
        lambda **_kwargs: None,
    )
    provider = ImpactfulPublicLiveInformationProvider(
        scoped,
        timeout=1.0,
        max_attempts=1,
        http_get=get,
        clock=lambda: NOW,
        sleeper=lambda _: None,
    )

    report = provider.collect(include_optional=False)

    assert calls == [
        "https://api.gdeltproject.org/api/v2/doc/doc",
        "https://api.gdeltproject.org/api/v2/context/context",
        "https://news.google.com/rss/search",
    ]
    assert report.required_sources_ready is True
    assert [item.succeeded for item in report.sources[:3]] == [False, False, True]
    assert report.sources[2].source_identifier == "google-news-global-discovery"
    assert report.live_record_count == 1
    record = report.records[0]
    assert record.topic == "Global markets react to policy shift"
    assert record.provenance.usage_rights_identifier == (
        "metadata-and-links-only.no-article-body-storage"
    )


def test_three_provider_policy_stays_inside_existing_requirement_budget() -> None:
    policy = qualification._gdelt_provider_request_policy(
        requirement_group=_REQUIREMENT_GROUP,
        provider_count=3,
        values={},
    )

    assert policy is not None
    request_timeout, attempts = policy
    assert attempts == 2
    assert 9.0 < request_timeout < 10.0
    assert request_timeout * 3 * attempts < 60.0
    assert qualification._requirement_timeout_seconds({}) == 75.0
