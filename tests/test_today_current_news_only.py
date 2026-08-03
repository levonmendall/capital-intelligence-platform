from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import educational_market_briefing_ui as event_ui
import today_event_alignment_runtime as alignment
from data.decision_information import InformationSourceType, PortfolioImpactChannel
from providers.public_live_information import (
    PublicLiveInformationProvider,
    PublicLiveSourceCatalog,
    PublicLiveSourceDefinition,
)
from providers.public_live_information_runtime import (
    GovernedPublicLiveInformationProvider,
)
from public_live_record_history import merge_public_event_records


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.content = json.dumps(payload).encode("utf-8")

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _source(parser: str, *, name: str = "Test source") -> PublicLiveSourceDefinition:
    return PublicLiveSourceDefinition(
        identifier=f"source:{parser}",
        source_name=name,
        parser=parser,
        endpoint="https://example.test/data",
        source_type=InformationSourceType.OFFICIAL,
        independence_group=f"group:{parser}",
        domains=("government_policy_regulation",),
        impact_channels=(PortfolioImpactChannel.GROWTH,),
        enabled=True,
        required=True,
        credential_environment_variables=(),
        user_agent_environment_variable=None,
        parameters={},
        headers={},
        maximum_records=20,
        reliability=0.95,
        relevance=0.8,
        materiality=0.7,
        license_identifier="public:test",
        usage_rights_identifier="internal-analysis",
        limitations=("required",),
    )


def _record(
    identifier: str,
    *,
    now: datetime,
    provider: str,
    topic: str,
    published_at: datetime,
    event_at: datetime | None = None,
    tags: tuple[str, ...] = (),
    channels: tuple[str, ...] = (),
    source_type: str = "official",
) -> dict[str, Any]:
    return {
        "identifier": identifier,
        "canonical_event_identifier": f"event:{identifier}",
        "topic": topic,
        "summary": topic,
        "event_at": (event_at or published_at).isoformat(),
        "published_at": published_at.isoformat(),
        "available_at": now.isoformat(),
        "impact_channels": list(channels),
        "tags": list(tags),
        "reliability": 0.9,
        "relevance": 0.8,
        "materiality": 0.7,
        "independence": 1.0,
        "provenance": {
            "provider": provider,
            "source_type": source_type,
            "source_identifier": identifier,
        },
    }


def test_today_excludes_old_imf_and_world_bank_rows_retrieved_now() -> None:
    now = datetime(2026, 8, 3, 19, 0, tzinfo=timezone.utc)
    records = (
        _record(
            "imf:arg:2007",
            now=now,
            provider="IMF DataMapper real GDP growth",
            topic="IMF NGDP_RPCH: ARG",
            published_at=now - timedelta(minutes=3),
            event_at=datetime(2007, 1, 1, tzinfo=timezone.utc),
            tags=("imf-datamapper",),
            channels=("growth",),
        ),
        _record(
            "world-bank:cri:2024",
            now=now,
            provider="World Bank global growth indicators",
            topic="World Bank indicator GDP growth (annual %)",
            published_at=now - timedelta(minutes=3),
            event_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            channels=("growth",),
        ),
        _record(
            "news:current",
            now=now,
            provider="GDELT DOC 2.0 news discovery metadata",
            topic="Oil falls after a verified ceasefire announcement",
            published_at=now - timedelta(minutes=8),
            tags=("current_events_news", "metadata-only"),
            source_type="alternative",
        ),
    )

    items = alignment.build_today_items(records, now=now)

    assert [item.title for item in items] == [
        "Oil falls after a verified ceasefire announcement"
    ]


def test_collection_time_does_not_renew_an_old_news_item() -> None:
    now = datetime(2026, 8, 3, 19, 0, tzinfo=timezone.utc)
    old = _record(
        "news:old",
        now=now,
        provider="GDELT DOC 2.0 news discovery metadata",
        topic="Old market headline",
        published_at=now - timedelta(days=3),
        tags=("current_events_news",),
        source_type="alternative",
    )

    assert event_ui._record_time(old) == now - timedelta(days=3)
    assert alignment.build_today_items((old,), now=now) == ()


def test_current_source_qualified_news_without_channels_remains_displayable() -> None:
    now = datetime(2026, 8, 3, 19, 0, tzinfo=timezone.utc)
    current = _record(
        "news:channel-missing",
        now=now,
        provider="GDELT DOC 2.0 news discovery metadata",
        topic="Current verified market development",
        published_at=now - timedelta(minutes=15),
        tags=("current_events_news",),
        source_type="alternative",
    )

    items = alignment.build_today_items((current,), now=now)

    assert [item.title for item in items] == ["Current verified market development"]
    assert "precise portfolio transmission" in items[0].why_it_matters


def test_corrected_current_record_evicts_cached_false_fresh_version(tmp_path: Path) -> None:
    now = datetime(2026, 8, 3, 19, 0, tzinfo=timezone.utc)
    path = tmp_path / "records.json"
    cached = _record(
        "imf:arg:2007",
        now=now,
        provider="IMF DataMapper real GDP growth",
        topic="IMF NGDP_RPCH: ARG",
        published_at=now - timedelta(minutes=5),
        event_at=datetime(2007, 1, 1, tzinfo=timezone.utc),
        tags=("imf-datamapper",),
        channels=("growth",),
    )
    path.write_text(json.dumps({"records": [cached]}), encoding="utf-8")
    corrected = dict(cached)
    corrected["published_at"] = datetime(2007, 1, 1, tzinfo=timezone.utc).isoformat()
    corrected["tags"] = [
        "data-observation",
        "historical-economic-observation",
        "imf-datamapper",
    ]

    merged = merge_public_event_records(path, (corrected,), evaluated_at=now)

    assert merged == []


def test_world_bank_observation_uses_observation_year_not_retrieval_time() -> None:
    now = datetime(2026, 8, 3, 19, 0, tzinfo=timezone.utc)
    payload = [
        {"page": 1},
        [
            {
                "country": {"value": "Costa Rica"},
                "countryiso3code": "CRI",
                "indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"},
                "date": "2024",
                "value": 4.08,
            }
        ],
    ]
    provider = PublicLiveInformationProvider(
        PublicLiveSourceCatalog("catalog:test", (_source("world_bank"),)),
        http_get=lambda *args, **kwargs: FakeResponse(payload),
        clock=lambda: now,
        sleeper=lambda _: None,
    )

    record = provider.collect().records[0]

    assert record.published_at == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert "data-observation" in record.tags
    assert "world-bank-indicator" in record.tags


def test_imf_observation_uses_observation_year_not_retrieval_time() -> None:
    now = datetime(2026, 8, 3, 19, 0, tzinfo=timezone.utc)
    payload = {"values": {"NGDP_RPCH": {"ARG": {"2007": 9.0}}}}
    provider = GovernedPublicLiveInformationProvider(
        PublicLiveSourceCatalog("catalog:test", (_source("imf_datamapper"),)),
        http_get=lambda *args, **kwargs: FakeResponse(payload),
        clock=lambda: now,
        sleeper=lambda _: None,
    )

    record = provider.collect().records[0]

    assert record.published_at == datetime(2007, 1, 1, tzinfo=timezone.utc)
    assert "data-observation" in record.tags
    assert "historical-economic-observation" in record.tags
