"""Append-only SQLite persistence for versioned temporal security masters."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data.security import (
    AssetClass,
    IdentifierScheme,
    Instrument,
    InstrumentIdentifier,
    InstrumentType,
    Issuer,
    TradingCalendar,
)
from data.security_master import (
    IdentifierAssignment,
    InstrumentRecord,
    IssuerRecord,
    ListingRecord,
    ListingStatus,
    PointInTimeSecurityMasterSnapshot,
    SecurityEntityType,
    SecurityMasterAction,
    SecurityMasterActionType,
    SecurityMasterCatalog,
    SecurityMasterCoverage,
)


class SecurityMasterIntegrityError(RuntimeError):
    """Raised when the immutable catalog chain cannot be verified."""


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _canonical_json(value: dict[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("security-master payload must be finite JSON") from error


@dataclass(frozen=True, slots=True)
class SecurityMasterCatalogEvent:
    sequence: int
    catalog_identifier: str
    catalog_version: str
    recorded_at: datetime
    payload_json: str
    previous_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("sequence must be an integer")
        if self.sequence < 1:
            raise ValueError("sequence must be positive")
        for field_name in (
            "catalog_identifier",
            "catalog_version",
            "previous_hash",
            "content_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.recorded_at, field_name="recorded_at")
        try:
            decoded = json.loads(self.payload_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("payload_json must be valid JSON") from error
        if not isinstance(decoded, dict):
            raise ValueError("payload_json must encode an object")

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)


class SQLiteSecurityMasterStore:
    """Persist complete catalog versions without mutable historical rows."""

    _TABLE = "security_master_catalogs"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    catalog_identifier TEXT NOT NULL UNIQUE,
                    catalog_version TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );

                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'security-master catalog history is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'security-master catalog history is append-only');
                END;
                """
            )

    def append(
        self,
        catalog: SecurityMasterCatalog,
        *,
        recorded_at: datetime | None = None,
    ) -> SecurityMasterCatalogEvent:
        if not isinstance(catalog, SecurityMasterCatalog):
            raise TypeError("catalog must be a SecurityMasterCatalog")
        recorded = _aware(
            recorded_at or datetime.now(timezone.utc),
            field_name="recorded_at",
        )
        payload_json = _canonical_json(serialize_security_master_catalog(catalog))
        with self._connect() as connection:
            existing = connection.execute(
                f"SELECT * FROM {self._TABLE} WHERE catalog_identifier = ?",
                (catalog.identifier,),
            ).fetchone()
            if existing is not None:
                event = self._event(existing)
                if event.payload_json != payload_json:
                    raise ValueError(
                        "catalog identifier already exists with different content"
                    )
                return event
            previous = connection.execute(
                f"SELECT content_hash FROM {self._TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = (
                str(previous["content_hash"])
                if previous is not None
                else "0" * 64
            )
            content_hash = _content_hash(
                catalog_identifier=catalog.identifier,
                catalog_version=catalog.version,
                recorded_at=recorded,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            cursor = connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    catalog_identifier,
                    catalog_version,
                    recorded_at,
                    payload_json,
                    previous_hash,
                    content_hash
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    catalog.identifier,
                    catalog.version,
                    recorded.isoformat(),
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
            row = connection.execute(
                f"SELECT * FROM {self._TABLE} WHERE sequence = ?",
                (cursor.lastrowid,),
            ).fetchone()
        if row is None:
            raise RuntimeError("security-master catalog append did not persist")
        return self._event(row)

    def get(self, catalog_identifier: str) -> SecurityMasterCatalog | None:
        identifier = _required_text(
            catalog_identifier,
            field_name="catalog_identifier",
        )
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {self._TABLE} WHERE catalog_identifier = ?",
                (identifier,),
            ).fetchone()
        return None if row is None else deserialize_security_master_catalog(
            self._event(row).payload
        )

    def latest(self) -> SecurityMasterCatalog | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        return None if row is None else deserialize_security_master_catalog(
            self._event(row).payload
        )

    def snapshot(
        self,
        *,
        as_of: datetime,
        knowledge_cutoff: datetime | None = None,
        catalog_identifier: str | None = None,
        require_authoritative: bool = False,
    ) -> PointInTimeSecurityMasterSnapshot:
        catalog = (
            self.get(catalog_identifier)
            if catalog_identifier is not None
            else self.latest()
        )
        if catalog is None:
            raise LookupError("no security-master catalog is available")
        return catalog.snapshot(
            as_of=as_of,
            knowledge_cutoff=knowledge_cutoff,
            require_authoritative=require_authoritative,
        )

    def events(self) -> tuple[SecurityMasterCatalogEvent, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        return tuple(self._event(row) for row in rows)

    def verify_integrity(self) -> bool:
        previous_hash = "0" * 64
        expected_sequence = 1
        for event in self.events():
            if event.sequence != expected_sequence:
                raise SecurityMasterIntegrityError(
                    "security-master catalog sequence is not contiguous"
                )
            if event.previous_hash != previous_hash:
                raise SecurityMasterIntegrityError(
                    "security-master previous-hash link is invalid"
                )
            expected_hash = _content_hash(
                catalog_identifier=event.catalog_identifier,
                catalog_version=event.catalog_version,
                recorded_at=event.recorded_at,
                payload_json=event.payload_json,
                previous_hash=event.previous_hash,
            )
            if event.content_hash != expected_hash:
                raise SecurityMasterIntegrityError(
                    "security-master catalog content hash is invalid"
                )
            previous_hash = event.content_hash
            expected_sequence += 1
        return True

    @staticmethod
    def _event(row: sqlite3.Row) -> SecurityMasterCatalogEvent:
        return SecurityMasterCatalogEvent(
            sequence=int(row["sequence"]),
            catalog_identifier=str(row["catalog_identifier"]),
            catalog_version=str(row["catalog_version"]),
            recorded_at=datetime.fromisoformat(str(row["recorded_at"])),
            payload_json=str(row["payload_json"]),
            previous_hash=str(row["previous_hash"]),
            content_hash=str(row["content_hash"]),
        )


def _content_hash(
    *,
    catalog_identifier: str,
    catalog_version: str,
    recorded_at: datetime,
    payload_json: str,
    previous_hash: str,
) -> str:
    material = "\n".join(
        (
            catalog_identifier,
            catalog_version,
            recorded_at.isoformat(),
            payload_json,
            previous_hash,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def serialize_security_master_catalog(
    catalog: SecurityMasterCatalog,
) -> dict[str, Any]:
    if not isinstance(catalog, SecurityMasterCatalog):
        raise TypeError("catalog must be a SecurityMasterCatalog")
    return {
        "schema_version": "security-master-catalog.v1",
        "identifier": catalog.identifier,
        "version": catalog.version,
        "coverage": _coverage_payload(catalog.coverage),
        "issuers": [_issuer_record_payload(item) for item in catalog.issuers],
        "instruments": [
            _instrument_record_payload(item) for item in catalog.instruments
        ],
        "identifiers": [
            _identifier_assignment_payload(item) for item in catalog.identifiers
        ],
        "listings": [_listing_record_payload(item) for item in catalog.listings],
        "actions": [_action_payload(item) for item in catalog.actions],
    }


def deserialize_security_master_catalog(
    payload: dict[str, Any],
) -> SecurityMasterCatalog:
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dictionary")
    if payload.get("schema_version") != "security-master-catalog.v1":
        raise ValueError("unsupported security-master catalog schema")
    return SecurityMasterCatalog(
        identifier=str(payload["identifier"]),
        version=str(payload["version"]),
        coverage=_coverage_from_payload(payload["coverage"]),
        issuers=tuple(_issuer_record_from_payload(item) for item in payload["issuers"]),
        instruments=tuple(
            _instrument_record_from_payload(item) for item in payload["instruments"]
        ),
        identifiers=tuple(
            _identifier_assignment_from_payload(item)
            for item in payload["identifiers"]
        ),
        listings=tuple(
            _listing_record_from_payload(item) for item in payload["listings"]
        ),
        actions=tuple(_action_from_payload(item) for item in payload["actions"]),
    )


def _coverage_payload(value: SecurityMasterCoverage) -> dict[str, Any]:
    return {
        "source": value.source,
        "source_version": value.source_version,
        "licensed": value.licensed,
        "complete_universe": value.complete_universe,
        "point_in_time": value.point_in_time,
        "historical_identifiers": value.historical_identifiers,
        "listing_history": value.listing_history,
        "delistings": value.delistings,
        "corporate_actions": value.corporate_actions,
        "provenance_complete": value.provenance_complete,
        "service_level_defined": value.service_level_defined,
    }


def _coverage_from_payload(payload: dict[str, Any]) -> SecurityMasterCoverage:
    return SecurityMasterCoverage(**payload)


def _identifier_payload(value: InstrumentIdentifier) -> dict[str, Any]:
    return {
        "scheme": value.scheme.value,
        "value": value.value,
        "provider": value.provider,
    }


def _identifier_from_payload(payload: dict[str, Any]) -> InstrumentIdentifier:
    return InstrumentIdentifier(
        scheme=IdentifierScheme(payload["scheme"]),
        value=str(payload["value"]),
        provider=payload.get("provider"),
    )


def _issuer_payload(value: Issuer) -> dict[str, Any]:
    return {
        "issuer_id": value.issuer_id,
        "name": value.name,
        "identifiers": [_identifier_payload(item) for item in value.identifiers],
    }


def _issuer_from_payload(payload: dict[str, Any]) -> Issuer:
    return Issuer(
        issuer_id=str(payload["issuer_id"]),
        name=str(payload["name"]),
        identifiers=tuple(
            _identifier_from_payload(item) for item in payload["identifiers"]
        ),
    )


def _instrument_payload(value: Instrument) -> dict[str, Any]:
    return {
        "instrument_id": value.instrument_id,
        "name": value.name,
        "asset_class": value.asset_class.value,
        "instrument_type": value.instrument_type.value,
        "identifiers": [_identifier_payload(item) for item in value.identifiers],
        "issuer_id": value.issuer_id,
        "base_asset": value.base_asset,
        "quote_currency": value.quote_currency,
        "settlement_currency": value.settlement_currency,
        "network": value.network,
        "economic_exposure": (
            None if value.economic_exposure is None else value.economic_exposure.value
        ),
        "leverage_multiplier": value.leverage_multiplier,
        "uses_derivatives": value.uses_derivatives,
        "replication_method": value.replication_method,
    }


def _instrument_from_payload(payload: dict[str, Any]) -> Instrument:
    return Instrument(
        instrument_id=str(payload["instrument_id"]),
        name=str(payload["name"]),
        asset_class=AssetClass(payload["asset_class"]),
        instrument_type=InstrumentType(payload["instrument_type"]),
        identifiers=tuple(
            _identifier_from_payload(item) for item in payload["identifiers"]
        ),
        issuer_id=payload.get("issuer_id"),
        base_asset=payload.get("base_asset"),
        quote_currency=payload.get("quote_currency"),
        settlement_currency=payload.get("settlement_currency"),
        network=payload.get("network"),
        economic_exposure=(
            None
            if payload.get("economic_exposure") is None
            else AssetClass(str(payload["economic_exposure"]))
        ),
        leverage_multiplier=float(payload.get("leverage_multiplier", 1.0)),
        uses_derivatives=bool(payload.get("uses_derivatives", False)),
        replication_method=payload.get("replication_method"),
    )


def _temporal_payload(value: object) -> dict[str, Any]:
    return {
        "record_identifier": value.record_identifier,
        "effective_from": value.effective_from.isoformat(),
        "effective_until": (
            value.effective_until.isoformat()
            if value.effective_until is not None
            else None
        ),
        "available_at": value.available_at.isoformat(),
        "source_identifier": value.source_identifier,
    }


def _issuer_record_payload(value: IssuerRecord) -> dict[str, Any]:
    return {**_temporal_payload(value), "issuer": _issuer_payload(value.issuer)}


def _issuer_record_from_payload(payload: dict[str, Any]) -> IssuerRecord:
    return IssuerRecord(
        record_identifier=str(payload["record_identifier"]),
        issuer=_issuer_from_payload(payload["issuer"]),
        effective_from=datetime.fromisoformat(payload["effective_from"]),
        effective_until=(
            datetime.fromisoformat(payload["effective_until"])
            if payload.get("effective_until") is not None
            else None
        ),
        available_at=datetime.fromisoformat(payload["available_at"]),
        source_identifier=str(payload["source_identifier"]),
    )


def _instrument_record_payload(value: InstrumentRecord) -> dict[str, Any]:
    return {
        **_temporal_payload(value),
        "instrument": _instrument_payload(value.instrument),
    }


def _instrument_record_from_payload(payload: dict[str, Any]) -> InstrumentRecord:
    return InstrumentRecord(
        record_identifier=str(payload["record_identifier"]),
        instrument=_instrument_from_payload(payload["instrument"]),
        effective_from=datetime.fromisoformat(payload["effective_from"]),
        effective_until=(
            datetime.fromisoformat(payload["effective_until"])
            if payload.get("effective_until") is not None
            else None
        ),
        available_at=datetime.fromisoformat(payload["available_at"]),
        source_identifier=str(payload["source_identifier"]),
    )


def _identifier_assignment_payload(value: IdentifierAssignment) -> dict[str, Any]:
    return {
        **_temporal_payload(value),
        "assignment_identifier": value.assignment_identifier,
        "entity_type": value.entity_type.value,
        "entity_identifier": value.entity_identifier,
        "identifier": _identifier_payload(value.identifier),
    }


def _identifier_assignment_from_payload(
    payload: dict[str, Any],
) -> IdentifierAssignment:
    return IdentifierAssignment(
        record_identifier=str(payload["record_identifier"]),
        assignment_identifier=str(payload["assignment_identifier"]),
        entity_type=SecurityEntityType(payload["entity_type"]),
        entity_identifier=str(payload["entity_identifier"]),
        identifier=_identifier_from_payload(payload["identifier"]),
        effective_from=datetime.fromisoformat(payload["effective_from"]),
        effective_until=(
            datetime.fromisoformat(payload["effective_until"])
            if payload.get("effective_until") is not None
            else None
        ),
        available_at=datetime.fromisoformat(payload["available_at"]),
        source_identifier=str(payload["source_identifier"]),
    )


def _listing_record_payload(value: ListingRecord) -> dict[str, Any]:
    return {
        **_temporal_payload(value),
        "listing_identifier": value.listing_identifier,
        "instrument_identifier": value.instrument_identifier,
        "venue": value.venue,
        "symbol": value.symbol,
        "country_code": value.country_code,
        "trading_calendar": value.trading_calendar.value,
        "status": value.status.value,
        "primary": value.primary,
    }


def _listing_record_from_payload(payload: dict[str, Any]) -> ListingRecord:
    return ListingRecord(
        record_identifier=str(payload["record_identifier"]),
        listing_identifier=str(payload["listing_identifier"]),
        instrument_identifier=str(payload["instrument_identifier"]),
        venue=str(payload["venue"]),
        symbol=str(payload["symbol"]),
        country_code=str(payload["country_code"]),
        trading_calendar=TradingCalendar(payload["trading_calendar"]),
        status=ListingStatus(payload["status"]),
        primary=bool(payload["primary"]),
        effective_from=datetime.fromisoformat(payload["effective_from"]),
        effective_until=(
            datetime.fromisoformat(payload["effective_until"])
            if payload.get("effective_until") is not None
            else None
        ),
        available_at=datetime.fromisoformat(payload["available_at"]),
        source_identifier=str(payload["source_identifier"]),
    )


def _action_payload(value: SecurityMasterAction) -> dict[str, Any]:
    return {
        "record_identifier": value.record_identifier,
        "action_identifier": value.action_identifier,
        "instrument_identifier": value.instrument_identifier,
        "action_type": value.action_type.value,
        "announced_at": value.announced_at.isoformat(),
        "effective_at": value.effective_at.isoformat(),
        "available_at": value.available_at.isoformat(),
        "source_identifier": value.source_identifier,
        "successor_instrument_identifier": value.successor_instrument_identifier,
        "new_symbol": value.new_symbol,
        "new_venue": value.new_venue,
        "ratio": value.ratio,
    }


def _action_from_payload(payload: dict[str, Any]) -> SecurityMasterAction:
    return SecurityMasterAction(
        record_identifier=str(payload["record_identifier"]),
        action_identifier=str(payload["action_identifier"]),
        instrument_identifier=str(payload["instrument_identifier"]),
        action_type=SecurityMasterActionType(payload["action_type"]),
        announced_at=datetime.fromisoformat(payload["announced_at"]),
        effective_at=datetime.fromisoformat(payload["effective_at"]),
        available_at=datetime.fromisoformat(payload["available_at"]),
        source_identifier=str(payload["source_identifier"]),
        successor_instrument_identifier=payload.get(
            "successor_instrument_identifier"
        ),
        new_symbol=payload.get("new_symbol"),
        new_venue=payload.get("new_venue"),
        ratio=payload.get("ratio"),
    )


__all__ = [
    "SQLiteSecurityMasterStore",
    "SecurityMasterCatalogEvent",
    "SecurityMasterIntegrityError",
    "deserialize_security_master_catalog",
    "serialize_security_master_catalog",
]
