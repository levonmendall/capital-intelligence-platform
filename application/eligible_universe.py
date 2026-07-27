"""Certified eligible-universe publication authority.

The production context adapter consumes the latest publication for the decision
timestamp. It never rebuilds eligibility or substitutes an older publication
when the newest record is unavailable, stale, or uncertified.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class EligibleUniverseError(RuntimeError):
    """Raised when a certified eligible-universe authority is unusable."""


class EligibleUniverseCertificationState(str, Enum):
    APPROVED = "approved"
    CONDITIONAL = "conditional"
    REJECTED = "rejected"
    EXPIRED = "expired"


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


def _texts(
    value: object,
    *,
    field_name: str,
    minimum: int = 0,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} must contain at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _versions(
    value: object,
    *,
    field_name: str,
) -> tuple[tuple[str, str], ...]:
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


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("eligible-universe payload must be finite JSON") from error


@dataclass(frozen=True, slots=True)
class CertifiedEligibleUniversePublication:
    """One immutable, certified publication of the eligible investment universe."""

    identifier: str
    published_at: datetime
    as_of: datetime
    knowledge_cutoff: datetime
    security_master_catalog_identifier: str
    security_master_snapshot_identifier: str
    policy_version: str
    certification_identifier: str
    certification_state: EligibleUniverseCertificationState
    certification_expires_at: datetime
    eligible_instrument_identifiers: tuple[str, ...]
    source_versions: tuple[tuple[str, str], ...]
    model_versions: tuple[tuple[str, str], ...]
    schema_version: str = "certified-eligible-universe-publication.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "security_master_catalog_identifier",
            "security_master_snapshot_identifier",
            "policy_version",
            "certification_identifier",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "published_at",
            "as_of",
            "knowledge_cutoff",
            "certification_expires_at",
        ):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.knowledge_cutoff > self.as_of:
            raise ValueError(
                "eligible-universe knowledge_cutoff cannot follow the decision timestamp"
            )
        if not isinstance(
            self.certification_state,
            EligibleUniverseCertificationState,
        ):
            raise TypeError(
                "certification_state must be an EligibleUniverseCertificationState"
            )
        object.__setattr__(
            self,
            "eligible_instrument_identifiers",
            _texts(
                self.eligible_instrument_identifiers,
                field_name="eligible_instrument_identifiers",
                minimum=1,
            ),
        )
        object.__setattr__(
            self,
            "source_versions",
            _versions(self.source_versions, field_name="source_versions"),
        )
        object.__setattr__(
            self,
            "model_versions",
            _versions(self.model_versions, field_name="model_versions"),
        )

    def require_usable(self, *, decision_timestamp: datetime) -> None:
        decision_time = _aware(
            decision_timestamp,
            field_name="decision_timestamp",
        )
        if self.as_of != decision_time:
            raise EligibleUniverseError(
                "eligible-universe publication does not match the decision timestamp"
            )
        if self.knowledge_cutoff > decision_time:
            raise EligibleUniverseError(
                "eligible-universe data cutoff follows the decision timestamp"
            )
        if self.published_at > decision_time:
            raise EligibleUniverseError(
                "eligible-universe publication was unavailable at the decision timestamp"
            )
        if (
            self.certification_state
            is not EligibleUniverseCertificationState.APPROVED
        ):
            raise EligibleUniverseError(
                f"eligible-universe certification {self.certification_identifier} "
                f"is {self.certification_state.value}, not approved"
            )
        if self.certification_expires_at < decision_time:
            raise EligibleUniverseError(
                f"eligible-universe certification {self.certification_identifier} "
                "is expired"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "published_at": self.published_at.isoformat(),
            "as_of": self.as_of.isoformat(),
            "knowledge_cutoff": self.knowledge_cutoff.isoformat(),
            "security_master_catalog_identifier": (
                self.security_master_catalog_identifier
            ),
            "security_master_snapshot_identifier": (
                self.security_master_snapshot_identifier
            ),
            "policy_version": self.policy_version,
            "certification_identifier": self.certification_identifier,
            "certification_state": self.certification_state.value,
            "certification_expires_at": self.certification_expires_at.isoformat(),
            "eligible_instrument_identifiers": list(
                self.eligible_instrument_identifiers
            ),
            "source_versions": [list(item) for item in self.source_versions],
            "model_versions": [list(item) for item in self.model_versions],
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "CertifiedEligibleUniversePublication":
        return cls(
            identifier=str(payload["identifier"]),
            published_at=datetime.fromisoformat(str(payload["published_at"])),
            as_of=datetime.fromisoformat(str(payload["as_of"])),
            knowledge_cutoff=datetime.fromisoformat(
                str(payload["knowledge_cutoff"])
            ),
            security_master_catalog_identifier=str(
                payload["security_master_catalog_identifier"]
            ),
            security_master_snapshot_identifier=str(
                payload["security_master_snapshot_identifier"]
            ),
            policy_version=str(payload["policy_version"]),
            certification_identifier=str(payload["certification_identifier"]),
            certification_state=EligibleUniverseCertificationState(
                str(payload["certification_state"])
            ),
            certification_expires_at=datetime.fromisoformat(
                str(payload["certification_expires_at"])
            ),
            eligible_instrument_identifiers=tuple(
                str(item)
                for item in payload["eligible_instrument_identifiers"]
            ),
            source_versions=tuple(
                (str(name), str(version))
                for name, version in payload.get("source_versions", ())
            ),
            model_versions=tuple(
                (str(name), str(version))
                for name, version in payload.get("model_versions", ())
            ),
            schema_version=str(
                payload.get(
                    "schema_version",
                    "certified-eligible-universe-publication.v1",
                )
            ),
        )


class SQLiteCertifiedEligibleUniverseStore:
    """Append-only, hash-chained eligible-universe publication authority."""

    _TABLE = "certified_eligible_universe_publications"
    _GENESIS_HASH = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    as_of TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS eligible_universe_as_of_sequence
                ON {self._TABLE} (as_of, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'eligible-universe publications are append-only'
                    );
                END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'eligible-universe publications are append-only'
                    );
                END;
                """
            )

    @staticmethod
    def _hash(
        *,
        sequence: int,
        event_identifier: str,
        as_of: str,
        published_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        raw = "|".join(
            (
                str(sequence),
                event_identifier,
                as_of,
                published_at,
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def append(self, publication: CertifiedEligibleUniversePublication) -> int:
        if not isinstance(publication, CertifiedEligibleUniversePublication):
            raise TypeError(
                "publication must be CertifiedEligibleUniversePublication"
            )
        self.verify_integrity()
        payload_json = _canonical_json(publication.to_dict())
        as_of = publication.as_of.isoformat()
        published_at = publication.published_at.isoformat()
        with self._connect() as connection:
            existing = connection.execute(
                f"SELECT sequence, payload_json FROM {self._TABLE} "
                "WHERE event_identifier = ?",
                (publication.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise ValueError(
                        "eligible-universe publication identifier already exists "
                        "with different content"
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
            content_hash = self._hash(
                sequence=sequence,
                event_identifier=publication.identifier,
                as_of=as_of,
                published_at=published_at,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    sequence, event_identifier, as_of, published_at,
                    payload_json, previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    publication.identifier,
                    as_of,
                    published_at,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def publication(
        self,
        identifier: str,
    ) -> CertifiedEligibleUniversePublication | None:
        resolved = _text(identifier, field_name="identifier")
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE event_identifier = ?",
                (resolved,),
            ).fetchone()
        if row is None:
            return None
        return CertifiedEligibleUniversePublication.from_dict(
            json.loads(str(row["payload_json"]))
        )

    def latest_for_decision(
        self,
        *,
        decision_timestamp: datetime,
    ) -> CertifiedEligibleUniversePublication:
        decision_time = _aware(
            decision_timestamp,
            field_name="decision_timestamp",
        )
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE as_of = ? ORDER BY sequence",
                (decision_time.isoformat(),),
            ).fetchall()
        if not rows:
            raise EligibleUniverseError(
                "certified eligible-universe publication is unavailable "
                "for the decision timestamp"
            )
        latest = CertifiedEligibleUniversePublication.from_dict(
            json.loads(str(rows[-1]["payload_json"]))
        )
        latest.require_usable(decision_timestamp=decision_time)
        return latest

    def verify_integrity(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous_hash = self._GENESIS_HASH
        for expected_sequence, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected_sequence:
                raise EligibleUniverseError(
                    "eligible-universe event sequence is not contiguous"
                )
            if str(row["previous_hash"]) != previous_hash:
                raise EligibleUniverseError(
                    "eligible-universe previous hash is invalid"
                )
            expected_hash = self._hash(
                sequence=expected_sequence,
                event_identifier=str(row["event_identifier"]),
                as_of=str(row["as_of"]),
                published_at=str(row["published_at"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous_hash,
            )
            if str(row["content_hash"]) != expected_hash:
                raise EligibleUniverseError(
                    "eligible-universe content hash is invalid"
                )
            previous_hash = expected_hash
        return True


__all__ = [
    "CertifiedEligibleUniversePublication",
    "EligibleUniverseCertificationState",
    "EligibleUniverseError",
    "SQLiteCertifiedEligibleUniverseStore",
]
