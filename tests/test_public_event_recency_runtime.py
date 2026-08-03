from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

import educational_market_briefing_ui as event_ui
import public_event_recency_runtime as recency


def _record(
    *,
    identifier: str,
    published_at: datetime,
    available_at: datetime,
) -> dict[str, object]:
    return {
        "identifier": identifier,
        "canonical_event_identifier": identifier,
        "topic": f"Event {identifier}",
        "summary": f"Summary for {identifier}",
        "event_at": published_at.isoformat(),
        "published_at": published_at.isoformat(),
        "available_at": available_at.isoformat(),
        "impact_channels": ["policy", "liquidity"],
        "tags": [],
        "reliability": 0.95,
        "relevance": 0.95,
        "materiality": 0.9,
        "independence": 0.9,
        "provenance": {
            "provider": "Official source",
            "source_type": "official",
        },
    }


def test_collection_time_does_not_renew_an_old_story() -> None:
    now = datetime(2026, 8, 2, 16, 0, tzinfo=timezone.utc)
    old_story = _record(
        identifier="old",
        published_at=now - timedelta(days=3),
        available_at=now - timedelta(minutes=5),
    )

    recency.install(event_ui)

    assert recency.source_event_time(old_story) == now - timedelta(days=3)
    assert event_ui.build_today_items((old_story,), now=now) == ()


def test_recent_publication_remains_visible() -> None:
    now = datetime(2026, 8, 2, 16, 0, tzinfo=timezone.utc)
    recent_story = _record(
        identifier="recent",
        published_at=now - timedelta(hours=2),
        available_at=now - timedelta(minutes=5),
    )

    recency.install(event_ui)

    items = event_ui.build_today_items((recent_story,), now=now)
    assert [item.title for item in items] == ["Event recent"]
    assert items[0].published_at == now - timedelta(hours=2)


def test_render_background_snapshot_keeps_bounded_source_timed_history(
    monkeypatch,
    tmp_path,
) -> None:
    import render_nonblocking_data

    now = datetime.now(timezone.utc)
    records_path = tmp_path / "public-live-information-records.json"
    records_path.write_text(
        json.dumps(
            {
                "schema_version": "public-live-information-record-set.v1",
                "evaluated_at": now.isoformat(),
                "records": [
                    _record(
                        identifier="old",
                        published_at=now - timedelta(days=3),
                        available_at=now - timedelta(minutes=2),
                    ),
                    _record(
                        identifier="recent",
                        published_at=now - timedelta(hours=2),
                        available_at=now - timedelta(minutes=2),
                    ),
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_RECORDS",
        str(records_path),
    )

    recency.install(event_ui)
    snapshot = render_nonblocking_data._PUBLIC_EVENTS._supplier()

    assert [record["identifier"] for record in snapshot.records] == [
        "recent",
        "old",
    ]
    assert [item.title for item in event_ui.build_today_items(snapshot.records, now=now)] == [
        "Event recent"
    ]


def test_streamlit_reruns_do_not_reset_the_warmed_event_loader(monkeypatch) -> None:
    reset_calls: list[str] = []
    fake_loader = SimpleNamespace(reset=lambda: reset_calls.append("reset"))
    fake_nonblocking = ModuleType("render_nonblocking_data")
    fake_nonblocking._PUBLIC_EVENTS = fake_loader
    fake_event_ui = ModuleType("educational_market_briefing_ui")
    monkeypatch.setitem(sys.modules, "render_nonblocking_data", fake_nonblocking)

    recency.install(fake_event_ui)
    installed_supplier = fake_loader._supplier
    recency.install(fake_event_ui)

    assert reset_calls == ["reset"]
    assert fake_loader._supplier is installed_supplier
    assert fake_event_ui._record_time is recency.source_event_time


def test_both_streamlit_entrypoints_install_the_recency_fix() -> None:
    for path in (Path("app.py"), Path("render_app.py")):
        source = path.read_text(encoding="utf-8")
        assert "import public_event_recency_runtime" in source
        assert "public_event_recency_runtime.install" in source
