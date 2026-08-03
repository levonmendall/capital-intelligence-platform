"""Materialize resilient, less-restrictive Today news coverage.

This is a one-use, strict source transformation. It broadens only the educational
Today display and collection continuity. It does not change CIO, specialist,
construction, evidence-certification, or execution thresholds.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{relative}: expected one replacement target, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def write_new(relative: str, content: str) -> None:
    path = ROOT / relative
    if path.exists():
        raise RuntimeError(f"new file already exists: {relative}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def update_source_catalog() -> None:
    path = ROOT / "config/public_live_information_sources.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    matches = [
        item
        for item in payload.get("sources", [])
        if item.get("identifier") == "gdelt-global-news-discovery"
    ]
    if len(matches) != 1:
        raise RuntimeError("GDELT source definition is not unique")
    source = matches[0]
    parameters = source.setdefault("parameters", {})
    if parameters.get("timespan") != "1h":
        raise RuntimeError("GDELT source window changed before materialization")
    parameters["timespan"] = "24h"
    parameters["query"] = (
        "(economy OR markets OR stocks OR bonds OR oil OR inflation OR central bank "
        "OR earnings OR commodities OR sanctions OR conflict OR ceasefire OR trade "
        "OR cyber OR weather)"
    )
    parameters["maxrecords"] = 250
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    update_source_catalog()

    replace_once(
        "render.yaml",
        '''      - key: CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS
        value: "1800"
''',
        '''      - key: CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS
        value: "900"
''',
    )

    write_new(
        "public_live_record_history.py",
        '''"""Bounded rolling history for investor-facing public-event metadata.

Every collection pass may return a partial source window or experience one provider
outage. This module merges the new normalized records with recent prior records so a
successful 24-hour news set is not erased by one thin or degraded pass. Source
publication time remains authoritative and stale records are never renewed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


