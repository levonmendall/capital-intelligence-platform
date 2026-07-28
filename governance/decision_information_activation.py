"""Append-only runtime activation for decision-information sources.

The source-controlled maximum-information manifest declares the source identities,
roles, independence groups, and domains the product is prepared to consume. Human
reviewed, expiring activation records supply deployment facts without mutating that
policy or storing credentials in source control.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from governance.decision_information_readiness import (
    DecisionInformationDomain,
    DecisionInformationSourceCapability,
    MaximumDecisionInformationManifest,
)


class DecisionInformationActivationError(RuntimeError):
    """Raised when source activation authority is invalid or unavailable."""


class DecisionInformationActivationIntegrityError(
    DecisionInformationActivationError
):
    """Raised when append-only source activation history is corrupted."""


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


def _boolean(value: object, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a bool")
    return value


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as error:
        raise ValueError("source activation must contain finite JSON") from error


def _content_hash(previous_hash: str | None, payload_json: str) -> str:
    return hashlib.sha256(
        ((previous_hash or "") + "\n" + payload_json).encode("utf-8")
    ).hexdigest()


_READINESS_FIELDS = (
    "usage_rights_approved",
    "storage_and_backup_approved",
    "derived_analytics_approved",
    "internal_display_approved",
    "paper_simulation_approved",
    "event_time_supported",
    "publication_time_supported",
    "availability_time_supported",
    "correction_history_supported",
    "historical_coverage_supported",
    "provenance_complete",
    "entity_mapping_supported",
    "geographic_mapping_supported",
    "reliability_policy_defined",
    "manipulation_controls_defined",
    "deduplication_supported",
    "service_level_defined",
)


@dataclass(frozen=True, slots=True)
class DecisionInformationSourceActivation:
    identifier: str
    source_identifier: str
    source_name: str
    enabled: bool
    approved_domains: tuple[DecisionInformationDomain, ...]
    authoritative_domains: tuple[DecisionInformationDomain, ...]
    usage_rights_approved: bool
    storage_and_backup_approved: bool
    derived_analytics_approved: bool
    internal_display_approved: bool
    paper_simulation_approved: bool
    event_time_supported: bool
    publication_time_supported: bool
    availability_time_supported: bool
    correction_history_supported: bool
    historical_coverage_supported: bool
    provenance_complete: bool
    entity_mapping_supported: bool
    geographic_mapping_supported: bool
    reliability_policy_defined: bool
    manipulation_controls_defined: bool
    deduplication_supported: bool
    service_level_defined: bool
    certification_identifier: str
    approved_by: str
    rationale: str
    approved_at: datetime
    effective_at: datetime
    expires_at: datetime
    evidence_identifiers: tuple[str, ...] = ()
    schema_version: str = "decision-information-source-activation.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "source_identifier",
            "source_name",
            "certification_identifier",
            "approved_by",
            "rationale",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _boolean(self.enabled, field_name="enabled")
        for field_name in _READINESS_FIELDS:
            _boolean(getattr(self, field_name), field_name=field_name)
        for field_name in ("approved_domains", "authoritative_domains"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, DecisionInformationDomain) for item in values
            ):
                raise TypeError(
                    f"{field_name} must contain DecisionInformationDomain values"
                )
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} cannot contain duplicates")
        if not self.approved_domains:
            raise ValueError("approved_domains must not be empty")
        if set(self.authoritative_domains) - set(self.approved_domains):
            raise ValueError(
                "authoritative_domains must be a subset of approved_domains"
            )
        approved_at = _aware(self.approved_at, field_name="approved_at")
        effective_at = _aware(self.effective_at, field_name="effective_at")
        expires_at = _aware(self.expires_at, field_name="expires_at")
        if approved_at > effective_at:
            raise ValueError("approved_at cannot follow effective_at")
        if effective_at >= expires_at:
            raise ValueError("effective_at must precede expires_at")
        if not isinstance(self.evidence_identifiers, tuple):
            raise TypeError("evidence_identifiers must be a tuple")
        evidence = tuple(
            _text(item, field_name="evidence_identifier")
            for item in self.evidence_identifiers
        )
        if len(evidence) != len(set(evidence)):
            raise ValueError("evidence_identifiers cannot contain duplicates")
        object.__setattr__(self, "evidence_identifiers", evidence)
        if self.enabled:
            missing = tuple(
                field_name
                for field_name in _READINESS_FIELDS
                if not getattr(self, field_name)
            )
            if missing:
                raise ValueError(
                    "enabled source activation is incomplete: " + ", ".join(missing)
                )

    def active_at(self, timestamp: datetime) -> bool:
        value = _aware(timestamp, field_name="timestamp")
        return self.effective_at <= value < self.expires_at

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "identifier": self.identifier,
            "source_identifier": self.source_identifier,
            "source_name": self.source_name,
            "enabled": self.enabled,
            "approved_domains": [item.value for item in self.approved_domains],
            "authoritative_domains": [
                item.value for item in self.authoritative_domains
            ],
            "certification_identifier": self.certification_identifier,
            "approved_by": self.approved_by,
            "rationale": self.rationale,
            "approved_at": self.approved_at.isoformat(),
            "effective_at": self.effective_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "evidence_identifiers": list(self.evidence_identifiers),
            "real_money_authorized": False,
        }
        payload.update(
            {field_name: getattr(self, field_name) for field_name in _READINESS_FIELDS}
        )
        return payload

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "DecisionInformationSourceActivation":
        values: dict[str, Any] = {
            "identifier": str(payload["identifier"]),
            "source_identifier": str(payload["source_identifier"]),
            "source_name": str(payload["source_name"]),
            "enabled": _boolean(payload["enabled"], field_name="enabled"),
            "approved_domains": tuple(
                DecisionInformationDomain(str(item))
                for item in payload["approved_domains"]
            ),
            "authoritative_domains": tuple(
                DecisionInformationDomain(str(item))
                for item in payload.get("authoritative_domains", ())
            ),
            "certification_identifier": str(payload["certification_identifier"]),
            "approved_by": str(payload["approved_by"]),
            "rationale": str(payload["rationale"]),
            "approved_at": datetime.fromisoformat(str(payload["approved_at"])),
            "effective_at": datetime.fromisoformat(str(payload["effective_at"])),
            "expires_at": datetime.fromisoformat(str(payload["expires_at"])),
            "evidence_identifiers": tuple(
                str(item) for item in payload.get("evidence_identifiers", ())
            ),
            "schema_version": str(
                payload.get(
                    "schema_version",
                    "decision-information-source-activation.v1",
                )
            ),
        }
        values.update(
            {
                field_name: _boolean(payload[field_name], field_name=field_name)
                for field_name in _READINESS_FIELDS
            }
        )
        return cls(**values)


class SQLiteDecisionInformationActivationStore:
    _TABLE = "decision_information_source_activations"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
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
                    identifier TEXT NOT NULL UNIQUE,
                    source_identifier TEXT NOT NULL,
                    effective_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT,
                    content_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS decision_information_activation_lookup
                    ON {self._TABLE}(source_identifier, effective_at, sequence);
                CREATE TRIGGER IF NOT EXISTS decision_information_activations_no_update
                    BEFORE UPDATE ON {self._TABLE}
                    BEGIN SELECT RAISE(ABORT, 'decision information activations are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS decision_information_activations_no_delete
                    BEFORE DELETE ON {self._TABLE}
                    BEGIN SELECT RAISE(ABORT, 'decision information activations are append-only'); END;
                """
            )

    def append(self, activation: DecisionInformationSourceActivation) -> int:
        if not isinstance(activation, DecisionInformationSourceActivation):
            raise TypeError(
                "activation must be DecisionInformationSourceActivation"
            )
        payload_json = _canonical_json(activation.to_dict())
        with self._connect() as connection:
            existing = connection.execute(
                f"SELECT sequence, payload_json FROM {self._TABLE} WHERE identifier = ?",
                (activation.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise DecisionInformationActivationIntegrityError(
                        "source activation identifier already exists with different content"
                    )
                return int(existing["sequence"])
            previous = connection.execute(
                f"SELECT content_hash FROM {self._TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = None if previous is None else str(previous["content_hash"])
            content_hash = _content_hash(previous_hash, payload_json)
            cursor = connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    identifier, source_identifier, effective_at, expires_at,
                    payload_json, previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    activation.identifier,
                    activation.source_identifier,
                    activation.effective_at.isoformat(),
                    activation.expires_at.isoformat(),
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
            return int(cursor.lastrowid)

    def activations(
        self, source_identifier: str | None = None
    ) -> tuple[DecisionInformationSourceActivation, ...]:
        with self._connect() as connection:
            if source_identifier is None:
                rows = connection.execute(
                    f"SELECT payload_json FROM {self._TABLE} ORDER BY sequence"
                ).fetchall()
            else:
                normalized = _text(
                    source_identifier, field_name="source_identifier"
                )
                rows = connection.execute(
                    f"""
                    SELECT payload_json FROM {self._TABLE}
                    WHERE source_identifier = ? ORDER BY sequence
                    """,
                    (normalized,),
                ).fetchall()
        return tuple(
            DecisionInformationSourceActivation.from_dict(
                json.loads(str(row["payload_json"]))
            )
            for row in rows
        )

    def active(
        self, source_identifier: str, *, evaluated_at: datetime
    ) -> DecisionInformationSourceActivation | None:
        timestamp = _aware(evaluated_at, field_name="evaluated_at")
        values = tuple(
            item
            for item in self.activations(source_identifier)
            if item.active_at(timestamp)
        )
        return None if not values else values[-1]

    def verify_integrity(self) -> None:
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT sequence, payload_json, previous_hash, content_hash
                FROM {self._TABLE} ORDER BY sequence
                """
            ).fetchall()
        previous_hash: str | None = None
        for expected_sequence, row in enumerate(rows, 1):
            if int(row["sequence"]) != expected_sequence:
                raise DecisionInformationActivationIntegrityError(
                    "source activation sequence is not contiguous"
                )
            stored_previous = row["previous_hash"]
            normalized_previous = (
                None if stored_previous is None else str(stored_previous)
            )
            if normalized_previous != previous_hash:
                raise DecisionInformationActivationIntegrityError(
                    "source activation previous hash is invalid"
                )
            expected_hash = _content_hash(previous_hash, str(row["payload_json"]))
            if str(row["content_hash"]) != expected_hash:
                raise DecisionInformationActivationIntegrityError(
                    "source activation content hash is invalid"
                )
            previous_hash = expected_hash


@dataclass(frozen=True, slots=True)
class DecisionInformationActivationOverlay:
    manifest: MaximumDecisionInformationManifest
    activation_identifiers: tuple[str, ...]
    inactive_source_identifiers: tuple[str, ...]


class DecisionInformationActivationAuthority:
    def __init__(self, store: SQLiteDecisionInformationActivationStore) -> None:
        if not isinstance(store, SQLiteDecisionInformationActivationStore):
            raise TypeError(
                "store must be SQLiteDecisionInformationActivationStore"
            )
        self.store = store

    def overlay(
        self,
        manifest: MaximumDecisionInformationManifest,
        *,
        evaluated_at: datetime,
    ) -> DecisionInformationActivationOverlay:
        if not isinstance(manifest, MaximumDecisionInformationManifest):
            raise TypeError("manifest must be MaximumDecisionInformationManifest")
        timestamp = _aware(evaluated_at, field_name="evaluated_at")
        self.store.verify_integrity()
        sources: list[DecisionInformationSourceCapability] = []
        identifiers: list[str] = []
        inactive: list[str] = []
        for template in manifest.sources:
            activation = self.store.active(
                template.identifier, evaluated_at=timestamp
            )
            if activation is None:
                sources.append(template)
                inactive.append(template.identifier)
                continue
            unsupported = set(activation.approved_domains) - set(template.domains)
            if unsupported:
                raise DecisionInformationActivationError(
                    f"activation {activation.identifier} approves undeclared domains "
                    f"for {template.identifier}: "
                    + ", ".join(sorted(item.value for item in unsupported))
                )
            unsupported_authority = set(activation.authoritative_domains) - set(
                template.authoritative_domains
            )
            if unsupported_authority:
                raise DecisionInformationActivationError(
                    f"activation {activation.identifier} expands undeclared "
                    f"authoritative domains for {template.identifier}: "
                    + ", ".join(
                        sorted(item.value for item in unsupported_authority)
                    )
                )
            replacements: dict[str, Any] = {
                "source_name": activation.source_name,
                "enabled": activation.enabled,
                "domains": activation.approved_domains,
                "authoritative_domains": activation.authoritative_domains,
                "certification_identifier": activation.certification_identifier,
            }
            replacements.update(
                {
                    field_name: getattr(activation, field_name)
                    for field_name in _READINESS_FIELDS
                }
            )
            sources.append(replace(template, **replacements))
            identifiers.append(activation.identifier)
        return DecisionInformationActivationOverlay(
            manifest=replace(manifest, sources=tuple(sources)),
            activation_identifiers=tuple(identifiers),
            inactive_source_identifiers=tuple(inactive),
        )


__all__ = [
    "DecisionInformationActivationAuthority",
    "DecisionInformationActivationError",
    "DecisionInformationActivationIntegrityError",
    "DecisionInformationActivationOverlay",
    "DecisionInformationSourceActivation",
    "SQLiteDecisionInformationActivationStore",
]
