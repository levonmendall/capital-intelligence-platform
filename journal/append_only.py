"""Tamper-evident append-only journal for institutional decisions."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from evaluation import DecisionQualityReview
from intelligence.regime_pipeline import InstitutionalRegimeRun


class JournalEventType(str, Enum):
    """Versioned event types supported by the institutional ledger."""

    REGIME_RUN = "regime_run"
    DECISION_QUALITY_REVIEW = "decision_quality_review"


class JournalIntegrityError(RuntimeError):
    """Raised when the persisted hash chain cannot be verified."""


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _canonical_json(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise TypeError("payload must be a mapping")
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "payload must contain finite JSON-serializable values"
        ) from error


@dataclass(frozen=True, slots=True)
class JournalEvent:
    """One immutable event recovered from the institutional ledger."""

    sequence: int
    event_identifier: str
    aggregate_identifier: str
    event_type: JournalEventType
    occurred_at: datetime
    recorded_at: datetime
    schema_version: str
    payload_json: str
    previous_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(
            self.sequence,
            int,
        ):
            raise TypeError("sequence must be an int")
        if self.sequence < 1:
            raise ValueError("sequence must be positive")
        for field_name in (
            "event_identifier",
            "aggregate_identifier",
            "schema_version",
            "previous_hash",
            "content_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        if not isinstance(self.event_type, JournalEventType):
            raise TypeError(
                "event_type must be a JournalEventType"
            )
        _aware_datetime(self.occurred_at, field_name="occurred_at")
        _aware_datetime(self.recorded_at, field_name="recorded_at")
        try:
            payload = json.loads(self.payload_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("payload_json must be valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("payload_json must encode an object")

    @property
    def payload(self) -> dict[str, Any]:
        """Return a fresh copy of the immutable serialized payload."""

        return json.loads(self.payload_json)


def serialize_regime_run(
    run: InstitutionalRegimeRun,
    *,
    code_version: str = "unknown",
) -> dict[str, Any]:
    """Serialize a complete regime run without discarding lineage."""

    if not isinstance(run, InstitutionalRegimeRun):
        raise TypeError("run must be an InstitutionalRegimeRun")
    resolved_code_version = _required_text(
        code_version,
        field_name="code_version",
    )
    assessment = run.assessment
    result = assessment.result
    evidence = assessment.evidence
    return {
        "as_of": run.as_of.isoformat(),
        "code_version": resolved_code_version,
        "provider": run.provider,
        "loaded_count": run.loaded_count,
        "unavailable_count": run.unavailable_count,
        "degraded": run.degraded,
        "loads": [
            {
                "signal": load.request.signal,
                "provider_series_identifier": (
                    load.request.series.provider_series_identifier
                ),
                "limit": load.request.limit,
                "state": load.state.value,
                "error": load.error,
                "observations": [
                    observation.to_dict()
                    for observation in load.observations
                ],
            }
            for load in run.loads
        ],
        "evidence": {
            "rules_version": evidence.rules_version,
            "data_coverage": evidence.data_coverage,
            "quality_score": evidence.quality_score,
            "signals": [
                {
                    "name": signal.name.value,
                    "score": signal.score,
                    "quality_score": signal.quality_score,
                    "calculation": signal.calculation,
                    "lineage": [
                        {
                            "provider": item.provider,
                            "series_identifier": (
                                item.series_identifier
                            ),
                            "observation_date": (
                                item.observation_date.isoformat()
                            ),
                            "released_at": (
                                item.released_at.isoformat()
                            ),
                            "retrieved_at": (
                                item.retrieved_at.isoformat()
                            ),
                            "quality_state": (
                                item.quality_state.value
                            ),
                            "value": item.value,
                        }
                        for item in signal.lineage
                    ],
                }
                for signal in evidence.signals
            ],
        },
        "classification": {
            "regime": result.regime.value,
            "engine_confidence": result.confidence,
            "evidence_adjusted_confidence": (
                assessment.confidence
            ),
            "data_coverage": result.data_coverage,
            "conclusion": result.conclusion,
            "strengths": list(result.strengths),
            "risks": list(result.risks),
            "signals": [
                {
                    "name": signal.name,
                    "score": signal.score,
                    "assessment": signal.assessment,
                    "explanation": signal.explanation,
                }
                for signal in result.signals
            ],
        },
    }


def serialize_decision_quality_review(
    review: DecisionQualityReview,
) -> dict[str, Any]:
    """Serialize a process/outcome review for append-only storage."""

    if not isinstance(review, DecisionQualityReview):
        raise TypeError(
            "review must be a DecisionQualityReview"
        )
    return {
        "decision_identifier": review.decision_identifier,
        "reviewed_at": review.reviewed_at.isoformat(),
        "process_verdict": review.process_verdict.value,
        "outcome": review.outcome.value,
        "classification": review.classification.value,
        "process_evidence": list(review.process_evidence),
        "outcome_evidence": list(review.outcome_evidence),
        "lessons": list(review.lessons),
        "reviewer": review.reviewer,
    }


class SQLiteAppendOnlyJournal:
    """SQLite event ledger protected by triggers and a hash chain."""

    _GENESIS_HASH = "0" * 64

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        identifier_factory: Callable[[], str] | None = None,
    ) -> None:
        self.path = Path(path)
        if self.path.exists() and self.path.is_dir():
            raise ValueError("journal path must be a file")
        self._clock = clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._identifier_factory = identifier_factory or (
            lambda: str(uuid.uuid4())
        )
        self.initialize()

    def initialize(self) -> None:
        """Create the ledger and database-level append-only guards."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS journal_events (
                    sequence INTEGER PRIMARY KEY,
                    event_identifier TEXT NOT NULL UNIQUE,
                    aggregate_identifier TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );

                CREATE INDEX IF NOT EXISTS
                    journal_events_aggregate_sequence
                ON journal_events (
                    aggregate_identifier,
                    sequence
                );

                CREATE TRIGGER IF NOT EXISTS
                    journal_events_prevent_update
                BEFORE UPDATE ON journal_events
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'institutional journal is append-only'
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS
                    journal_events_prevent_delete
                BEFORE DELETE ON journal_events
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'institutional journal is append-only'
                    );
                END;
                """
            )

    def append(
        self,
        *,
        event_type: JournalEventType,
        aggregate_identifier: str,
        occurred_at: datetime,
        payload: Mapping[str, Any],
        schema_version: str = "1",
    ) -> JournalEvent:
        """Append one event under a transaction-wide write lock."""

        if not isinstance(event_type, JournalEventType):
            raise TypeError(
                "event_type must be a JournalEventType"
            )
        aggregate = _required_text(
            aggregate_identifier,
            field_name="aggregate_identifier",
        )
        occurred = _aware_datetime(
            occurred_at,
            field_name="occurred_at",
        )
        version = _required_text(
            schema_version,
            field_name="schema_version",
        )
        recorded = _aware_datetime(
            self._clock(),
            field_name="clock",
        )
        event_identifier = _required_text(
            self._identifier_factory(),
            field_name="event_identifier",
        )
        payload_json = _canonical_json(payload)

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                """
                SELECT sequence, content_hash
                FROM journal_events
                ORDER BY sequence DESC
                LIMIT 1
                """
            ).fetchone()
            sequence = (
                int(previous["sequence"]) + 1
                if previous is not None
                else 1
            )
            previous_hash = (
                str(previous["content_hash"])
                if previous is not None
                else self._GENESIS_HASH
            )
            content_hash = self._content_hash(
                sequence=sequence,
                event_identifier=event_identifier,
                aggregate_identifier=aggregate,
                event_type=event_type,
                occurred_at=occurred,
                recorded_at=recorded,
                schema_version=version,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                """
                INSERT INTO journal_events (
                    sequence,
                    event_identifier,
                    aggregate_identifier,
                    event_type,
                    occurred_at,
                    recorded_at,
                    schema_version,
                    payload_json,
                    previous_hash,
                    content_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    event_identifier,
                    aggregate,
                    event_type.value,
                    occurred.isoformat(),
                    recorded.isoformat(),
                    version,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return JournalEvent(
            sequence=sequence,
            event_identifier=event_identifier,
            aggregate_identifier=aggregate,
            event_type=event_type,
            occurred_at=occurred,
            recorded_at=recorded,
            schema_version=version,
            payload_json=payload_json,
            previous_hash=previous_hash,
            content_hash=content_hash,
        )

    def append_regime_run(
        self,
        run: InstitutionalRegimeRun,
        *,
        run_identifier: str | None = None,
        code_version: str | None = None,
    ) -> JournalEvent:
        """Append a complete point-in-time regime run."""

        aggregate = run_identifier or (
            f"regime:{run.as_of.isoformat()}"
        )
        resolved_code_version = (
            code_version
            or os.getenv("CAPITAL_INTELLIGENCE_CODE_VERSION")
            or os.getenv("GITHUB_SHA")
            or "unknown"
        )
        return self.append(
            event_type=JournalEventType.REGIME_RUN,
            aggregate_identifier=aggregate,
            occurred_at=run.as_of,
            payload=serialize_regime_run(
                run,
                code_version=resolved_code_version,
            ),
            schema_version="regime-run.v1",
        )

    def append_decision_quality_review(
        self,
        review: DecisionQualityReview,
    ) -> JournalEvent:
        """Append a review linked to its immutable decision identifier."""

        return self.append(
            event_type=(
                JournalEventType.DECISION_QUALITY_REVIEW
            ),
            aggregate_identifier=(
                f"decision:{review.decision_identifier}"
            ),
            occurred_at=review.reviewed_at,
            payload=serialize_decision_quality_review(review),
            schema_version="decision-quality-review.v1",
        )

    def events(
        self,
        *,
        aggregate_identifier: str | None = None,
    ) -> tuple[JournalEvent, ...]:
        """Return events in immutable ledger order."""

        with self._connect() as connection:
            if aggregate_identifier is None:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM journal_events
                    ORDER BY sequence
                    """
                ).fetchall()
            else:
                aggregate = _required_text(
                    aggregate_identifier,
                    field_name="aggregate_identifier",
                )
                rows = connection.execute(
                    """
                    SELECT *
                    FROM journal_events
                    WHERE aggregate_identifier = ?
                    ORDER BY sequence
                    """,
                    (aggregate,),
                ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def verify_integrity(self) -> bool:
        """Return whether sequence and every hash-chain link are valid."""

        previous_hash = self._GENESIS_HASH
        for expected_sequence, event in enumerate(
            self.events(),
            start=1,
        ):
            if event.sequence != expected_sequence:
                return False
            if event.previous_hash != previous_hash:
                return False
            expected_hash = self._content_hash(
                sequence=event.sequence,
                event_identifier=event.event_identifier,
                aggregate_identifier=(
                    event.aggregate_identifier
                ),
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                recorded_at=event.recorded_at,
                schema_version=event.schema_version,
                payload_json=event.payload_json,
                previous_hash=event.previous_hash,
            )
            if event.content_hash != expected_hash:
                return False
            previous_hash = event.content_hash
        return True

    def require_integrity(self) -> None:
        """Raise if journal sequence or hash-chain verification fails."""

        if not self.verify_integrity():
            raise JournalIntegrityError(
                "institutional journal integrity check failed"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @classmethod
    def _content_hash(
        cls,
        *,
        sequence: int,
        event_identifier: str,
        aggregate_identifier: str,
        event_type: JournalEventType,
        occurred_at: datetime,
        recorded_at: datetime,
        schema_version: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        canonical = json.dumps(
            {
                "sequence": sequence,
                "event_identifier": event_identifier,
                "aggregate_identifier": aggregate_identifier,
                "event_type": event_type.value,
                "occurred_at": occurred_at.isoformat(),
                "recorded_at": recorded_at.isoformat(),
                "schema_version": schema_version,
                "payload": json.loads(payload_json),
                "previous_hash": previous_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> JournalEvent:
        return JournalEvent(
            sequence=int(row["sequence"]),
            event_identifier=str(row["event_identifier"]),
            aggregate_identifier=str(
                row["aggregate_identifier"]
            ),
            event_type=JournalEventType(row["event_type"]),
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
            schema_version=str(row["schema_version"]),
            payload_json=str(row["payload_json"]),
            previous_hash=str(row["previous_hash"]),
            content_hash=str(row["content_hash"]),
        )


__all__ = [
    "JournalEvent",
    "JournalEventType",
    "JournalIntegrityError",
    "SQLiteAppendOnlyJournal",
    "serialize_decision_quality_review",
    "serialize_regime_run",
]
