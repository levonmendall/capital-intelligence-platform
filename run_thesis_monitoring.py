"""Run one governed scheduled and event-driven living-thesis monitoring cycle."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from api.config import ApiSettings
from cio.persistence import SQLiteCIOJournal
from thesis.orchestration import (
    SQLiteThesisMonitoringStore,
    ThesisMonitoringOrchestrator,
    ThesisMonitoringTrigger,
    ThesisReviewPriority,
    ThesisTriggerSource,
)


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must include a UTC offset")
    return parsed


def _factory(value: str | None):
    if value is None:
        return None
    if ":" not in value:
        raise ValueError("factories must use module:function form")
    module_name, attribute_name = value.split(":", 1)
    factory = getattr(importlib.import_module(module_name), attribute_name, None)
    if not callable(factory):
        raise ValueError(f"factory {value!r} is not callable")
    return factory()


def _triggers(path: str | None) -> tuple[ThesisMonitoringTrigger, ...]:
    if path is None:
        return ()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("trigger file must encode a list")
    return tuple(
        ThesisMonitoringTrigger(
            identifier=str(item["identifier"]),
            thesis_identifier=str(item["thesis_identifier"]),
            source=ThesisTriggerSource(str(item.get("source", "event"))),
            as_of=_timestamp(str(item["as_of"])),
            reason=str(item["reason"]),
            evidence_fingerprint=str(item["evidence_fingerprint"]),
            priority=ThesisReviewPriority(str(item.get("priority", "standard"))),
        )
        for item in payload
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run scheduled and event-driven living-thesis reviews. Monitoring "
            "may queue a CIO proposal but cannot alter positions or create orders."
        )
    )
    parser.add_argument("--evidence-provider", required=True)
    parser.add_argument("--notification-publisher")
    parser.add_argument("--as-of")
    parser.add_argument("--trigger-file")
    parser.add_argument("--events-only", action="store_true")
    parser.add_argument("--require-all-success", action="store_true")
    parser.add_argument("--suppression-hours", type=float, default=24.0)
    parser.add_argument("--journal-database")
    parser.add_argument("--monitoring-database")
    args = parser.parse_args(argv)

    try:
        as_of = _timestamp(args.as_of)
        provider = _factory(args.evidence_provider)
        publisher = _factory(args.notification_publisher)
        triggers = _triggers(args.trigger_file)
        if args.suppression_hours < 0:
            raise ValueError("suppression-hours cannot be negative")
    except (ImportError, AttributeError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))

    settings = ApiSettings.from_env()
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    journal_path = Path(args.journal_database).expanduser() if args.journal_database else settings.journal_database
    monitoring_path = (
        Path(args.monitoring_database).expanduser()
        if args.monitoring_database
        else Path(
            os.getenv(
                "CAPITAL_INTELLIGENCE_THESIS_MONITORING_DATABASE",
                str(data_dir / "thesis_monitoring.db"),
            )
        ).expanduser()
    )
    orchestrator = ThesisMonitoringOrchestrator(
        journal=SQLiteCIOJournal(journal_path),
        store=SQLiteThesisMonitoringStore(monitoring_path),
        evidence_provider=provider,
        notification_publisher=publisher,
        suppression_window=timedelta(hours=args.suppression_hours),
    )
    try:
        result = orchestrator.run(
            as_of=as_of,
            event_triggers=triggers,
            include_scheduled=not args.events_only,
        )
    except Exception as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, indent=2, sort_keys=True))
        return 4

    payload: dict[str, Any] = {
        "status": "completed" if result.all_success else "completed_with_failures",
        "evaluated_at": result.evaluated_at.isoformat(),
        "results": [
            {
                "trigger_identifier": item.trigger_identifier,
                "thesis_identifier": item.thesis_identifier,
                "review_identifier": item.review_identifier,
                "status": item.status,
                "required_cio_review": item.required_cio_review,
                "queue_item_identifier": item.queue_item_identifier,
                "notification_reference": item.notification_reference,
                "error": item.error,
            }
            for item in result.results
        ],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.require_all_success and not result.all_success:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
