from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import educational_market_briefing_ui as event_ui
import public_event_recency_runtime
import today_event_alignment_runtime
import today_story_retention_runtime as retention


def _record(
    *,
    identifier: str,
    published_at: datetime,
    available_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "identifier": identifier,
        "canonical_event_identifier": identifier,
        "topic": f"Event {identifier}",
        "summary": f"Summary for {identifier}",
        "event_at": published_at.isoformat(),
        "published_at": published_at.isoformat(),
        "available_at": (available_at or published_at).isoformat(),
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


def test_old_story_is_retained_without_renewing_its_publication_time() -> None:
    now = datetime(2026, 8, 3, 4, 0, tzinfo=timezone.utc)
    old_story = _record(
        identifier="prior",
        published_at=now - timedelta(days=3),
        available_at=now - timedelta(minutes=5),
    )
    public_event_recency_runtime.install(event_ui)

    assert event_ui.build_today_items((old_story,), now=now) == ()

    retained = retention._build_retained_items(
        event_ui.build_today_items,
        event_ui,
        (old_story,),
        now=now,
        limit=3,
    )

    assert [item.title for item in retained] == ["Event prior"]
    assert retained[0].published_at == now - timedelta(days=3)


def test_aligned_federal_reserve_story_is_retained() -> None:
    now = datetime(2026, 8, 3, 4, 0, tzinfo=timezone.utc)
    published_at = now - timedelta(days=3)
    story = _record(
        identifier="retained-fed-story",
        published_at=published_at,
        available_at=now - timedelta(minutes=5),
    )
    story["topic"] = "Federal Reserve policy decision changes the rate outlook"
    story["summary"] = (
        "The Federal Reserve held its policy rate steady and said future decisions "
        "depend on inflation and labor-market evidence."
    )
    story["provenance"] = {
        "provider": "Federal Reserve",
        "source_type": "official",
    }
    public_event_recency_runtime.install(event_ui)

    retained = retention._build_retained_items(
        today_event_alignment_runtime.build_today_items,
        event_ui,
        (story,),
        now=now,
        limit=3,
    )

    assert [item.title for item in retained] == [
        "Federal Reserve policy decision changes the rate outlook"
    ]
    assert retained[0].published_at == published_at


def test_current_story_is_preferred_over_retained_history() -> None:
    now = datetime(2026, 8, 3, 4, 0, tzinfo=timezone.utc)
    records = (
        _record(identifier="current", published_at=now - timedelta(hours=2)),
        _record(identifier="prior", published_at=now - timedelta(days=2)),
    )
    public_event_recency_runtime.install(event_ui)

    selected = retention._build_retained_items(
        event_ui.build_today_items,
        event_ui,
        records,
        now=now,
        limit=3,
    )

    assert [item.title for item in selected] == ["Event current"]


def test_empty_refresh_reuses_persistent_story_cache(monkeypatch, tmp_path) -> None:
    now = datetime.now(timezone.utc)
    cache_path = tmp_path / "today-story-retention.json"
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_TODAY_STORY_RETENTION",
        str(cache_path),
    )
    public_event_recency_runtime.install(event_ui)
    snapshots = {
        "value": event_ui.PublicEventSnapshot(
            records=(
                _record(
                    identifier="cached",
                    published_at=now - timedelta(hours=2),
                ),
            ),
            evaluated_at=now,
            state="available",
            detail="Current event metadata is available.",
        )
    }
    loader = retention._retaining_loader(
        lambda: snapshots["value"],
        event_ui.build_today_items,
        event_ui,
    )

    first = loader()
    assert [record["identifier"] for record in first.records] == ["cached"]
    assert cache_path.exists()

    snapshots["value"] = event_ui.PublicEventSnapshot(
        records=(),
        evaluated_at=now + timedelta(hours=26),
        state="available",
        detail="No new records were collected.",
    )
    second = loader()
    selected = retention._build_retained_items(
        event_ui.build_today_items,
        event_ui,
        second.records,
        now=now + timedelta(hours=26),
        limit=3,
    )

    assert [record["identifier"] for record in second.records] == ["cached"]
    assert [item.title for item in selected] == ["Event cached"]
    assert "No new source-qualified development" in second.detail
    assert "original publication times are preserved" in second.detail

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "today-story-retention.v1"
    assert payload["records"][0]["identifier"] == "cached"


def test_entrypoints_install_retention_after_final_today_renderer() -> None:
    for path in (Path("app.py"), Path("render_app.py")):
        source = path.read_text(encoding="utf-8")
        assert "import today_story_retention_runtime" in source
        final_renderer = source.index("environment_story_placement_refinement.install(app_impl)")
        retention_install = source.index("today_story_retention_runtime.install(")
        assert final_renderer < retention_install


def test_retained_today_copy_is_truthful_about_story_age() -> None:
    source = Path("today_story_retention_runtime.py").read_text(encoding="utf-8")

    assert "Today // latest prior developments" in source
    assert "No new source-qualified development cleared the current 24-hour controls" in source
    assert "original publication timestamps" in source
    assert "No new qualifying stories" in source
