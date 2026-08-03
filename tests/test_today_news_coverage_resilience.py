from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import educational_market_briefing_ui as event_ui
import today_story_retention_runtime as retention
from public_live_record_history import merge_public_event_records


def _record(identifier: str, published_at: datetime, *, channels=()):
    timestamp = published_at.isoformat()
    return {
        "identifier": identifier,
        "canonical_event_identifier": identifier,
        "topic": f"Headline {identifier}",
        "summary": "",
        "event_at": timestamp,
        "published_at": timestamp,
        "available_at": timestamp,
        "impact_channels": list(channels),
        "tags": [],
        "reliability": 0.55,
        "relevance": 0.7,
        "materiality": 0.45,
        "independence": 1.0,
        "provenance": {
            "provider": "Broad news discovery",
            "source_type": "alternative",
            "source_identifier": identifier,
        },
    }


def test_rolling_history_survives_a_thin_collection_without_renewing_age(tmp_path) -> None:
    now = datetime(2026, 8, 3, 18, 0, tzinfo=timezone.utc)
    records_path = tmp_path / "records.json"
    records_path.write_text(
        json.dumps(
            {
                "records": [
                    _record("prior", now - timedelta(hours=8)),
                    _record("stale", now - timedelta(days=3)),
                ]
            }
        ),
        encoding="utf-8",
    )

    merged = merge_public_event_records(
        records_path,
        (_record("current", now - timedelta(minutes=10)),),
        evaluated_at=now,
    )

    assert [item["identifier"] for item in merged] == ["current", "prior"]
    assert merged[1]["published_at"] == (now - timedelta(hours=8)).isoformat()


def test_today_accepts_current_source_qualified_news_without_channel_tags() -> None:
    now = datetime(2026, 8, 3, 18, 0, tzinfo=timezone.utc)

    items = event_ui.build_today_items((_record("broad", now - timedelta(hours=1)),), now=now)

    assert [item.title for item in items] == ["Headline broad"]
    assert items[0].summary == "A current public source reported: Headline broad."


def test_empty_record_file_is_coverage_degradation_not_quiet_day(tmp_path) -> None:
    now = datetime(2026, 8, 3, 18, 0, tzinfo=timezone.utc)
    path = tmp_path / "records.json"
    path.write_text(
        json.dumps(
            {
                "evaluated_at": now.isoformat(),
                "records": [],
                "coverage": {
                    "required_sources_ready": False,
                    "failed_source_count": 2,
                },
            }
        ),
        encoding="utf-8",
    )

    snapshot = event_ui._read_public_event_file.__wrapped__(str(path), path.stat().st_mtime_ns)

    assert snapshot.state == "degraded"
    assert "not evidence that the news cycle was quiet" in snapshot.detail


def test_stale_retention_does_not_relabel_old_news_as_current() -> None:
    now = datetime(2026, 8, 3, 18, 0, tzinfo=timezone.utc)
    stale = _record("stale", now - timedelta(days=3), channels=("policy",))

    retained = retention._build_retained_items(
        event_ui.build_today_items,
        event_ui,
        (stale,),
        now=now,
        limit=3,
    )

    assert retained == ()


def test_deployment_and_discovery_windows_support_continuous_today_coverage() -> None:
    catalog = json.loads(Path("config/public_live_information_sources.json").read_text())
    source = next(
        item for item in catalog["sources"]
        if item["identifier"] == "gdelt-global-news-discovery"
    )
    render = Path("render.yaml").read_text(encoding="utf-8")
    retention_source = Path("today_story_retention_runtime.py").read_text(encoding="utf-8")

    assert source["parameters"]["timespan"] == "24h"
    assert "stocks OR bonds OR oil" in source["parameters"]["query"]
    assert "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS" in render
    assert 'value: "900"' in render
    assert "No new story earned investor attention" not in retention_source
    assert "Current headline coverage is incomplete" in retention_source
