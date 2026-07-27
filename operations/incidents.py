"""Append-only operational incident authority for test-readiness evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class OperationalIncidentError(RuntimeError):
    """Raised when operational incident history is invalid or inconsistent."""


class OperationalIncidentIntegrityError(OperationalIncidentError):
    """Raised when the append-only incident chain is invalid."""


class OperationalIncidentSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OperationalIncidentState(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _texts(value: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} requires at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class OperationalIncidentEvent:
    """One immutable state transition for one operational incident."""

    identifier: str
    incident_identifier: str
    severity: OperationalIncidentSeverity
    state: OperationalIncidentState
    occurred_at: datetime
    detected_at: datetime
    classification: str
    summary: str
    baseline_identifier: str
    process_version: str
    code_version: str
    source_identifiers: tuple[str, ...]
    resolution_identifier: str | None = None
    schema_version: str = "operational-incident-event.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "incident_identifier",
            "classification",
            "summary",
            "baseline_identifier",
            "process_version",
            "code_version",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.severity, OperationalIncidentSeverity):
            raise TypeError("severity must be OperationalIncidentSeverity")
        if not isinstance(self.state, OperationalIncidentState):
            raise TypeError("state must be OperationalIncidentState")
        _aware(self.occurred_at, field_name="occurred_at")
        _aware(self.detected_at, field_name="detected_at")
        if self.occurred_at < self.detected_at:
            raise ValueError("occurred_at cannot predate detected_at")
        object.__setattr__(
            self,
            "source_identifiers",
            _texts(
                self.source_identifiers,
                field_name="source_identifiers",
                minimum=1,
            ),
        )
        if self.resolution_identifier is not None:
            object.__setattr__(
                self,
                "resolution_identifier",
                _text(
                    self.resolution_identifier,
                    field_name="resolution_identifier",
                ),
            )
        if self.state is OperationalIncidentState.RESOLVED and (
            self.resolution_identifier is None
        ):
            raise ValueError("resolved incidents require a resolution identifier")
        if self.state is OperationalIncidentState.OPEN and (
            self.resolution_identifier is not None
        ):
            raise ValueError("open incidents cannot contain a resolution identifier")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "incident_identifier": self.incident_identifier,
            "severity": self.severity.value,
            "state": self.state.value,
            "occurred_at": self.occurred_at.isoformat(),
            "detected_at": self.detected_at.isoformat(),
            "classification": self.classification,
            "summary": self.summary,
            "baseline_identifier": self.baseline_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "source_identifiers": list(self.source_identifiers),
            "resolution_identifier": self.resolution_identifier,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OperationalIncidentEvent":
        return cls(
            identifier=str(payload["identifier"]),
            incident_identifier=str(payload["incident_identifier"]),
            severity=OperationalIncidentSeverity(str(payload["severity"])),
            state=OperationalIncidentState(str(payload["state"])),
            occurred_at=datetime.fromisoformat(str(payload["occurred_at"])),
            detected_at=datetime.fromisoformat(str(payload["detected_at"])),
            classification=str(payload["classification"]),
            summary=str(payload["summary"]),
            baseline_identifier=str(payload["baseline_identifier"]),
            process_version=str(payload["process_version"]),
            code_version=str(payload["code_version"]),
            source_identifiers=tuple(
                str(item) for item in payload["source_identifiers"]
            ),
            resolution_identifier=(
                None
                if payload.get("resolution_identifier") is None
                else str(payload["resolution_identifier"])
            ),
            schema_version=str(
                payload.get("schema_version", "operational-incident-event.v1")
            ),
        )


class SQLiteOperationalIncidentStore:
    """Append-only SHA-256 incident history with point-in-time active state."""

    _TABLE = "operational_incident_events"
    _GENESIS = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    incident_identifier TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS incident_state_lookup
                ON {self._TABLE}(incident_identifier, occurred_at, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'operational incident history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'operational incident history is append-only'); END;
                """
            )

    @staticmethod
    def _hash(
        sequence: int,
        event_identifier: str,
        incident_identifier: str,
        occurred_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        raw = "|".join(
            (
                str(sequence),
                event_identifier,
                incident_identifier,
                occurred_at,
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def append(self, event: OperationalIncidentEvent) -> int:
        if not isinstance(event, OperationalIncidentEvent):
            raise TypeError("event must be OperationalIncidentEvent")
        self.verify_integrity()
        payload_json = _canonical_json(event.to_dict())
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence,payload_json FROM {self._TABLE} "
                "WHERE event_identifier=?",
                (event.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing[1]) != payload_json:
                    raise OperationalIncidentError(
                        "incident event identifier already exists with different content"
                    )
                return int(existing[0])
            previous_event = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE incident_identifier=? ORDER BY occurred_at DESC, sequence DESC LIMIT 1",
                (event.incident_identifier,),
            ).fetchone()
            if previous_event is not None:
                previous_state = OperationalIncidentEvent.from_dict(
                    json.loads(str(previous_event[0]))
                )
                if event.occurred_at < previous_state.occurred_at:
                    raise OperationalIncidentError(
                        "incident state transitions cannot move backward in time"
                    )
                if previous_state.state is OperationalIncidentState.RESOLVED:
                    raise OperationalIncidentError(
                        "a resolved incident cannot be reopened under the same identifier"
                    )
                if event.state is OperationalIncidentState.OPEN:
                    raise OperationalIncidentError(
                        "an open incident cannot receive another open state event"
                    )
            elif event.state is OperationalIncidentState.RESOLVED:
                raise OperationalIncidentError(
                    "an incident cannot be resolved before it is opened"
                )
            tail = connection.execute(
                f"SELECT sequence,content_hash FROM {self._TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail[0]) + 1
            previous_hash = self._GENESIS if tail is None else str(tail[1])
            occurred_at = event.occurred_at.isoformat()
            content_hash = self._hash(
                sequence,
                event.identifier,
                event.incident_identifier,
                occurred_at,
                payload_json,
                previous_hash,
            )
            connection.execute(
                f"INSERT INTO {self._TABLE} VALUES (?,?,?,?,?,?,?)",
                (
                    sequence,
                    event.identifier,
                    event.incident_identifier,
                    occurred_at,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def events(
        self,
        *,
        as_of: datetime | None = None,
    ) -> tuple[OperationalIncidentEvent, ...]:
        with sqlite3.connect(self.path) as connection:
            if as_of is None:
                rows = connection.execute(
                    f"SELECT payload_json FROM {self._TABLE} ORDER BY sequence"
                ).fetchall()
            else:
                timestamp = _aware(as_of, field_name="as_of").isoformat()
                rows = connection.execute(
                    f"SELECT payload_json FROM {self._TABLE} "
                    "WHERE occurred_at<=? ORDER BY sequence",
                    (timestamp,),
                ).fetchall()
        return tuple(
            OperationalIncidentEvent.from_dict(json.loads(str(row[0])))
            for row in rows
        )

    def active_incidents(
        self,
        *,
        as_of: datetime,
    ) -> tuple[OperationalIncidentEvent, ...]:
        latest: dict[str, OperationalIncidentEvent] = {}
        for event in self.events(as_of=as_of):
            latest[event.incident_identifier] = event
        return tuple(
            sorted(
                (
                    item
                    for item in latest.values()
                    if item.state is OperationalIncidentState.OPEN
                ),
                key=lambda item: (item.severity.value, item.incident_identifier),
            )
        )

    def unresolved_critical(
        self,
        *,
        as_of: datetime,
    ) -> tuple[OperationalIncidentEvent, ...]:
        return tuple(
            item
            for item in self.active_incidents(as_of=as_of)
            if item.severity is OperationalIncidentSeverity.CRITICAL
        )

    def verify_integrity(self) -> bool:
        previous = self._GENESIS
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        for expected, row in enumerate(rows, 1):
            if int(row[0]) != expected or str(row[5]) != previous:
                raise OperationalIncidentIntegrityError(
                    "operational incident chain is not contiguous"
                )
            actual = self._hash(
                int(row[0]),
                str(row[1]),
                str(row[2]),
                str(row[3]),
                str(row[4]),
                str(row[5]),
            )
            if str(row[6]) != actual:
                raise OperationalIncidentIntegrityError(
                    "operational incident content hash is invalid"
                )
            previous = actual
        return True


__all__ = [
    "OperationalIncidentError",
    "OperationalIncidentEvent",
    "OperationalIncidentIntegrityError",
    "OperationalIncidentSeverity",
    "OperationalIncidentState",
    "SQLiteOperationalIncidentStore",
]
