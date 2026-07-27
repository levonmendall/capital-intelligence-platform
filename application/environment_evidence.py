"""Canonical Environment evidence with decision-time and subsequent separation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


class EnvironmentEvidenceError(RuntimeError):
    """Raised when Environment evidence violates its point-in-time boundary."""


class EnvironmentEvidenceIntegrityError(EnvironmentEvidenceError):
    """Raised when the append-only Environment chain is invalid."""


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _texts(value: object, *, field_name: str, minimum: int = 1) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} requires at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _pairs(value: object, *, field_name: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(
        (
            _text(name, field_name=f"{field_name} name"),
            _text(version, field_name=f"{field_name} version"),
        )
        for name, version in value
    )
    names = tuple(name for name, _ in normalized)
    if len(names) != len(set(names)):
        raise ValueError(f"{field_name} names must be unique")
    return normalized


def _object(value: object, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    try:
        encoded = json.dumps(dict(value), sort_keys=True, allow_nan=False)
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"{field_name} must contain finite JSON") from error
    if not isinstance(decoded, dict):
        raise ValueError(f"{field_name} must encode an object")
    return decoded


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class CertifiedDecisionEnvironmentSnapshot:
    """Exact evidence view available to the CIO at one decision cutoff."""

    identifier: str
    decision_identifier: str
    context_identifier: str
    screening_publication_identifier: str
    as_of: datetime
    knowledge_cutoff: datetime
    published_at: datetime
    environment: Mapping[str, Any]
    evidence_identifiers: tuple[str, ...]
    source_versions: tuple[tuple[str, str], ...]
    model_versions: tuple[tuple[str, str], ...]
    code_version: str
    process_version: str
    schema_version: str = "certified-decision-environment.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "decision_identifier",
            "context_identifier",
            "screening_publication_identifier",
            "code_version",
            "process_version",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        for field_name in ("as_of", "knowledge_cutoff", "published_at"):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.knowledge_cutoff > self.as_of:
            raise ValueError("knowledge_cutoff cannot follow decision as_of")
        if self.published_at < self.as_of:
            raise ValueError("environment publication cannot predate the decision")
        object.__setattr__(
            self,
            "environment",
            _object(self.environment, field_name="environment"),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(
                self.evidence_identifiers,
                field_name="evidence_identifiers",
            ),
        )
        object.__setattr__(
            self,
            "source_versions",
            _pairs(self.source_versions, field_name="source_versions"),
        )
        object.__setattr__(
            self,
            "model_versions",
            _pairs(self.model_versions, field_name="model_versions"),
        )
        if self.schema_version != "certified-decision-environment.v1":
            raise ValueError("unsupported decision Environment schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "decision_identifier": self.decision_identifier,
            "context_identifier": self.context_identifier,
            "screening_publication_identifier": (
                self.screening_publication_identifier
            ),
            "as_of": self.as_of.isoformat(),
            "knowledge_cutoff": self.knowledge_cutoff.isoformat(),
            "published_at": self.published_at.isoformat(),
            "environment": dict(self.environment),
            "evidence_identifiers": list(self.evidence_identifiers),
            "source_versions": [list(item) for item in self.source_versions],
            "model_versions": [list(item) for item in self.model_versions],
            "code_version": self.code_version,
            "process_version": self.process_version,
            "decision_time_certified": True,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "CertifiedDecisionEnvironmentSnapshot":
        return cls(
            identifier=str(value["identifier"]),
            decision_identifier=str(value["decision_identifier"]),
            context_identifier=str(value["context_identifier"]),
            screening_publication_identifier=str(
                value["screening_publication_identifier"]
            ),
            as_of=datetime.fromisoformat(str(value["as_of"])),
            knowledge_cutoff=datetime.fromisoformat(
                str(value["knowledge_cutoff"])
            ),
            published_at=datetime.fromisoformat(str(value["published_at"])),
            environment=dict(value["environment"]),
            evidence_identifiers=tuple(
                str(item) for item in value["evidence_identifiers"]
            ),
            source_versions=tuple(
                (str(name), str(version))
                for name, version in value.get("source_versions", ())
            ),
            model_versions=tuple(
                (str(name), str(version))
                for name, version in value.get("model_versions", ())
            ),
            code_version=str(value["code_version"]),
            process_version=str(value["process_version"]),
            schema_version=str(
                value.get(
                    "schema_version",
                    "certified-decision-environment.v1",
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class SubsequentEnvironmentObservation:
    """Evidence available only after the decision cutoff."""

    identifier: str
    snapshot_identifier: str
    observed_at: datetime
    available_at: datetime
    category: str
    summary: str
    source_identifier: str
    evidence_identifier: str
    material: bool
    payload: Mapping[str, Any]
    schema_version: str = "subsequent-environment-observation.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "snapshot_identifier",
            "category",
            "summary",
            "source_identifier",
            "evidence_identifier",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.observed_at, field_name="observed_at")
        _aware(self.available_at, field_name="available_at")
        if self.available_at < self.observed_at:
            raise ValueError("available_at cannot predate observed_at")
        if not isinstance(self.material, bool):
            raise TypeError("material must be a bool")
        object.__setattr__(
            self,
            "payload",
            _object(self.payload, field_name="payload"),
        )
        if self.schema_version != "subsequent-environment-observation.v1":
            raise ValueError("unsupported subsequent Environment schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "snapshot_identifier": self.snapshot_identifier,
            "observed_at": self.observed_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "category": self.category,
            "summary": self.summary,
            "source_identifier": self.source_identifier,
            "evidence_identifier": self.evidence_identifier,
            "material": self.material,
            "payload": dict(self.payload),
            "decision_time_certified": False,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "SubsequentEnvironmentObservation":
        return cls(
            identifier=str(value["identifier"]),
            snapshot_identifier=str(value["snapshot_identifier"]),
            observed_at=datetime.fromisoformat(str(value["observed_at"])),
            available_at=datetime.fromisoformat(str(value["available_at"])),
            category=str(value["category"]),
            summary=str(value["summary"]),
            source_identifier=str(value["source_identifier"]),
            evidence_identifier=str(value["evidence_identifier"]),
            material=bool(value["material"]),
            payload=dict(value.get("payload", {})),
            schema_version=str(
                value.get(
                    "schema_version",
                    "subsequent-environment-observation.v1",
                )
            ),
        )


class SQLiteEnvironmentEvidenceStore:
    """Append-only decision snapshots and post-decision observations."""

    _TABLE = "canonical_environment_events"
    _GENESIS_HASH = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier TEXT NOT NULL UNIQUE,
                    snapshot_identifier TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS environment_snapshot_events
                ON {self._TABLE} (snapshot_identifier, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'environment evidence is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'environment evidence is append-only'); END;
                """
            )

    @classmethod
    def _hash(
        cls,
        *,
        sequence: int,
        identifier: str,
        snapshot_identifier: str,
        event_type: str,
        occurred_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        return hashlib.sha256(
            "|".join(
                (
                    str(sequence),
                    identifier,
                    snapshot_identifier,
                    event_type,
                    occurred_at,
                    payload_json,
                    previous_hash,
                )
            ).encode("utf-8")
        ).hexdigest()

    def _append(
        self,
        *,
        identifier: str,
        snapshot_identifier: str,
        event_type: str,
        occurred_at: datetime,
        payload: Mapping[str, Any],
    ) -> int:
        payload_json = _canonical_json(payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence, payload_json, event_type FROM {self._TABLE} "
                "WHERE identifier = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["payload_json"]) != payload_json
                    or str(existing["event_type"]) != event_type
                ):
                    raise EnvironmentEvidenceError(
                        "Environment identifier has conflicting content"
                    )
                return int(existing["sequence"])
            tail = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous_hash = (
                self._GENESIS_HASH
                if tail is None
                else str(tail["content_hash"])
            )
            occurred = occurred_at.isoformat()
            content_hash = self._hash(
                sequence=sequence,
                identifier=identifier,
                snapshot_identifier=snapshot_identifier,
                event_type=event_type,
                occurred_at=occurred,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    sequence, identifier, snapshot_identifier, event_type,
                    occurred_at, payload_json, previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    identifier,
                    snapshot_identifier,
                    event_type,
                    occurred,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def append_snapshot(
        self,
        snapshot: CertifiedDecisionEnvironmentSnapshot,
    ) -> int:
        if not isinstance(snapshot, CertifiedDecisionEnvironmentSnapshot):
            raise TypeError("snapshot must be CertifiedDecisionEnvironmentSnapshot")
        self.verify_integrity()
        return self._append(
            identifier=snapshot.identifier,
            snapshot_identifier=snapshot.identifier,
            event_type="decision_snapshot",
            occurred_at=snapshot.published_at,
            payload=snapshot.to_dict(),
        )

    def snapshot(
        self,
        identifier: str,
    ) -> CertifiedDecisionEnvironmentSnapshot | None:
        resolved = _text(identifier, field_name="identifier")
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE identifier = ? AND event_type = 'decision_snapshot'",
                (resolved,),
            ).fetchone()
        return (
            None
            if row is None
            else CertifiedDecisionEnvironmentSnapshot.from_dict(
                json.loads(str(row["payload_json"]))
            )
        )

    def append_observation(
        self,
        observation: SubsequentEnvironmentObservation,
    ) -> int:
        if not isinstance(observation, SubsequentEnvironmentObservation):
            raise TypeError(
                "observation must be SubsequentEnvironmentObservation"
            )
        snapshot = self.snapshot(observation.snapshot_identifier)
        if snapshot is None:
            raise EnvironmentEvidenceError(
                "subsequent observation requires an existing decision snapshot"
            )
        if observation.available_at <= snapshot.knowledge_cutoff:
            raise EnvironmentEvidenceError(
                "observation available at the decision cutoff belongs in the "
                "certified decision snapshot, not subsequent developments"
            )
        if observation.evidence_identifier in snapshot.evidence_identifiers:
            raise EnvironmentEvidenceError(
                "subsequent observation cannot reuse a decision-time evidence identifier"
            )
        self.verify_integrity()
        return self._append(
            identifier=observation.identifier,
            snapshot_identifier=observation.snapshot_identifier,
            event_type="subsequent_observation",
            occurred_at=observation.available_at,
            payload=observation.to_dict(),
        )

    def latest_snapshot(self) -> CertifiedDecisionEnvironmentSnapshot | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE event_type = 'decision_snapshot' "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        return (
            None
            if row is None
            else CertifiedDecisionEnvironmentSnapshot.from_dict(
                json.loads(str(row["payload_json"]))
            )
        )

    def observations(
        self,
        snapshot_identifier: str,
    ) -> tuple[SubsequentEnvironmentObservation, ...]:
        resolved = _text(
            snapshot_identifier,
            field_name="snapshot_identifier",
        )
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE snapshot_identifier = ? "
                "AND event_type = 'subsequent_observation' "
                "ORDER BY sequence",
                (resolved,),
            ).fetchall()
        return tuple(
            SubsequentEnvironmentObservation.from_dict(
                json.loads(str(row["payload_json"]))
            )
            for row in rows
        )

    def latest_view(self) -> dict[str, object] | None:
        snapshot = self.latest_snapshot()
        if snapshot is None:
            return None
        observations = self.observations(snapshot.identifier)
        return {
            "snapshot_identifier": snapshot.identifier,
            "decision_identifier": snapshot.decision_identifier,
            "context_identifier": snapshot.context_identifier,
            "screening_publication_identifier": (
                snapshot.screening_publication_identifier
            ),
            "as_of": snapshot.as_of.isoformat(),
            "knowledge_cutoff": snapshot.knowledge_cutoff.isoformat(),
            "published_at": snapshot.published_at.isoformat(),
            "environment": dict(snapshot.environment),
            "evidence_identifiers": list(snapshot.evidence_identifiers),
            "source_versions": dict(snapshot.source_versions),
            "model_versions": dict(snapshot.model_versions),
            "code_version": snapshot.code_version,
            "process_version": snapshot.process_version,
            "decision_time_certified": True,
            "subsequent_observations": [
                item.to_dict() for item in observations
            ],
            "subsequent_observation_count": len(observations),
            "schema_version": "canonical-environment-view.v1",
        }

    def verify_integrity(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous_hash = self._GENESIS_HASH
        for expected, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected:
                raise EnvironmentEvidenceIntegrityError(
                    "Environment sequence is not contiguous"
                )
            if str(row["previous_hash"]) != previous_hash:
                raise EnvironmentEvidenceIntegrityError(
                    "Environment previous hash is invalid"
                )
            expected_hash = self._hash(
                sequence=expected,
                identifier=str(row["identifier"]),
                snapshot_identifier=str(row["snapshot_identifier"]),
                event_type=str(row["event_type"]),
                occurred_at=str(row["occurred_at"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous_hash,
            )
            if str(row["content_hash"]) != expected_hash:
                raise EnvironmentEvidenceIntegrityError(
                    "Environment content hash is invalid"
                )
            previous_hash = expected_hash
        return True


__all__ = [
    "CertifiedDecisionEnvironmentSnapshot",
    "EnvironmentEvidenceError",
    "EnvironmentEvidenceIntegrityError",
    "SQLiteEnvironmentEvidenceStore",
    "SubsequentEnvironmentObservation",
]
