from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import run_public_headline_collector as collector
from run_render_service import managed_processes


class FakeResponse:
    def __init__(self, *, content: bytes = b"", payload=None, status_code: int = 200):
        self.content = content
        self._payload = payload
        self.status_code = status_code
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_rss_headline_metadata_is_normalized_without_article_body() -> None:
    now = datetime(2026, 8, 4, 3, 0, tzinfo=timezone.utc)
    source = collector.HeadlineSource(
        identifier="test-rss",
        provider="Test Business News",
        endpoint="https://example.test/rss",
        parser="rss",
        source_type="journalism",
        independence_group="test-newsroom",
        reliability=0.8,
    )
    response = FakeResponse(
        content=(
            b"<rss><channel><item><title>Stocks rise as inflation cools</title>"
            b"<link>https://example.test/story</link>"
            b"<description>Markets advanced after a softer inflation report.</description>"
            b"<pubDate>Tue, 04 Aug 2026 02:45:00 GMT</pubDate>"
            b"</item></channel></rss>"
        )
    )

    result = collector.collect_headlines(
        now=now,
        sources=(source,),
        http_get=lambda *args, **kwargs: response,
        sleeper=lambda _seconds: None,
    )

    assert len(result.records) == 1
    record = result.records[0]
    assert record["topic"] == "Stocks rise as inflation cools"
    assert "broad-news" in record["tags"]
    assert record["provenance"]["provider"] == "Test Business News"
    assert record["provenance"]["usage_rights_identifier"] == (
        "headline-metadata-and-source-link-only"
    )
    assert result.to_dict()["full_article_text_stored"] is False


def test_builtin_headline_coverage_has_independent_no_key_sources() -> None:
    no_key_sources = tuple(
        source
        for source in collector.HEADLINE_SOURCES
        if source.key_environment_variable is None
    )
    providers = {source.provider for source in no_key_sources}
    independence_groups = {source.independence_group for source in no_key_sources}

    assert len(no_key_sources) >= 6
    assert {"BBC Business", "NPR Business", "The Guardian Business", "CoinDesk"} <= providers
    assert len(independence_groups) >= 4
    assert all(source.identifier != "gdelt-global-news-discovery" for source in no_key_sources)


def test_unconfigured_optional_provider_is_skipped_without_becoming_failure(monkeypatch) -> None:
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    source = next(
        item for item in collector.HEADLINE_SOURCES
        if item.identifier == "finnhub-general-news"
    )

    result = collector.collect_headlines(
        now=datetime(2026, 8, 4, 3, 0, tzinfo=timezone.utc),
        sources=(source,),
        http_get=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("not called")),
        sleeper=lambda _seconds: None,
    )

    assert result.configured_source_count == 0
    assert result.failed_source_count == 0
    assert result.sources[0].configured is False


def test_persistence_keeps_recent_verified_headline_when_pass_is_empty(tmp_path, monkeypatch) -> None:
    now = datetime(2026, 8, 4, 3, 0, tzinfo=timezone.utc)
    records_path = tmp_path / "public-live-information-records.json"
    lock_path = tmp_path / "public-live-information-runtime.lock"
    prior = {
        "identifier": "headline:prior",
        "canonical_event_identifier": "event:headline:prior",
        "topic": "Verified prior market headline",
        "summary": "Verified prior market headline",
        "event_at": (now - timedelta(hours=2)).isoformat(),
        "published_at": (now - timedelta(hours=2)).isoformat(),
        "available_at": (now - timedelta(hours=2)).isoformat(),
        "tags": ["current_events_news", "broad-news"],
        "provenance": {"provider": "Prior Provider", "source_type": "journalism"},
    }
    records_path.write_text(json.dumps({"records": [prior]}), encoding="utf-8")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PUBLIC_LIVE_RECORDS", str(records_path))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_LOCK", str(lock_path))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PUBLIC_HEADLINE_REPORT", str(tmp_path / "report.json"))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PUBLIC_HEADLINE_STATE", str(tmp_path / "state.json"))

    result = collector.HeadlineCollectionResult(
        evaluated_at=now,
        records=(),
        sources=(
            collector.HeadlineSourceStatus(
                identifier="temporarily-down",
                provider="Temporary Source",
                configured=True,
                succeeded=False,
                record_count=0,
                error="timeout",
            ),
        ),
    )

    state = collector.persist_headline_collection(result)
    persisted = json.loads(records_path.read_text(encoding="utf-8"))

    assert state["state"] == "degraded"
    assert [item["topic"] for item in persisted["records"]] == [
        "Verified prior market headline"
    ]
    assert persisted["coverage"]["broad_news_ready"] is True


def test_render_supervisor_runs_noncritical_headline_collector() -> None:
    processes = {item.name: item for item in managed_processes(port=10000, python_executable="python")}

    headline = processes["public-headline-collector"]
    assert headline.command == ("python", "run_public_headline_collector.py", "--loop")
    assert headline.critical is False
    assert headline.restart_delay_seconds == 60
