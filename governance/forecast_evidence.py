"""Point-in-time forecast evidence with no independent decision authority."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Any, Mapping


class ForecastEvidenceError(RuntimeError):
    """Raised when a forecast cannot be used as governed supporting evidence."""


class ForecastEvidenceIntegrityError(ForecastEvidenceError):
    """Raised when the append-only forecast chain is invalid."""


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


def _probability(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return round(normalized, 12)


def _texts(value: object, *, field_name: str, minimum: int = 1) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} requires at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _versions(value: object, *, field_name: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(
        (
            _text(name, field_name=f"{field_name} name"),
            _text(version, field_name=f"{field_name} version"),
        )
        for name, version in value
    )
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    names = tuple(name for name, _ in normalized)
    if len(names) != len(set(names)):
        raise ValueError(f"{field_name} names must be unique")
    return normalized


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class ForecastScenario:
    name: str
    probability: float
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, field_name="name"))
        object.__setattr__(
            self,
            "probability",
            _probability(self.probability, field_name="probability"),
        )
        object.__setattr__(
            self,
            "description",
            _text(self.description, field_name="description"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "probability": self.probability,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class GovernedForecastEvidence:
    """One calibrated forecast that may support, but never issue, a decision."""

    identifier: str
    target: str
    as_of: datetime
    knowledge_cutoff: datetime
    horizon_end: datetime
    generated_at: datetime
    scenarios: tuple[ForecastScenario, ...]
    confidence: float
    calibration_method: str
    calibration_sample_size: int
    historical_accuracy: float
    model_versions: tuple[tuple[str, str], ...]
    data_versions: tuple[tuple[str, str], ...]
    evidence_identifiers: tuple[str, ...]
    originating_fact_identifiers: tuple[str, ...]
    limitations: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    supporting_only: bool = True
    schema_version: str = "governed-forecast-evidence.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "target",
            "calibration_method",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "as_of",
            "knowledge_cutoff",
            "horizon_end",
            "generated_at",
        ):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.knowledge_cutoff < self.as_of:
            raise ValueError("knowledge_cutoff cannot predate forecast as_of")
        if self.generated_at < self.knowledge_cutoff:
            raise ValueError("generated_at cannot predate the knowledge cutoff")
        if self.horizon_end <= self.as_of:
            raise ValueError("forecast horizon must end after as_of")
        if not isinstance(self.scenarios, tuple) or not self.scenarios or not all(
            isinstance(item, ForecastScenario) for item in self.scenarios
        ):
            raise TypeError("scenarios must contain ForecastScenario values")
        names = tuple(item.name for item in self.scenarios)
        if len(names) != len(set(names)):
            raise ValueError("forecast scenario names must be unique")
        if abs(sum(item.probability for item in self.scenarios) - 1.0) > 1e-9:
            raise ValueError("forecast scenario probabilities must sum to 1")
        object.__setattr__(
            self,
            "confidence",
            _probability(self.confidence, field_name="confidence"),
        )
        if isinstance(self.calibration_sample_size, bool) or not isinstance(
            self.calibration_sample_size,
            int,
        ):
            raise TypeError("calibration_sample_size must be an integer")
        if self.calibration_sample_size < 1:
            raise ValueError("calibration_sample_size must be positive")
        object.__setattr__(
            self,
            "historical_accuracy",
            _probability(
                self.historical_accuracy,
                field_name="historical_accuracy",
            ),
        )
        object.__setattr__(
            self,
            "model_versions",
            _versions(self.model_versions, field_name="model_versions"),
        )
        object.__setattr__(
            self,
            "data_versions",
            _versions(self.data_versions, field_name="data_versions"),
        )
        for field_name in (
            "evidence_identifiers",
            "originating_fact_identifiers",
            "limitations",
            "invalidation_conditions",
        ):
            object.__setattr__(
                self,
                field_name,
                _texts(getattr(self, field_name), field_name=field_name),
            )
        if self.supporting_only is not True:
            raise ValueError("forecast evidence must be supporting-only")
        if self.schema_version != "governed-forecast-evidence.v1":
            raise ValueError("unsupported forecast evidence schema")

    @property
    def horizon_seconds(self) -> float:
        return (self.horizon_end - self.as_of).total_seconds()

    def require_usable(
        self,
        *,
        decision_timestamp: datetime,
        knowledge_cutoff: datetime,
    ) -> None:
        decision = _aware(
            decision_timestamp,
            field_name="decision_timestamp",
        )
        cutoff = _aware(knowledge_cutoff, field_name="knowledge_cutoff")
        if self.generated_at > decision:
            raise ForecastEvidenceError(
                "forecast was generated after the decision timestamp"
            )
        if self.knowledge_cutoff > cutoff:
            raise ForecastEvidenceError(
                "forecast uses evidence after the decision knowledge cutoff"
            )
        if self.as_of > decision:
            raise ForecastEvidenceError("forecast as_of follows the decision")
        if not self.supporting_only:
            raise ForecastEvidenceError(
                "forecast cannot be used as an independent decision authority"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "target": self.target,
            "as_of": self.as_of.isoformat(),
            "knowledge_cutoff": self.knowledge_cutoff.isoformat(),
            "horizon_end": self.horizon_end.isoformat(),
            "horizon_seconds": self.horizon_seconds,
            "generated_at": self.generated_at.isoformat(),
            "scenarios": [item.to_dict() for item in self.scenarios],
            "confidence": self.confidence,
            "calibration_method": self.calibration_method,
            "calibration_sample_size": self.calibration_sample_size,
            "historical_accuracy": self.historical_accuracy,
            "model_versions": [list(item) for item in self.model_versions],
            "data_versions": [list(item) for item in self.data_versions],
            "evidence_identifiers": list(self.evidence_identifiers),
            "originating_fact_identifiers": list(
                self.originating_fact_identifiers
            ),
            "limitations": list(self.limitations),
            "invalidation_conditions": list(self.invalidation_conditions),
            "supporting_only": self.supporting_only,
            "independent_decision_authority": False,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GovernedForecastEvidence":
        return cls(
            identifier=str(value["identifier"]),
            target=str(value["target"]),
            as_of=datetime.fromisoformat(str(value["as_of"])),
            knowledge_cutoff=datetime.fromisoformat(
                str(value["knowledge_cutoff"])
            ),
            horizon_end=datetime.fromisoformat(str(value["horizon_end"])),
            generated_at=datetime.fromisoformat(str(value["generated_at"])),
            scenarios=tuple(
                ForecastScenario(
                    name=str(item["name"]),
                    probability=float(item["probability"]),
                    description=str(item["description"]),
                )
                for item in value["scenarios"]
            ),
            confidence=float(value["confidence"]),
            calibration_method=str(value["calibration_method"]),
            calibration_sample_size=int(value["calibration_sample_size"]),
            historical_accuracy=float(value["historical_accuracy"]),
            model_versions=tuple(
                (str(name), str(version))
                for name, version in value["model_versions"]
            ),
            data_versions=tuple(
                (str(name), str(version))
                for name, version in value["data_versions"]
            ),
            evidence_identifiers=tuple(
                str(item) for item in value["evidence_identifiers"]
            ),
            originating_fact_identifiers=tuple(
                str(item) for item in value["originating_fact_identifiers"]
            ),
            limitations=tuple(str(item) for item in value["limitations"]),
            invalidation_conditions=tuple(
                str(item) for item in value["invalidation_conditions"]
            ),
            supporting_only=bool(value.get("supporting_only", True)),
            schema_version=str(
                value.get("schema_version", "governed-forecast-evidence.v1")
            ),
        )


class SQLiteForecastEvidenceStore:
    """Append-only SHA-256 authority for governed forecast evidence."""

    _TABLE = "governed_forecast_evidence"
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
                    target TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    knowledge_cutoff TEXT NOT NULL,
                    horizon_end TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS forecast_target_cutoff
                ON {self._TABLE} (target, knowledge_cutoff, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'forecast evidence is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'forecast evidence is append-only'); END;
                """
            )

    @classmethod
    def _hash(
        cls,
        *,
        sequence: int,
        identifier: str,
        target: str,
        as_of: str,
        knowledge_cutoff: str,
        horizon_end: str,
        generated_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        raw = "|".join(
            (
                str(sequence),
                identifier,
                target,
                as_of,
                knowledge_cutoff,
                horizon_end,
                generated_at,
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def append(self, forecast: GovernedForecastEvidence) -> int:
        if not isinstance(forecast, GovernedForecastEvidence):
            raise TypeError("forecast must be GovernedForecastEvidence")
        self.verify_integrity()
        payload_json = _canonical_json(forecast.to_dict())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence, payload_json FROM {self._TABLE} "
                "WHERE identifier = ?",
                (forecast.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise ForecastEvidenceError(
                        "forecast identifier already exists with different content"
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
            values = (
                sequence,
                forecast.identifier,
                forecast.target,
                forecast.as_of.isoformat(),
                forecast.knowledge_cutoff.isoformat(),
                forecast.horizon_end.isoformat(),
                forecast.generated_at.isoformat(),
                payload_json,
                previous_hash,
            )
            content_hash = self._hash(
                sequence=sequence,
                identifier=forecast.identifier,
                target=forecast.target,
                as_of=forecast.as_of.isoformat(),
                knowledge_cutoff=forecast.knowledge_cutoff.isoformat(),
                horizon_end=forecast.horizon_end.isoformat(),
                generated_at=forecast.generated_at.isoformat(),
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    sequence, identifier, target, as_of, knowledge_cutoff,
                    horizon_end, generated_at, payload_json, previous_hash,
                    content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values + (content_hash,),
            )
        return sequence

    def get(self, identifier: str) -> GovernedForecastEvidence | None:
        resolved = _text(identifier, field_name="identifier")
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} WHERE identifier = ?",
                (resolved,),
            ).fetchone()
        return (
            None
            if row is None
            else GovernedForecastEvidence.from_dict(
                json.loads(str(row["payload_json"]))
            )
        )

    def latest_for_target(
        self,
        target: str,
        *,
        knowledge_cutoff: datetime,
    ) -> GovernedForecastEvidence | None:
        resolved = _text(target, field_name="target")
        cutoff = _aware(knowledge_cutoff, field_name="knowledge_cutoff")
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE target = ? AND generated_at <= ? AND knowledge_cutoff <= ? "
                "ORDER BY sequence DESC LIMIT 1",
                (resolved, cutoff.isoformat(), cutoff.isoformat()),
            ).fetchone()
        return (
            None
            if row is None
            else GovernedForecastEvidence.from_dict(
                json.loads(str(row["payload_json"]))
            )
        )

    def verify_integrity(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous_hash = self._GENESIS_HASH
        for expected, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected:
                raise ForecastEvidenceIntegrityError(
                    "forecast evidence sequence is not contiguous"
                )
            if str(row["previous_hash"]) != previous_hash:
                raise ForecastEvidenceIntegrityError(
                    "forecast evidence previous hash is invalid"
                )
            expected_hash = self._hash(
                sequence=expected,
                identifier=str(row["identifier"]),
                target=str(row["target"]),
                as_of=str(row["as_of"]),
                knowledge_cutoff=str(row["knowledge_cutoff"]),
                horizon_end=str(row["horizon_end"]),
                generated_at=str(row["generated_at"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous_hash,
            )
            if str(row["content_hash"]) != expected_hash:
                raise ForecastEvidenceIntegrityError(
                    "forecast evidence content hash is invalid"
                )
            previous_hash = expected_hash
        return True


__all__ = [
    "ForecastEvidenceError",
    "ForecastEvidenceIntegrityError",
    "ForecastScenario",
    "GovernedForecastEvidence",
    "SQLiteForecastEvidenceStore",
]
