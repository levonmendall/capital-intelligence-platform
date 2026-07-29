"""Immutable records used by the historical backfill and shadow replay system."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Mapping

UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def parse_timestamp(value: str | date | datetime) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, date):
        result = datetime(value.year, value.month, value.day, tzinfo=UTC)
    else:
        text = str(value).strip()
        if not text:
            raise ValueError("timestamp cannot be empty")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            result = datetime.fromisoformat(text)
        except ValueError:
            result = datetime.fromisoformat(text + "T00:00:00+00:00")
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def iso_timestamp(value: str | date | datetime) -> str:
    return parse_timestamp(value).isoformat().replace("+00:00", "Z")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True, slots=True)
class HistoricalRecord:
    source: str
    dataset: str
    observed_at: str
    available_at: str
    retrieved_at: str
    payload: Mapping[str, Any]
    strict_replay_eligible: bool
    quality: str = "reported"
    limitations: tuple[str, ...] = field(default_factory=tuple)
    provenance_url: str = ""
    schema_version: int = 1
    content_hash: str = ""
    record_id: str = ""

    def __post_init__(self) -> None:
        source = self.source.strip().lower()
        dataset = self.dataset.strip().lower()
        if not source or not dataset:
            raise ValueError("source and dataset are required")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "dataset", dataset)
        object.__setattr__(self, "observed_at", iso_timestamp(self.observed_at))
        object.__setattr__(self, "available_at", iso_timestamp(self.available_at))
        object.__setattr__(self, "retrieved_at", iso_timestamp(self.retrieved_at))
        normalized_payload = json.loads(canonical_json(dict(self.payload)))
        object.__setattr__(self, "payload", normalized_payload)
        object.__setattr__(self, "limitations", tuple(sorted({str(x) for x in self.limitations if str(x)})))
        digest_material = {
            "source": source,
            "dataset": dataset,
            "observed_at": self.observed_at,
            "available_at": self.available_at,
            "payload": normalized_payload,
            "schema_version": self.schema_version,
        }
        digest = hashlib.sha256(canonical_json(digest_material).encode("utf-8")).hexdigest()
        if self.content_hash and self.content_hash != digest:
            raise ValueError("content_hash does not match record content")
        object.__setattr__(self, "content_hash", digest)
        if not self.record_id:
            object.__setattr__(self, "record_id", f"{source}:{dataset}:{digest}")

    @property
    def observed_datetime(self) -> datetime:
        return parse_timestamp(self.observed_at)

    @property
    def available_datetime(self) -> datetime:
        return parse_timestamp(self.available_at)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceResult:
    source: str
    state: str
    records: tuple[HistoricalRecord, ...] = field(default_factory=tuple)
    blockers: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.state not in {"available", "degraded", "unavailable", "failed"}:
            raise ValueError(f"unsupported source state: {self.state}")


@dataclass(frozen=True, slots=True)
class BackfillReport:
    started_at: str
    completed_at: str
    start_date: str
    end_date: str
    source_results: tuple[SourceResult, ...]
    records_written: int
    duplicates_skipped: int
    state: str
    strict_replay_records: int
    real_money_authorized: bool = False
    performance_claims_authorized: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "records_written": self.records_written,
            "duplicates_skipped": self.duplicates_skipped,
            "strict_replay_records": self.strict_replay_records,
            "state": self.state,
            "real_money_authorized": self.real_money_authorized,
            "performance_claims_authorized": self.performance_claims_authorized,
            "source_results": [
                {
                    "source": item.source,
                    "state": item.state,
                    "record_count": len(item.records),
                    "blockers": list(item.blockers),
                    "warnings": list(item.warnings),
                }
                for item in self.source_results
            ],
        }
