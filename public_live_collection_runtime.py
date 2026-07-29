"""Persist public live-information evidence in the operating application runtime.

The GitHub workflow remains an independent hourly observability check. This module
ensures the Streamlit/headless paper operator writes the same credential-safe
reports into the persistent application data volume before the CIO cycle runs.
Temporary upstream outages are recorded as degraded evidence; they do not become
available evidence and do not by themselves stop paper operation.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from providers.public_live_information import load_public_live_source_catalog
from providers.public_live_information_extended import (
    ImpactfulPublicLiveInformationProvider,
)


@dataclass(frozen=True, slots=True)
class PublicLiveCollectionResult:
    state: str
    detail: str
    evaluated_at: datetime
    exit_code: int | None
    report_path: Path
    records_path: Path
    state_path: Path
    required_sources_ready: bool | None = None
    source_count: int = 0
    failed_source_count: int = 0
    next_due_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "detail": self.detail,
            "evaluated_at": self.evaluated_at.isoformat(),
            "exit_code": self.exit_code,
            "report_path": str(self.report_path),
            "records_path": str(self.records_path),
            "state_path": str(self.state_path),
            "required_sources_ready": self.required_sources_ready,
            "source_count": self.source_count,
            "failed_source_count": self.failed_source_count,
            "next_due_at": (
                self.next_due_at.isoformat() if self.next_due_at is not None else None
            ),
            "full_article_text_stored": False,
            "secret_values_disclosed": False,
            "real_money_authorized": False,
        }


def _enabled() -> bool:
    raw = os.getenv("CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_ENABLED", "true")
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_ENABLED must be boolean"
    )


def _data_path(environment_name: str, default_name: str) -> Path:
    configured = os.getenv(environment_name, "").strip()
    if configured:
        return Path(configured).expanduser()
    data_dir = Path(
        os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
    ).expanduser()
    return data_dir / default_name


def _interval() -> timedelta:
    raw = os.getenv(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS",
        "3600",
    )
    seconds = int(raw)
    if not 300 <= seconds <= 86400:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS "
            "must be between 300 and 86400"
        )
    return timedelta(seconds=seconds)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("collection time must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _read_state(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _acquire_lock(path: Path, *, now: datetime) -> bool:
    """Acquire an atomic cross-process lease, removing only clearly stale leases."""

    path.parent.mkdir(parents=True, exist_ok=True)
    stale_after = timedelta(minutes=20)
    for _ in range(2):
        try:
            descriptor = os.open(
                path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            try:
                modified_at = datetime.fromtimestamp(
                    path.stat().st_mtime,
                    tz=timezone.utc,
                )
            except OSError:
                return False
            if now - modified_at <= stale_after:
                return False
            try:
                path.unlink()
            except OSError:
                return False
            continue
        try:
            os.write(descriptor, (now.isoformat() + "\n").encode("utf-8"))
        finally:
            os.close(descriptor)
        return True
    return False


def collect_public_live_information_if_due(
    *,
    now: datetime | None = None,
    force: bool = False,
    provider_factory: Callable[[object], object] | None = None,
) -> PublicLiveCollectionResult:
    """Collect once immediately when no state exists, then at most once per interval."""

    evaluated_at = _aware_utc(now or datetime.now(timezone.utc))
    report_path = _data_path(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_REPORT",
        "public-live-information-report.json",
    )
    records_path = _data_path(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_RECORDS",
        "public-live-information-records.json",
    )
    state_path = _data_path(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_STATE",
        "public-live-information-runtime-state.json",
    )
    lock_path = _data_path(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_LOCK",
        "public-live-information-runtime.lock",
    )

    if not _enabled():
        return PublicLiveCollectionResult(
            state="disabled",
            detail="Runtime public live-information collection is disabled.",
            evaluated_at=evaluated_at,
            exit_code=None,
            report_path=report_path,
            records_path=records_path,
            state_path=state_path,
        )

    interval = _interval()
    previous = _read_state(state_path)
    last_completed_at = _parse_time(previous.get("completed_at"))
    next_due_at = (
        last_completed_at + interval if last_completed_at is not None else evaluated_at
    )
    if not force and last_completed_at is not None and evaluated_at < next_due_at:
        return PublicLiveCollectionResult(
            state="not_due",
            detail="The latest runtime public collection is still inside the hourly window.",
            evaluated_at=evaluated_at,
            exit_code=(
                int(previous["exit_code"])
                if isinstance(previous.get("exit_code"), int)
                else None
            ),
            report_path=report_path,
            records_path=records_path,
            state_path=state_path,
            required_sources_ready=(
                bool(previous["required_sources_ready"])
                if isinstance(previous.get("required_sources_ready"), bool)
                else None
            ),
            source_count=int(previous.get("source_count", 0) or 0),
            failed_source_count=int(previous.get("failed_source_count", 0) or 0),
            next_due_at=next_due_at,
        )

    if not _acquire_lock(lock_path, now=evaluated_at):
        return PublicLiveCollectionResult(
            state="in_progress",
            detail=(
                "Another application session owns the runtime public-information "
                "collection lease."
            ),
            evaluated_at=evaluated_at,
            exit_code=None,
            report_path=report_path,
            records_path=records_path,
            state_path=state_path,
            required_sources_ready=(
                bool(previous["required_sources_ready"])
                if isinstance(previous.get("required_sources_ready"), bool)
                else None
            ),
            source_count=int(previous.get("source_count", 0) or 0),
            failed_source_count=int(previous.get("failed_source_count", 0) or 0),
            next_due_at=next_due_at,
        )

    try:
        attempted_payload: dict[str, object] = {
            "schema_version": "public-live-information-runtime-state.v1",
            "state": "collecting",
            "attempted_at": evaluated_at.isoformat(),
            "report_path": str(report_path),
            "records_path": str(records_path),
            "interval_seconds": int(interval.total_seconds()),
            "real_money_authorized": False,
        }
        _write_json(state_path, attempted_payload)

        try:
            catalog_path = os.getenv(
                "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_SOURCE_CATALOG",
                "config/public_live_information_sources.json",
            )
            catalog = load_public_live_source_catalog(catalog_path)
            factory = provider_factory or ImpactfulPublicLiveInformationProvider
            report = factory(catalog).collect(include_optional=True)
            report_payload = report.to_dict(include_records=False)
            records_payload = {
                "schema_version": "public-live-information-record-set.v1",
                "catalog_identifier": report.catalog_identifier,
                "evaluated_at": report.evaluated_at.isoformat(),
                "records": [item.to_dict() for item in report.records],
                "full_article_text_stored": False,
                "secret_values_disclosed": False,
                "real_money_authorized": False,
            }
            _write_json(report_path, report_payload)
            _write_json(records_path, records_payload)

            failed_source_count = sum(
                1 for item in report.sources if not item.succeeded
            )
            if not report.required_sources_ready:
                exit_code = 3
                state = "degraded"
                detail = (
                    "One or more required public sources were unavailable; exact "
                    "failures are persisted and cannot support a CIO decision."
                )
            elif failed_source_count:
                exit_code = 2
                state = "degraded"
                detail = (
                    "Required public sources are available, but one or more optional "
                    "sources were unavailable."
                )
            else:
                exit_code = 0
                state = "available"
                detail = "Runtime public live-information collection completed."

            completed_at = _aware_utc(report.evaluated_at)
            next_due_at = completed_at + interval
            state_payload = {
                "schema_version": "public-live-information-runtime-state.v1",
                "state": state,
                "detail": detail,
                "attempted_at": evaluated_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "next_due_at": next_due_at.isoformat(),
                "exit_code": exit_code,
                "required_sources_ready": bool(report.required_sources_ready),
                "source_count": len(report.sources),
                "failed_source_count": failed_source_count,
                "record_count": len(report.records),
                "catalog_identifier": report.catalog_identifier,
                "report_path": str(report_path),
                "records_path": str(records_path),
                "interval_seconds": int(interval.total_seconds()),
                "full_article_text_stored": False,
                "secret_values_disclosed": False,
                "real_money_authorized": False,
            }
            _write_json(state_path, state_payload)
            return PublicLiveCollectionResult(
                state=state,
                detail=detail,
                evaluated_at=completed_at,
                exit_code=exit_code,
                report_path=report_path,
                records_path=records_path,
                state_path=state_path,
                required_sources_ready=bool(report.required_sources_ready),
                source_count=len(report.sources),
                failed_source_count=failed_source_count,
                next_due_at=next_due_at,
            )
        except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
            detail = f"Runtime public live-information collector failed: {error}"
            _write_json(
                state_path,
                {
                    "schema_version": "public-live-information-runtime-state.v1",
                    "state": "failed",
                    "detail": detail,
                    "attempted_at": evaluated_at.isoformat(),
                    "completed_at": evaluated_at.isoformat(),
                    "exit_code": 4,
                    "report_path": str(report_path),
                    "records_path": str(records_path),
                    "interval_seconds": int(interval.total_seconds()),
                    "secret_values_disclosed": False,
                    "real_money_authorized": False,
                },
            )
            return PublicLiveCollectionResult(
                state="failed",
                detail=detail,
                evaluated_at=evaluated_at,
                exit_code=4,
                report_path=report_path,
                records_path=records_path,
                state_path=state_path,
            )
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
