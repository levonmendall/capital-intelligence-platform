"""Append-only runtime activation authority for external data providers.

The version-controlled data-readiness manifest defines the providers and domains the
product is prepared to use.  It deliberately ships with commercial capabilities
turned off.  This module supplies the missing operational authority: a human-approved,
expiring, hash-chained activation record can enable one configured provider without
editing source-controlled policy or placing secrets in the repository.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from governance.data_readiness_core import DataDomain, ProviderDataCapability
from governance.data_readiness_scope import AllMarketsDataManifest


class ProviderActivationError(RuntimeError):
    """Raised when provider activation authority is unavailable or invalid."""


class ProviderActivationIntegrityError(ProviderActivationError):
    """Raised when append-only activation history fails integrity verification."""


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
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("provider activation must contain finite JSON") from error


def _content_hash(previous_hash: str | None, payload_json: str) -> str:
    material = ((previous_hash or "") + "\n" + payload_json).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


@dataclass(frozen=True, slots=True)
class ProviderActivation:
    """One immutable human approval of provider operating capabilities."""

    identifier: str
    provider_identifier: str
    provider_name: str
    enabled: bool
    approved_domains: tuple[DataDomain, ...]
    authoritative_domains: tuple[DataDomain, ...]
    usage_rights_approved: bool
    point_in_time_supported: bool
    historical_coverage_supported: bool
    provenance_complete: bool
    service_level_defined: bool
    storage_and_backup_approved: bool
    derived_analytics_approved: bool
    paper_simulation_approved: bool
    certification_identifier: str
    approved_by: str
    rationale: str
    approved_at: datetime
    effective_at: datetime
    expires_at: datetime
    source_identifiers: tuple[str, ...] = ()
    schema_version: str = "provider-activation.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "provider_identifier",
            "provider_name",
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
        for field_name in (
            "enabled",
            "usage_rights_approved",
            "point_in_time_supported",
            "historical_coverage_supported",
            "provenance_complete",
            "service_level_defined",
            "storage_and_backup_approved",
            "derived_analytics_approved",
            "paper_simulation_approved",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")
        for field_name in ("approved_domains", "authoritative_domains"):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or not all(
                isinstance(item, DataDomain) for item in value
            ):
                raise TypeError(f"{field_name} must contain DataDomain values")
            if len(value) != len(set(value)):
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
        if not isinstance(self.source_identifiers, tuple):
            raise TypeError("source_identifiers must be a tuple")
        normalized_sources = tuple(
            _text(item, field_name="source_identifier")
            for item in self.source_identifiers
        )
        if len(normalized_sources) != len(set(normalized_sources)):
            raise ValueError("source_identifiers cannot contain duplicates")
        object.__setattr__(self, "source_identifiers", normalized_sources)
        if self.enabled:
            required = {
                "usage_rights_approved": self.usage_rights_approved,
                "point_in_time_supported": self.point_in_time_supported,
                "historical_coverage_supported": self.historical_coverage_supported,
                "provenance_complete": self.provenance_complete,
                "service_level_defined": self.service_level_defined,
                "storage_and_backup_approved": self.storage_and_backup_approved,
                "derived_analytics_approved": self.derived_analytics_approved,
                "paper_simulation_approved": self.paper_simulation_approved,
            }
            missing = tuple(name for name, value in required.items() if not value)
            if missing:
                raise ValueError(
                    "enabled provider activation is incomplete: " + ", ".join(missing)
                )

    def active_at(self, timestamp: datetime) -> bool:
        value = _aware(timestamp, field_name="timestamp")
        return self.effective_at <= value < self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identifier": self.identifier,
            "provider_identifier": self.provider_identifier,
            "provider_name": self.provider_name,
            "enabled": self.enabled,
            "approved_domains": [item.value for item in self.approved_domains],
            "authoritative_domains": [
                item.value for item in self.authoritative_domains
            ],
            "usage_rights_approved": self.usage_rights_approved,
            "point_in_time_supported": self.point_in_time_supported,
            "historical_coverage_supported": self.historical_coverage_supported,
            "provenance_complete": self.provenance_complete,
            "service_level_defined": self.service_level_defined,
            "storage_and_backup_approved": self.storage_and_backup_approved,
            "derived_analytics_approved": self.derived_analytics_approved,
            "paper_simulation_approved": self.paper_simulation_approved,
            "certification_identifier": self.certification_identifier,
            "approved_by": self.approved_by,
            "rationale": self.rationale,
            "approved_at": self.approved_at.isoformat(),
            "effective_at": self.effective_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "source_identifiers": list(self.source_identifiers),
            "real_money_authorized": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProviderActivation":
        return cls(
            identifier=str(payload["identifier"]),
            provider_identifier=str(payload["provider_identifier"]),
            provider_name=str(payload["provider_name"]),
            enabled=_boolean(payload["enabled"], field_name="enabled"),
            approved_domains=tuple(
                DataDomain(str(item)) for item in payload["approved_domains"]
            ),
            authoritative_domains=tuple(
                DataDomain(str(item))
                for item in payload.get("authoritative_domains", ())
            ),
            usage_rights_approved=_boolean(payload["usage_rights_approved"], field_name="usage_rights_approved"),
            point_in_time_supported=_boolean(payload["point_in_time_supported"], field_name="point_in_time_supported"),
            historical_coverage_supported=_boolean(
                payload["historical_coverage_supported"],
                field_name="historical_coverage_supported",
            ),
            provenance_complete=_boolean(payload["provenance_complete"], field_name="provenance_complete"),
            service_level_defined=_boolean(payload["service_level_defined"], field_name="service_level_defined"),
            storage_and_backup_approved=_boolean(
                payload["storage_and_backup_approved"],
                field_name="storage_and_backup_approved",
            ),
            derived_analytics_approved=_boolean(
                payload["derived_analytics_approved"],
                field_name="derived_analytics_approved",
            ),
            paper_simulation_approved=_boolean(payload["paper_simulation_approved"], field_name="paper_simulation_approved"),
            certification_identifier=str(payload["certification_identifier"]),
            approved_by=str(payload["approved_by"]),
            rationale=str(payload["rationale"]),
            approved_at=datetime.fromisoformat(
                str(payload["approved_at"]).replace("Z", "+00:00")
            ),
            effective_at=datetime.fromisoformat(
                str(payload["effective_at"]).replace("Z", "+00:00")
            ),
            expires_at=datetime.fromisoformat(
                str(payload["expires_at"]).replace("Z", "+00:00")
            ),
            source_identifiers=tuple(
                str(item) for item in payload.get("source_identifiers", ())
            ),
            schema_version=str(
                payload.get("schema_version", "provider-activation.v1")
            ),
        )


class SQLiteProviderActivationStore:
    """Append-only, hash-chained provider activation registry."""

    _TABLE = "provider_activations"

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
                    provider_identifier TEXT NOT NULL,
                    effective_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT,
                    content_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS provider_activation_lookup
                    ON {self._TABLE}(provider_identifier, effective_at, sequence);
                CREATE TRIGGER IF NOT EXISTS provider_activations_no_update
                    BEFORE UPDATE ON {self._TABLE}
                    BEGIN SELECT RAISE(ABORT, 'provider activations are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS provider_activations_no_delete
                    BEFORE DELETE ON {self._TABLE}
                    BEGIN SELECT RAISE(ABORT, 'provider activations are append-only'); END;
                """
            )

    def append(self, activation: ProviderActivation) -> int:
        if not isinstance(activation, ProviderActivation):
            raise TypeError("activation must be ProviderActivation")
        payload_json = _canonical_json(activation.to_dict())
        with self._connect() as connection:
            existing = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} WHERE identifier = ?",
                (activation.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise ProviderActivationIntegrityError(
                        "provider activation identifier already exists with different content"
                    )
                sequence = connection.execute(
                    f"SELECT sequence FROM {self._TABLE} WHERE identifier = ?",
                    (activation.identifier,),
                ).fetchone()
                return int(sequence["sequence"])
            previous = connection.execute(
                f"SELECT content_hash FROM {self._TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = None if previous is None else str(previous["content_hash"])
            content_hash = _content_hash(previous_hash, payload_json)
            cursor = connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    identifier, provider_identifier, effective_at, expires_at,
                    payload_json, previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    activation.identifier,
                    activation.provider_identifier,
                    activation.effective_at.isoformat(),
                    activation.expires_at.isoformat(),
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
            return int(cursor.lastrowid)

    def activations(
        self, provider_identifier: str | None = None
    ) -> tuple[ProviderActivation, ...]:
        with self._connect() as connection:
            if provider_identifier is None:
                rows = connection.execute(
                    f"SELECT payload_json FROM {self._TABLE} ORDER BY sequence"
                ).fetchall()
            else:
                identifier = _text(
                    provider_identifier, field_name="provider_identifier"
                )
                rows = connection.execute(
                    f"""
                    SELECT payload_json FROM {self._TABLE}
                    WHERE provider_identifier = ? ORDER BY sequence
                    """,
                    (identifier,),
                ).fetchall()
        return tuple(
            ProviderActivation.from_dict(json.loads(str(row["payload_json"])))
            for row in rows
        )

    def active(
        self, provider_identifier: str, *, evaluated_at: datetime
    ) -> ProviderActivation | None:
        timestamp = _aware(evaluated_at, field_name="evaluated_at")
        values = tuple(
            item
            for item in self.activations(provider_identifier)
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
                raise ProviderActivationIntegrityError(
                    "provider activation sequence is not contiguous"
                )
            stored_previous = row["previous_hash"]
            normalized_previous = None if stored_previous is None else str(stored_previous)
            if normalized_previous != previous_hash:
                raise ProviderActivationIntegrityError(
                    "provider activation previous hash is invalid"
                )
            expected_hash = _content_hash(previous_hash, str(row["payload_json"]))
            if str(row["content_hash"]) != expected_hash:
                raise ProviderActivationIntegrityError(
                    "provider activation content hash is invalid"
                )
            previous_hash = expected_hash


@dataclass(frozen=True, slots=True)
class ProviderActivationOverlay:
    manifest: AllMarketsDataManifest
    activation_identifiers: tuple[str, ...]
    inactive_provider_identifiers: tuple[str, ...]


class ProviderActivationAuthority:
    """Overlay active runtime approvals onto source-controlled provider templates."""

    def __init__(self, store: SQLiteProviderActivationStore) -> None:
        if not isinstance(store, SQLiteProviderActivationStore):
            raise TypeError("store must be SQLiteProviderActivationStore")
        self.store = store

    def overlay(
        self, manifest: AllMarketsDataManifest, *, evaluated_at: datetime
    ) -> ProviderActivationOverlay:
        if not isinstance(manifest, AllMarketsDataManifest):
            raise TypeError("manifest must be AllMarketsDataManifest")
        timestamp = _aware(evaluated_at, field_name="evaluated_at")
        self.store.verify_integrity()
        providers: list[ProviderDataCapability] = []
        identifiers: list[str] = []
        inactive: list[str] = []
        for template in manifest.providers:
            activation = self.store.active(
                template.identifier, evaluated_at=timestamp
            )
            if activation is None:
                providers.append(template)
                inactive.append(template.identifier)
                continue
            unsupported = set(activation.approved_domains) - set(template.domains)
            if unsupported:
                raise ProviderActivationError(
                    f"activation {activation.identifier} approves undeclared domains "
                    f"for {template.identifier}: "
                    + ", ".join(sorted(item.value for item in unsupported))
                )
            unsupported_authority = set(activation.authoritative_domains) - set(
                template.authoritative_domains
            )
            if unsupported_authority:
                raise ProviderActivationError(
                    f"activation {activation.identifier} expands undeclared authoritative "
                    f"domains for {template.identifier}: "
                    + ", ".join(
                        sorted(item.value for item in unsupported_authority)
                    )
                )
            providers.append(
                replace(
                    template,
                    provider_name=activation.provider_name,
                    enabled=activation.enabled,
                    domains=activation.approved_domains,
                    authoritative_domains=activation.authoritative_domains,
                    usage_rights_approved=activation.usage_rights_approved,
                    point_in_time_supported=activation.point_in_time_supported,
                    historical_coverage_supported=(
                        activation.historical_coverage_supported
                    ),
                    provenance_complete=activation.provenance_complete,
                    service_level_defined=activation.service_level_defined,
                    storage_and_backup_approved=(
                        activation.storage_and_backup_approved
                    ),
                    derived_analytics_approved=(
                        activation.derived_analytics_approved
                    ),
                    paper_simulation_approved=(
                        activation.paper_simulation_approved
                    ),
                    certification_identifier=(
                        activation.certification_identifier
                    ),
                )
            )
            identifiers.append(activation.identifier)
        return ProviderActivationOverlay(
            manifest=replace(manifest, providers=tuple(providers)),
            activation_identifiers=tuple(identifiers),
            inactive_provider_identifiers=tuple(inactive),
        )


__all__ = [
    "ProviderActivation",
    "ProviderActivationAuthority",
    "ProviderActivationError",
    "ProviderActivationIntegrityError",
    "ProviderActivationOverlay",
    "SQLiteProviderActivationStore",
]