_HISTORY_WINDOW = timedelta(hours=30)
_MAX_RECORDS = 2000


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("rolling public-event history requires an aware timestamp")
    return value.astimezone(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _record_time(record: Mapping[str, Any], *, fallback: datetime | None) -> datetime | None:
    for field_name in ("published_at", "event_at", "available_at"):
        parsed = _parse_time(record.get(field_name))
        if parsed is not None:
            return parsed
    return fallback


def _record_key(record: Mapping[str, Any]) -> str:
    direct = str(
        record.get("canonical_event_identifier")
        or record.get("identifier")
        or ""
    ).strip().casefold()
    if direct:
        return direct
    provenance = record.get("provenance")
    source_identifier = (
        str(provenance.get("source_identifier", "")).strip().casefold()
        if isinstance(provenance, Mapping)
        else ""
    )
    material = "|".join(
        (
            source_identifier,
            str(record.get("topic", "")).strip().casefold(),
            str(record.get("published_at", "")).strip(),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _existing_records(path: Path) -> tuple[Mapping[str, Any], ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, Mapping):
        return ()
    records = payload.get("records", [])
    if not isinstance(records, list):
        return ()
    return tuple(item for item in records if isinstance(item, Mapping))


def merge_public_event_records(
    path: str | Path,
    current_records: Iterable[Mapping[str, Any]],
    *,
    evaluated_at: datetime,
) -> list[dict[str, Any]]:
    """Return current plus recent prior records, deduplicated by event identity."""

    now = _aware(evaluated_at)
    cutoff = now - _HISTORY_WINDOW
    current = tuple(dict(item) for item in current_records if isinstance(item, Mapping))
    previous = _existing_records(Path(path))

    # Current normalized metadata wins when the same event appears in both sets.
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

    ordered = sorted(
        chosen.values(),
        key=lambda item: (item[0], _record_key(item[1])),
        reverse=True,
    )
    return [record for _observed_at, record in ordered[:_MAX_RECORDS]]


__all__ = ["merge_public_event_records"]
''',
    )

    replace_once(
        "public_live_collection_runtime.py",
        '''from providers.public_live_information_extended import (
    ImpactfulPublicLiveInformationProvider,
)
''',
        '''from providers.public_live_information_extended import (
    ImpactfulPublicLiveInformationProvider,
)
from public_live_record_history import merge_public_event_records
''',
    )

    replace_once(
        "public_live_collection_runtime.py",
        '''            report = factory(catalog).collect(include_optional=True)
            report_payload = {
                **report.to_dict(include_records=False),
                "decision_evidence_authority": False,
            }
            records_payload = {
                "schema_version": "public-live-information-record-set.v1",
                "catalog_identifier": report.catalog_identifier,
                "evaluated_at": report.evaluated_at.isoformat(),
                "records": [item.to_dict() for item in report.records],
                "decision_evidence_authority": False,
                "full_article_text_stored": False,
                "secret_values_disclosed": False,
                "real_money_authorized": False,
            }
            _write_json(report_path, report_payload)
            _write_json(records_path, records_payload)

            failed_source_count = sum(
                1 for item in report.sources if not item.succeeded
            )
''',
        '''            report = factory(catalog).collect(include_optional=True)
            failed_source_count = sum(
                1 for item in report.sources if not item.succeeded
            )
            successful_source_count = sum(
                1 for item in report.sources if item.succeeded
            )
            current_records = [item.to_dict() for item in report.records]
            rolling_records = merge_public_event_records(
                records_path,
                current_records,
                evaluated_at=report.evaluated_at,
            )
            report_payload = {
                **report.to_dict(include_records=False),
                "decision_evidence_authority": False,
            }
            records_payload = {
                "schema_version": "public-live-information-record-set.v2",
                "catalog_identifier": report.catalog_identifier,
                "evaluated_at": report.evaluated_at.isoformat(),
                "records": rolling_records,
                "coverage": {
                    "required_sources_ready": bool(report.required_sources_ready),
                    "successful_source_count": successful_source_count,
                    "source_count": len(report.sources),
                    "failed_source_count": failed_source_count,
                    "current_record_count": len(current_records),
                    "rolling_record_count": len(rolling_records),
                },
                "decision_evidence_authority": False,
                "full_article_text_stored": False,
                "secret_values_disclosed": False,
                "real_money_authorized": False,
            }
            _write_json(report_path, report_payload)
            _write_json(records_path, records_payload)

''',
    )

    replace_once(
        "educational_market_briefing_ui.py",
        '''class PublicEventSnapshot:
    records: tuple[Mapping[str, Any], ...]
    evaluated_at: datetime | None
    state: str
    detail: str
''',
        '''class PublicEventSnapshot:
    records: tuple[Mapping[str, Any], ...]
    evaluated_at: datetime | None
    state: str
    detail: str
    coverage: Mapping[str, Any] | None = None
''',
    )

    replace_once(
        "educational_market_briefing_ui.py",
        '''def _displayable(
    record: Mapping[str, Any],
    *,
    now: datetime,
    allowed_channels: frozenset[str],
) -> bool:
    topic = _clean_text(record.get("topic"))
    summary = _clean_text(record.get("summary"))
    available_at = _record_time(record)
    if not topic or not summary or available_at is None:
        return False
    if available_at > now or now - available_at > _RECENT_WINDOW:
        return False
    if _EXCLUDED_TAGS & _tags(record):
        return False
    if topic.lower().startswith("ofac sanctions listing:"):
        return False
    return bool(set(_channels(record)) & allowed_channels)
''',
        '''def _displayable(
    record: Mapping[str, Any],
    *,
    now: datetime,
    allowed_channels: frozenset[str],
) -> bool:
    topic = _clean_text(record.get("topic"))
    available_at = _record_time(record)
    if not topic or available_at is None:
        return False
    if available_at > now or now - available_at > _RECENT_WINDOW:
        return False
    if _EXCLUDED_TAGS & _tags(record):
        return False
    if topic.lower().startswith("ofac sanctions listing:"):
        return False

    channels = set(_channels(record))
    if channels & allowed_channels:
        return True

    # Today is an educational awareness surface, not the CIO evidence gate. A
    # current, source-qualified headline must not disappear merely because a
    # provider omitted an impact-channel tag. Environment remains channel-specific.
    if allowed_channels == _MARKET_CHANNELS:
        source_type = _clean_text(_provenance(record).get("source_type")).lower()
        return source_type in {
            "official",
            "regulatory",
            "issuer",
            "newswire",
            "journalism",
            "research",
            "market",
            "alternative",
        }
    return False
''',
    )

    replace_once(
        "educational_market_briefing_ui.py",
        '''    summary = _truncate(record.get("summary"), limit=240)
''',
        '''    summary = _truncate(record.get("summary") or record.get("topic"), limit=240)
''',
    )

    replace_once(
        "educational_market_briefing_ui.py",
        '''    evaluated_at = _parse_datetime(payload.get("evaluated_at"))
    return PublicEventSnapshot(
        records,
        evaluated_at,
        "available",
        "Governed public-event metadata is available.",
    )
''',
        '''    evaluated_at = _parse_datetime(payload.get("evaluated_at"))
    raw_coverage = payload.get("coverage")
    coverage = raw_coverage if isinstance(raw_coverage, Mapping) else {}
    failed_sources = int(coverage.get("failed_source_count", 0) or 0)
    required_ready = coverage.get("required_sources_ready")
    if not records:
        state = "degraded"
        detail = (
            "The current headline collection produced no usable records. This is a "
            "coverage condition, not evidence that the news cycle was quiet."
        )
    elif required_ready is False or failed_sources > 0:
        state = "degraded"
        detail = (
            "Recent source-qualified developments are available, but headline "
            "coverage is incomplete because one or more sources failed."
        )
    else:
        state = "available"
        detail = "Recent governed public-event metadata is available."
    return PublicEventSnapshot(
        records,
        evaluated_at,
        state,
        detail,
        coverage,
    )
''',
    )

    replace_once(
        "today_story_retention_runtime.py",
        '''_MAX_CACHED_RECORDS = 250
''',
        '''_MAX_CACHED_RECORDS = 250
_MAX_RETENTION_AGE = timedelta(hours=36)
''',
    )

    replace_once(
        "today_story_retention_runtime.py",
        '''    latest = _latest_record_time(event_ui, candidates, now=evaluated_at)
    if latest is None:
        return ()
''',
        '''    latest = _latest_record_time(event_ui, candidates, now=evaluated_at)
    if latest is None or evaluated_at - latest > _MAX_RETENTION_AGE:
        return ()
''',
    )

    replace_once(
        "today_story_retention_runtime.py",
        '''    for record in _records(records):
        observed_at = _record_time(event_ui, record)
        if observed_at is None or observed_at > now:
            continue
''',
        '''    cutoff = now - _MAX_RETENTION_AGE
    for record in _records(records):
        observed_at = _record_time(event_ui, record)
        if observed_at is None or observed_at > now or observed_at < cutoff:
            continue
''',
    )

    replace_once(
        "today_story_retention_runtime.py",
        '''            + ('<span class="ci-chip">No new qualifying stories</span>' if retained else "")
            + "</div></div>"
''',
        '''            + ('<span class="ci-chip">No new qualifying stories</span>' if retained else "")
            + (
                '<span class="ci-chip">Coverage incomplete</span>'
                if str(getattr(snapshot, "state", "available")) != "available"
                else ""
            )
            + "</div></div>"
''',
    )

    replace_once(
        "today_story_retention_runtime.py",
        '''            detail = story_ui._clean(getattr(snapshot, "detail", "")) or (
                "No material, source-qualified event cleared the last-24-hour controls."
            )
            hero += (
                '<div class="ci-primary"><div class="ci-meta"><span class="ci-rank">'
                "Quiet-day conclusion</span></div>"
                '<div class="ci-title">No new story earned investor attention.</div>'
                '<div class="ci-box"><div class="ci-label">Why this is useful</div>'
                f'<p>{escape(detail)} A quiet result is more trustworthy than filling the page '
                "with repetitive or low-quality headlines.</p></div></div>"
            )
''',
        '''            detail = story_ui._clean(getattr(snapshot, "detail", "")) or (
                "The current public-news collection did not return a usable story."
            )
            hero += (
                '<div class="ci-primary"><div class="ci-meta"><span class="ci-rank">'
                "Coverage status</span></div>"
                '<div class="ci-title">Current headline coverage is incomplete.</div>'
                '<div class="ci-box"><div class="ci-label">What this means</div>'
                f'<p>{escape(detail)} The application will not treat an empty record set as '
                "proof that nothing happened. Collection and filtering diagnostics remain "
                "visible while the feed refreshes.</p></div></div>"
            )
''',
    )

    replace_once(
        "tests/test_today_story_retention_runtime.py",
        '''def test_old_story_is_retained_without_renewing_its_publication_time() -> None:
    now = datetime(2026, 8, 3, 4, 0, tzinfo=timezone.utc)
    old_story = _record(
        identifier="prior",
        published_at=now - timedelta(days=3),
''',
        '''def test_recent_prior_story_is_retained_without_renewing_its_publication_time() -> None:
    now = datetime(2026, 8, 3, 4, 0, tzinfo=timezone.utc)
    old_story = _record(
        identifier="prior",
        published_at=now - timedelta(hours=30),
''',
    )
    replace_once(
        "tests/test_today_story_retention_runtime.py",
        '''    assert retained[0].published_at == now - timedelta(days=3)
''',
        '''    assert retained[0].published_at == now - timedelta(hours=30)
''',
    )
    replace_once(
        "tests/test_today_story_retention_runtime.py",
        '''    published_at = now - timedelta(days=3)
''',
        '''    published_at = now - timedelta(hours=30)
''',
    )

    write_new(
        "tests/test_today_news_coverage_resilience.py",
        '''from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import educational_market_briefing_ui as event_ui
import public_event_recency_runtime
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
    public_event_recency_runtime.install(event_ui)

    items = event_ui.build_today_items((_record("broad", now - timedelta(hours=1)),), now=now)

    assert [item.title for item in items] == ["Headline broad"]
    assert items[0].summary == "Headline broad"


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
    public_event_recency_runtime.install(event_ui)
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
    assert 'CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS\n        value: "900"' in render
    assert "No new story earned investor attention" not in retention_source
    assert "Current headline coverage is incomplete" in retention_source
''',
    )

    write_new(
        "docs/TODAY_NEWS_COVERAGE_RESILIENCE.md",
        '''# Today news coverage resilience

The Today surface now treats an empty event record set as a coverage defect, not as
proof that the investment news cycle was quiet.

## Collection continuity

- Broad GDELT discovery requests a rolling 24-hour window instead of one hour.
- Render collects public information every 15 minutes.
- Each pass merges current normalized records with a bounded 30-hour source-timed
  history, preventing one thin or degraded pass from erasing the day’s valid stories.
- Event identity is deduplicated and original publication time remains authoritative.
- Collection output includes source-health and record-count diagnostics.

## Display admission

The Today educational surface still rejects stale, future-dated, fixture, and raw OFAC
listing noise. It now admits a current source-qualified headline when a provider omitted
impact-channel metadata, then explains unresolved investment relevance neutrally. The
Environment surface remains restricted to economic impact channels.

## Empty-state truthfulness

When no usable current records exist, the UI reports incomplete coverage and keeps the
collection/filtering condition visible. It no longer says that no story deserved
attention. Historical retention is capped at 36 hours and never renews publication age.

These controls affect educational presentation only. They do not lower evidence,
specialist, CIO, cash-hurdle, construction, sizing, paper-execution, or real-money
boundaries.
''',
    )


if __name__ == "__main__":
    main()
