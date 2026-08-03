"""Materialize the Today current-news versus economic-data separation.

This one-use transformation fixes record-time semantics and keeps raw macro/market
observations in Environment rather than presenting them as today's news. It does not
change CIO, specialist, evidence, construction, sizing, or execution authority.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{relative}: expected exactly one replacement target, found {count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def write_new(relative: str, content: str) -> None:
    path = ROOT / relative
    if path.exists():
        raise RuntimeError(f"new file already exists: {relative}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    replace_once(
        "providers/public_live_information.py",
        '''    raw = str(value).strip()
    if not raw:
        return fallback
    compact_formats = ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y-%m-%d")
''',
        '''    raw = str(value).strip()
    if not raw:
        return fallback
    if len(raw) == 4 and raw.isdigit():
        raw = f"{raw}-01-01"
    compact_formats = ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y-%m-%d")
''',
    )

    replace_once(
        "providers/public_live_information.py",
        '''                tags=(str(item.get("commodity_name", "commodity")),),
''',
        '''                tags=(
                    "data-observation",
                    "cftc-positioning-observation",
                    str(item.get("commodity_name", "commodity")),
                ),
''',
    )

    replace_once(
        "providers/public_live_information.py",
        '''                source_identifier=f"{source.identifier}:{item.get('record_date', _hash_payload(item))}",
                geographies=("United States",),
''',
        '''                source_identifier=f"{source.identifier}:{item.get('record_date', _hash_payload(item))}",
                geographies=("United States",),
                tags=("data-observation", "treasury-fiscal-data"),
''',
    )

    replace_once(
        "providers/public_live_information.py",
        '''                event_at=item.get("date"),
                published_at=retrieved_at,
                source_identifier=f"{item.get('countryiso3code')}:{item.get('indicator', {}).get('id')}:{item.get('date')}",
                geographies=(str(item.get("country", {}).get("value", "global")),),
''',
        '''                event_at=item.get("date"),
                published_at=item.get("date"),
                source_identifier=f"{item.get('countryiso3code')}:{item.get('indicator', {}).get('id')}:{item.get('date')}",
                geographies=(str(item.get("country", {}).get("value", "global")),),
                tags=(
                    "data-observation",
                    "historical-economic-observation",
                    "world-bank-indicator",
                ),
''',
    )

    replace_once(
        "providers/public_live_information.py",
        '''                event_at=item.get("period"),
                published_at=retrieved_at,
                source_identifier=f"{item.get('series')}:{item.get('period')}",
                geographies=("United States",),
''',
        '''                event_at=item.get("period"),
                published_at=item.get("period"),
                source_identifier=f"{item.get('series')}:{item.get('period')}",
                geographies=("United States",),
                tags=("data-observation", "eia-series-observation"),
''',
    )

    replace_once(
        "providers/public_live_information_runtime.py",
        '''                    event_at=observed,
                    published_at=retrieved_at,
                    source_identifier=source_id,
''',
        '''                    event_at=observed,
                    published_at=observed,
                    source_identifier=source_id,
''',
    )

    replace_once(
        "providers/public_live_information_runtime.py",
        '''                            event_at=str(year),
                            published_at=retrieved_at,
                            source_identifier=f"{indicator}:{country}:{year}",
                            entities=("International Monetary Fund",),
                            geographies=(str(country),),
                            tags=(str(indicator), "imf-datamapper"),
''',
        '''                            event_at=str(year),
                            published_at=str(year),
                            source_identifier=f"{indicator}:{country}:{year}",
                            entities=("International Monetary Fund",),
                            geographies=(str(country),),
                            tags=(
                                "data-observation",
                                "historical-economic-observation",
                                str(indicator),
                                "imf-datamapper",
                            ),
''',
    )

    replace_once(
        "educational_market_briefing_ui.py",
        '''_EXCLUDED_TAGS = frozenset({"sanctions-list", "fixture"})
''',
        '''_EXCLUDED_TAGS = frozenset({"sanctions-list", "fixture"})
_NON_NEWS_DATASET_TAGS = frozenset(
    {
        "data-observation",
        "historical-economic-observation",
        "world-bank-indicator",
        "imf-datamapper",
        "treasury-fiscal-data",
        "eia-series-observation",
        "cftc-positioning-observation",
    }
)
_NON_NEWS_DATASET_PROVIDERS = frozenset(
    {
        "imf datamapper real gdp growth",
        "world bank global growth indicators",
        "u.s. treasury fiscal data debt to the penny",
        "u.s. energy information administration spot petroleum data",
        "cftc disaggregated commitments of traders",
    }
)
''',
    )

    replace_once(
        "educational_market_briefing_ui.py",
        '''def _provenance(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = record.get("provenance")
    return value if isinstance(value, Mapping) else {}


def _record_time(record: Mapping[str, Any]) -> datetime | None:
    for field_name in ("available_at", "published_at", "event_at"):
''',
        '''def _provenance(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = record.get("provenance")
    return value if isinstance(value, Mapping) else {}


def _is_non_news_dataset_observation(record: Mapping[str, Any]) -> bool:
    provider = _clean_text(_provenance(record).get("provider")).lower()
    return (
        provider in _NON_NEWS_DATASET_PROVIDERS
        or bool(_NON_NEWS_DATASET_TAGS & _tags(record))
    )


def _record_time(record: Mapping[str, Any]) -> datetime | None:
    # Publication/event time determines whether information is current. Collection
    # time is only a last-resort fallback and must never renew an old observation.
    for field_name in ("published_at", "event_at", "available_at"):
''',
    )

    replace_once(
        "educational_market_briefing_ui.py",
        '''    if _EXCLUDED_TAGS & _tags(record):
        return False
    if topic.lower().startswith("ofac sanctions listing:"):
        return False

    channels = set(_channels(record))
''',
        '''    if _EXCLUDED_TAGS & _tags(record):
        return False
    if topic.lower().startswith("ofac sanctions listing:"):
        return False
    if (
        allowed_channels == _MARKET_CHANNELS
        and _is_non_news_dataset_observation(record)
    ):
        return False

    channels = set(_channels(record))
''',
    )

    replace_once(
        "today_event_alignment_runtime.py",
        '''        if {"fixture", "sanctions-list"} & _tag_set(raw):
            continue
        interpretation = _interpret(raw)
''',
        '''        if {"fixture", "sanctions-list"} & _tag_set(raw):
            continue
        if event_ui._is_non_news_dataset_observation(raw):
            continue
        interpretation = _interpret(raw)
''',
    )

    replace_once(
        "public_live_record_history.py",
        '''    # Current normalized metadata wins when the same event appears in both sets.
    chosen: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for is_current, records in ((True, current), (False, previous)):
        for record in records:
            observed_at = _record_time(record, fallback=now if is_current else None)
            if observed_at is None or observed_at > now or observed_at < cutoff:
                continue
            key = _record_key(record)
            if key in chosen:
                continue
            chosen[key] = (observed_at, dict(record))
''',
        '''    # Current normalized metadata wins when the same event appears in both sets.
    # A current corrected record also suppresses an older cached version even when
    # the corrected timestamp proves the event is outside the rolling window.
    current_keys = {_record_key(record) for record in current}
    chosen: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for is_current, records in ((True, current), (False, previous)):
        for record in records:
            key = _record_key(record)
            if not is_current and key in current_keys:
                continue
            observed_at = _record_time(record, fallback=now if is_current else None)
            if observed_at is None or observed_at > now or observed_at < cutoff:
                continue
            if key in chosen:
                continue
            chosen[key] = (observed_at, dict(record))
''',
    )

    write_new(
        "tests/test_today_current_news_only.py",
        '''from __future__ import annotations

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
''',
    )

    replace_once(
        "docs/TODAY_NEWS_COVERAGE_RESILIENCE.md",
        '''## Display admission

The Today educational surface still rejects stale, future-dated, fixture, raw OFAC
listing, and routine administrative noise. It admits a current source-qualified headline
when a provider omitted impact-channel metadata or when the exact investment
transmission is still unresolved. In the latter case it reports the development,
identifies what remains unknown, and avoids inventing a directional market conclusion.
The Environment surface remains restricted to economic impact channels.
''',
        '''## Display admission

The Today educational surface still rejects stale, future-dated, fixture, raw OFAC
listing, and routine administrative noise. It admits a current source-qualified headline
when a provider omitted impact-channel metadata or when the exact investment
transmission is still unresolved. In the latter case it reports the development,
identifies what remains unknown, and avoids inventing a directional market conclusion.

Raw IMF, World Bank, Treasury, CFTC, and EIA table observations are economic evidence,
not news headlines. They remain available to the Environment and research layers, but
they cannot fill Today merely because the application retrieved them recently. Today
uses source publication time first, event time second, and collection time only when a
source provides neither. A corrected current record also evicts an older cached version
that had been mislabeled as fresh.
''',
    )


if __name__ == "__main__":
    main()
