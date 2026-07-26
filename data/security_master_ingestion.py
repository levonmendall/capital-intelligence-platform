"""Operational ingestion, reconciliation, quality, and activation controls.

A catalog may be useful identity evidence without being safe to power a full-
universe investment cycle.  This module keeps those states separate: providers
fetch immutable catalogs, ingestion stores them for audit, quality policy judges
them, and an append-only activation registry records the catalogs explicitly
authorized for Version 1 screening.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from data.security import AssetClass, IdentifierScheme, InstrumentType, SecurityMasterError
from data.security_master import (
    IdentifierAssignment,
    InstrumentRecord,
    IssuerRecord,
    ListingRecord,
    ListingStatus,
    SecurityMasterAction,
    SecurityMasterCatalog,
    SecurityMasterCoverage,
    SecurityEntityType,
)
from data.security_master_store import (
    SQLiteSecurityMasterStore,
    SecurityMasterCatalogEvent,
    SecurityMasterIntegrityError,
)


def _required_text(value: object, *, field_name: str) -> str:
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


def _finite(
    value: object,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    if maximum is not None and normalized > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}")
    return round(normalized, 10)


def _ratio(value: object, *, field_name: str) -> float:
    return _finite(
        value,
        field_name=field_name,
        minimum=0.0,
        maximum=1.0,
    )


def _canonical_json(value: dict[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("security-master operation payload must be finite JSON") from error


class SecurityMasterActivationMode(str, Enum):
    """How ingestion should treat activation eligibility."""

    STORE_ONLY = "store_only"
    ACTIVATE_IF_ELIGIBLE = "activate_if_eligible"
    REQUIRE_ACTIVATION = "require_activation"


class SecurityMasterIngestionDisposition(str, Enum):
    """Auditable outcome of one provider ingestion request."""

    STORED_ONLY = "stored_only"
    STORED_NOT_ACTIVATED = "stored_not_activated"
    ACTIVATED = "activated"
    ACTIVATION_REJECTED = "activation_rejected"


class SecurityMasterOperationType(str, Enum):
    INGESTION = "ingestion"
    ACTIVATION = "activation"


class SecurityMasterProviderError(RuntimeError):
    """Raised when a provider cannot return a valid immutable catalog."""


class SecurityMasterReconciliationError(SecurityMasterError):
    """Raised when independent source records conflict at the same boundary."""


class SecurityMasterActivationError(SecurityMasterError):
    """Raised when a caller requires activation but policy blocks the catalog."""

    def __init__(self, result: "SecurityMasterIngestionResult") -> None:
        self.result = result
        detail = "; ".join(result.reasons) or "catalog did not satisfy activation policy"
        super().__init__(f"security-master activation was rejected: {detail}")


@dataclass(frozen=True, slots=True)
class SecurityMasterIngestionQuery:
    """One immutable operational request and its point-in-time boundary."""

    identifier: str
    as_of: datetime
    knowledge_cutoff: datetime
    requested_at: datetime
    activation_mode: SecurityMasterActivationMode = (
        SecurityMasterActivationMode.ACTIVATE_IF_ELIGIBLE
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _required_text(self.identifier, field_name="identifier"),
        )
        for field_name in ("as_of", "knowledge_cutoff", "requested_at"):
            object.__setattr__(
                self,
                field_name,
                _aware(getattr(self, field_name), field_name=field_name),
            )
        if self.knowledge_cutoff < self.as_of:
            raise ValueError("knowledge_cutoff cannot predate as_of")
        if self.requested_at < self.knowledge_cutoff:
            raise ValueError("requested_at cannot predate knowledge_cutoff")
        if not isinstance(self.activation_mode, SecurityMasterActivationMode):
            raise TypeError("activation_mode must be SecurityMasterActivationMode")


@dataclass(frozen=True, slots=True)
class SecurityMasterCatalogDelivery:
    """Catalog plus the source observation and retrieval boundary."""

    catalog: SecurityMasterCatalog
    observed_at: datetime
    retrieved_at: datetime
    request_identifier: str

    def __post_init__(self) -> None:
        if not isinstance(self.catalog, SecurityMasterCatalog):
            raise TypeError("catalog must be SecurityMasterCatalog")
        observed = _aware(self.observed_at, field_name="observed_at")
        retrieved = _aware(self.retrieved_at, field_name="retrieved_at")
        if observed > retrieved:
            raise ValueError("observed_at cannot follow retrieved_at")
        object.__setattr__(
            self,
            "request_identifier",
            _required_text(
                self.request_identifier,
                field_name="request_identifier",
            ),
        )


@runtime_checkable
class SecurityMasterProvider(Protocol):
    """Provider-neutral immutable catalog retrieval contract."""

    @property
    def name(self) -> str:
        ...

    def fetch_security_master_delivery(
        self,
        query: SecurityMasterIngestionQuery,
    ) -> SecurityMasterCatalogDelivery:
        ...


@dataclass(frozen=True, slots=True)
class SecurityMasterActivationPolicy:
    """Minimum current-catalog quality required for full-universe screening."""

    version: str = "security-master-activation.v1"
    maximum_catalog_age_hours: float = 36.0
    minimum_instrument_count: int = 1
    minimum_active_listing_ratio: float = 0.95
    minimum_classified_instrument_ratio: float = 0.98
    minimum_stable_identifier_ratio: float = 0.90
    require_authoritative_coverage: bool = True
    require_catalog_integrity: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "version",
            _required_text(self.version, field_name="version"),
        )
        object.__setattr__(
            self,
            "maximum_catalog_age_hours",
            _finite(
                self.maximum_catalog_age_hours,
                field_name="maximum_catalog_age_hours",
                minimum=0.0,
            ),
        )
        if (
            isinstance(self.minimum_instrument_count, bool)
            or not isinstance(self.minimum_instrument_count, int)
        ):
            raise TypeError("minimum_instrument_count must be an integer")
        if self.minimum_instrument_count < 1:
            raise ValueError("minimum_instrument_count must be positive")
        for field_name in (
            "minimum_active_listing_ratio",
            "minimum_classified_instrument_ratio",
            "minimum_stable_identifier_ratio",
        ):
            object.__setattr__(
                self,
                field_name,
                _ratio(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "require_authoritative_coverage",
            "require_catalog_integrity",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")

    def assess(
        self,
        delivery: SecurityMasterCatalogDelivery,
        *,
        query: SecurityMasterIngestionQuery,
        integrity_verified: bool,
        evaluated_at: datetime | None = None,
    ) -> "SecurityMasterQualityReport":
        if not isinstance(delivery, SecurityMasterCatalogDelivery):
            raise TypeError("delivery must be SecurityMasterCatalogDelivery")
        catalog = delivery.catalog
        if not isinstance(query, SecurityMasterIngestionQuery):
            raise TypeError("query must be SecurityMasterIngestionQuery")
        if not isinstance(integrity_verified, bool):
            raise TypeError("integrity_verified must be a bool")
        evaluated = _aware(
            evaluated_at or query.requested_at,
            field_name="evaluated_at",
        )

        issues: list[str] = []
        if self.require_authoritative_coverage and not catalog.coverage.authoritative:
            issues.extend(
                f"coverage missing {item}" for item in catalog.coverage.deficiencies
            )
        if self.require_catalog_integrity and not integrity_verified:
            issues.append("catalog-store integrity was not verified")

        try:
            snapshot = catalog.snapshot(
                as_of=query.as_of,
                knowledge_cutoff=query.knowledge_cutoff,
            )
        except (LookupError, TypeError, ValueError) as error:
            raise SecurityMasterError(
                "catalog cannot produce the requested point-in-time snapshot"
            ) from error

        listings_by_instrument: dict[str, list[ListingRecord]] = {}
        for listing in snapshot.listings:
            listings_by_instrument.setdefault(
                listing.instrument_identifier,
                [],
            ).append(listing)
        explicitly_delisted = {
            instrument_identifier
            for instrument_identifier, listings in listings_by_instrument.items()
            if listings
            and all(item.status is ListingStatus.DELISTED for item in listings)
        }
        operational_instruments = tuple(
            item
            for item in snapshot.instruments
            if item.instrument.instrument_id not in explicitly_delisted
        )
        instrument_count = len(operational_instruments)
        active_listings = tuple(
            item for item in snapshot.listings if item.status is ListingStatus.ACTIVE
        )
        listed_instruments = {
            item.instrument_identifier for item in active_listings
        }
        active_listing_ratio = (
            len(
                listed_instruments
                & {item.instrument.instrument_id for item in operational_instruments}
            )
            / instrument_count
            if instrument_count
            else 0.0
        )

        classified = tuple(
            item
            for item in operational_instruments
            if item.instrument.asset_class is not AssetClass.UNKNOWN
            and item.instrument.instrument_type is not InstrumentType.OTHER
        )
        classified_ratio = (
            len(classified) / instrument_count if instrument_count else 0.0
        )

        stable_instrument_ids = {
            item.entity_identifier
            for item in snapshot.identifiers
            if item.entity_type is SecurityEntityType.INSTRUMENT
            and item.identifier.scheme
            in {
                IdentifierScheme.CUSIP,
                IdentifierScheme.FIGI,
                IdentifierScheme.ISIN,
            }
        }
        operational_ids = {
            item.instrument.instrument_id for item in operational_instruments
        }
        stable_identifier_ratio = (
            len(stable_instrument_ids & operational_ids) / instrument_count
            if instrument_count
            else 0.0
        )

        listing_keys = tuple((item.venue, item.symbol) for item in active_listings)
        duplicate_listing_count = len(listing_keys) - len(set(listing_keys))

        records = (
            *catalog.issuers,
            *catalog.instruments,
            *catalog.identifiers,
            *catalog.listings,
            *catalog.actions,
        )
        latest_available_at = max(item.available_at for item in records)
        source_age_hours = (evaluated - delivery.observed_at).total_seconds() / 3600.0
        if delivery.retrieved_at > query.requested_at:
            issues.append("provider delivery was retrieved after the request boundary")
        if delivery.retrieved_at > query.knowledge_cutoff:
            issues.append("provider delivery was unavailable by the knowledge cutoff")
        if source_age_hours < 0:
            issues.append("provider observation is later than evaluation time")
        elif source_age_hours > self.maximum_catalog_age_hours:
            issues.append(
                "source observation age exceeds activation policy: "
                f"{source_age_hours:.2f}h > {self.maximum_catalog_age_hours:.2f}h"
            )
        if instrument_count < self.minimum_instrument_count:
            issues.append(
                "instrument count is below activation minimum: "
                f"{instrument_count} < {self.minimum_instrument_count}"
            )
        if active_listing_ratio < self.minimum_active_listing_ratio:
            issues.append(
                "active-listing coverage is below activation minimum: "
                f"{active_listing_ratio:.4f} < {self.minimum_active_listing_ratio:.4f}"
            )
        if classified_ratio < self.minimum_classified_instrument_ratio:
            issues.append(
                "instrument classification is below activation minimum: "
                f"{classified_ratio:.4f} < "
                f"{self.minimum_classified_instrument_ratio:.4f}"
            )
        if stable_identifier_ratio < self.minimum_stable_identifier_ratio:
            issues.append(
                "stable-identifier coverage is below activation minimum: "
                f"{stable_identifier_ratio:.4f} < "
                f"{self.minimum_stable_identifier_ratio:.4f}"
            )
        if duplicate_listing_count:
            issues.append(
                f"catalog contains {duplicate_listing_count} duplicate active venue-symbol listing(s)"
            )

        future_known_records = sum(
            item.available_at > query.knowledge_cutoff for item in records
        )
        if future_known_records:
            issues.append(
                f"catalog contains {future_known_records} record(s) unavailable by the knowledge cutoff"
            )

        return SecurityMasterQualityReport(
            catalog_identifier=catalog.identifier,
            policy_version=self.version,
            evaluated_at=evaluated,
            as_of=query.as_of,
            knowledge_cutoff=query.knowledge_cutoff,
            source=catalog.coverage.source,
            authoritative_coverage=catalog.coverage.authoritative,
            integrity_verified=integrity_verified,
            instrument_count=instrument_count,
            active_listing_count=len(active_listings),
            active_listing_ratio=active_listing_ratio,
            classified_instrument_ratio=classified_ratio,
            stable_identifier_ratio=stable_identifier_ratio,
            duplicate_active_listing_count=duplicate_listing_count,
            future_known_record_count=future_known_records,
            source_observed_at=delivery.observed_at,
            source_retrieved_at=delivery.retrieved_at,
            latest_record_available_at=latest_available_at,
            source_age_hours=max(0.0, source_age_hours),
            coverage_deficiencies=catalog.coverage.deficiencies,
            issues=tuple(dict.fromkeys(issues)),
        )


@dataclass(frozen=True, slots=True)
class SecurityMasterQualityReport:
    """Transparent quality and SLA result used by activation policy."""

    catalog_identifier: str
    policy_version: str
    evaluated_at: datetime
    as_of: datetime
    knowledge_cutoff: datetime
    source: str
    authoritative_coverage: bool
    integrity_verified: bool
    instrument_count: int
    active_listing_count: int
    active_listing_ratio: float
    classified_instrument_ratio: float
    stable_identifier_ratio: float
    duplicate_active_listing_count: int
    future_known_record_count: int
    source_observed_at: datetime
    source_retrieved_at: datetime
    latest_record_available_at: datetime
    source_age_hours: float
    coverage_deficiencies: tuple[str, ...]
    issues: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("catalog_identifier", "policy_version", "source"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "evaluated_at",
            "as_of",
            "knowledge_cutoff",
            "source_observed_at",
            "source_retrieved_at",
            "latest_record_available_at",
        ):
            _aware(getattr(self, field_name), field_name=field_name)
        for field_name in ("authoritative_coverage", "integrity_verified"):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")
        for field_name in (
            "instrument_count",
            "active_listing_count",
            "duplicate_active_listing_count",
            "future_known_record_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} cannot be negative")
        for field_name in (
            "active_listing_ratio",
            "classified_instrument_ratio",
            "stable_identifier_ratio",
        ):
            object.__setattr__(
                self,
                field_name,
                _ratio(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "source_age_hours",
            _finite(
                self.source_age_hours,
                field_name="source_age_hours",
                minimum=0.0,
            ),
        )
        for field_name in ("coverage_deficiencies", "issues"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, str) and item.strip() for item in values
            ):
                raise TypeError(f"{field_name} must contain non-empty strings")

    @property
    def activatable(self) -> bool:
        return not self.issues


@dataclass(frozen=True, slots=True)
class SecurityMasterIngestionResult:
    identifier: str
    provider: str
    catalog_identifier: str
    catalog_content_hash: str
    ingested_at: datetime
    disposition: SecurityMasterIngestionDisposition
    activation_identifier: str | None
    quality: SecurityMasterQualityReport
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "provider",
            "catalog_identifier",
            "catalog_content_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.ingested_at, field_name="ingested_at")
        if not isinstance(self.disposition, SecurityMasterIngestionDisposition):
            raise TypeError("disposition must be SecurityMasterIngestionDisposition")
        if self.activation_identifier is not None:
            object.__setattr__(
                self,
                "activation_identifier",
                _required_text(
                    self.activation_identifier,
                    field_name="activation_identifier",
                ),
            )
        if self.disposition is SecurityMasterIngestionDisposition.ACTIVATED:
            if self.activation_identifier is None:
                raise ValueError("activated result requires activation_identifier")
        elif self.activation_identifier is not None:
            raise ValueError("non-activated result cannot contain activation_identifier")
        if not isinstance(self.quality, SecurityMasterQualityReport):
            raise TypeError("quality must be SecurityMasterQualityReport")
        if not isinstance(self.reasons, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.reasons
        ):
            raise TypeError("reasons must contain non-empty strings")


@dataclass(frozen=True, slots=True)
class SecurityMasterActivationRecord:
    identifier: str
    ingestion_identifier: str
    catalog_identifier: str
    activated_at: datetime
    policy_version: str
    quality: SecurityMasterQualityReport

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "ingestion_identifier",
            "catalog_identifier",
            "policy_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.activated_at, field_name="activated_at")
        if not isinstance(self.quality, SecurityMasterQualityReport):
            raise TypeError("quality must be SecurityMasterQualityReport")
        if not self.quality.activatable:
            raise ValueError("activation record requires an activatable quality report")


@dataclass(frozen=True, slots=True)
class SecurityMasterOperationalStatus:
    """Current readiness derived from immutable ingestion and activation events."""

    evaluated_at: datetime
    catalog_integrity_verified: bool
    operation_integrity_verified: bool
    latest_ingestion: SecurityMasterIngestionResult | None
    latest_activation: SecurityMasterActivationRecord | None
    active_catalog_identifier: str | None
    active_source_age_hours: float | None
    screening_ready: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _aware(self.evaluated_at, field_name="evaluated_at")
        for field_name in (
            "catalog_integrity_verified",
            "operation_integrity_verified",
            "screening_ready",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")
        if self.latest_ingestion is not None and not isinstance(
            self.latest_ingestion,
            SecurityMasterIngestionResult,
        ):
            raise TypeError(
                "latest_ingestion must be SecurityMasterIngestionResult or None"
            )
        if self.latest_activation is not None and not isinstance(
            self.latest_activation,
            SecurityMasterActivationRecord,
        ):
            raise TypeError(
                "latest_activation must be SecurityMasterActivationRecord or None"
            )
        if self.active_catalog_identifier is not None:
            object.__setattr__(
                self,
                "active_catalog_identifier",
                _required_text(
                    self.active_catalog_identifier,
                    field_name="active_catalog_identifier",
                ),
            )
        if self.active_source_age_hours is not None:
            object.__setattr__(
                self,
                "active_source_age_hours",
                _finite(
                    self.active_source_age_hours,
                    field_name="active_source_age_hours",
                    minimum=0.0,
                ),
            )
        if not isinstance(self.reasons, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.reasons
        ):
            raise TypeError("reasons must contain non-empty strings")


@dataclass(frozen=True, slots=True)
class SecurityMasterOperationEvent:
    sequence: int
    operation_identifier: str
    operation_type: SecurityMasterOperationType
    catalog_identifier: str
    occurred_at: datetime
    payload_json: str
    previous_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("sequence must be an integer")
        if self.sequence < 1:
            raise ValueError("sequence must be positive")
        for field_name in (
            "operation_identifier",
            "catalog_identifier",
            "previous_hash",
            "content_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.operation_type, SecurityMasterOperationType):
            raise TypeError("operation_type must be SecurityMasterOperationType")
        _aware(self.occurred_at, field_name="occurred_at")
        try:
            payload = json.loads(self.payload_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("payload_json must be valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("payload_json must encode an object")

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)


class SQLiteSecurityMasterOperationalStore:
    """Append-only ingestion and activation registry beside catalog storage."""

    _TABLE = "security_master_operations"

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
                    operation_identifier TEXT NOT NULL UNIQUE,
                    operation_type TEXT NOT NULL,
                    catalog_identifier TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );

                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'security-master operation history is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'security-master operation history is append-only');
                END;
                """
            )

    def append_ingestion(
        self,
        result: SecurityMasterIngestionResult,
    ) -> SecurityMasterOperationEvent:
        if not isinstance(result, SecurityMasterIngestionResult):
            raise TypeError("result must be SecurityMasterIngestionResult")
        return self._append(
            operation_identifier=f"ingestion:{result.identifier}",
            operation_type=SecurityMasterOperationType.INGESTION,
            catalog_identifier=result.catalog_identifier,
            occurred_at=result.ingested_at,
            payload=_ingestion_payload(result),
        )

    def append_activation(
        self,
        activation: SecurityMasterActivationRecord,
    ) -> SecurityMasterOperationEvent:
        if not isinstance(activation, SecurityMasterActivationRecord):
            raise TypeError("activation must be SecurityMasterActivationRecord")
        return self._append(
            operation_identifier=f"activation:{activation.identifier}",
            operation_type=SecurityMasterOperationType.ACTIVATION,
            catalog_identifier=activation.catalog_identifier,
            occurred_at=activation.activated_at,
            payload=_activation_payload(activation),
        )

    def _append(
        self,
        *,
        operation_identifier: str,
        operation_type: SecurityMasterOperationType,
        catalog_identifier: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> SecurityMasterOperationEvent:
        identifier = _required_text(
            operation_identifier,
            field_name="operation_identifier",
        )
        catalog_id = _required_text(
            catalog_identifier,
            field_name="catalog_identifier",
        )
        occurred = _aware(occurred_at, field_name="occurred_at")
        payload_json = _canonical_json(payload)
        with self._connect() as connection:
            existing = connection.execute(
                f"SELECT * FROM {self._TABLE} WHERE operation_identifier = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                event = self._event(existing)
                if (
                    event.operation_type is not operation_type
                    or event.catalog_identifier != catalog_id
                    or event.occurred_at != occurred
                    or event.payload_json != payload_json
                ):
                    raise ValueError(
                        "operation identifier already exists with different content"
                    )
                return event
            previous = connection.execute(
                f"SELECT content_hash FROM {self._TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = (
                str(previous["content_hash"]) if previous is not None else "0" * 64
            )
            content_hash = _operation_hash(
                operation_identifier=identifier,
                operation_type=operation_type,
                catalog_identifier=catalog_id,
                occurred_at=occurred,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            cursor = connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    operation_identifier,
                    operation_type,
                    catalog_identifier,
                    occurred_at,
                    payload_json,
                    previous_hash,
                    content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    operation_type.value,
                    catalog_id,
                    occurred.isoformat(),
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
            raise RuntimeError("security-master operation append did not persist")
        return self._event(row)

    def events(
        self,
        operation_type: SecurityMasterOperationType | None = None,
    ) -> tuple[SecurityMasterOperationEvent, ...]:
        if operation_type is not None and not isinstance(
            operation_type,
            SecurityMasterOperationType,
        ):
            raise TypeError("operation_type must be SecurityMasterOperationType or None")
        with self._connect() as connection:
            if operation_type is None:
                rows = connection.execute(
                    f"SELECT * FROM {self._TABLE} ORDER BY sequence"
                ).fetchall()
            else:
                rows = connection.execute(
                    f"SELECT * FROM {self._TABLE} WHERE operation_type = ? ORDER BY sequence",
                    (operation_type.value,),
                ).fetchall()
        return tuple(self._event(row) for row in rows)

    def latest_ingestion(self) -> SecurityMasterIngestionResult | None:
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM {self._TABLE}
                WHERE operation_type = ?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (SecurityMasterOperationType.INGESTION.value,),
            ).fetchone()
        if row is None:
            return None
        return _ingestion_from_payload(self._event(row).payload)

    def latest_activation(self) -> SecurityMasterActivationRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM {self._TABLE}
                WHERE operation_type = ?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (SecurityMasterOperationType.ACTIVATION.value,),
            ).fetchone()
        if row is None:
            return None
        return _activation_from_payload(self._event(row).payload)

    def verify_integrity(self) -> bool:
        previous_hash = "0" * 64
        expected_sequence = 1
        for event in self.events():
            if event.sequence != expected_sequence:
                raise SecurityMasterIntegrityError(
                    "security-master operation sequence is not contiguous"
                )
            if event.previous_hash != previous_hash:
                raise SecurityMasterIntegrityError(
                    "security-master operation previous-hash link is invalid"
                )
            expected_hash = _operation_hash(
                operation_identifier=event.operation_identifier,
                operation_type=event.operation_type,
                catalog_identifier=event.catalog_identifier,
                occurred_at=event.occurred_at,
                payload_json=event.payload_json,
                previous_hash=event.previous_hash,
            )
            if event.content_hash != expected_hash:
                raise SecurityMasterIntegrityError(
                    "security-master operation content hash is invalid"
                )
            previous_hash = event.content_hash
            expected_sequence += 1
        return True

    @staticmethod
    def _event(row: sqlite3.Row) -> SecurityMasterOperationEvent:
        return SecurityMasterOperationEvent(
            sequence=int(row["sequence"]),
            operation_identifier=str(row["operation_identifier"]),
            operation_type=SecurityMasterOperationType(str(row["operation_type"])),
            catalog_identifier=str(row["catalog_identifier"]),
            occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
            payload_json=str(row["payload_json"]),
            previous_hash=str(row["previous_hash"]),
            content_hash=str(row["content_hash"]),
        )


class SecurityMasterIngestionService:
    """Fetch, persist, judge, and explicitly activate security-master catalogs."""

    def __init__(
        self,
        catalog_store: SQLiteSecurityMasterStore,
        operational_store: SQLiteSecurityMasterOperationalStore,
        *,
        activation_policy: SecurityMasterActivationPolicy | None = None,
    ) -> None:
        if not isinstance(catalog_store, SQLiteSecurityMasterStore):
            raise TypeError("catalog_store must be SQLiteSecurityMasterStore")
        if not isinstance(
            operational_store,
            SQLiteSecurityMasterOperationalStore,
        ):
            raise TypeError(
                "operational_store must be SQLiteSecurityMasterOperationalStore"
            )
        self.catalog_store = catalog_store
        self.operational_store = operational_store
        self.activation_policy = activation_policy or SecurityMasterActivationPolicy()

    def ingest(
        self,
        provider: SecurityMasterProvider,
        query: SecurityMasterIngestionQuery,
    ) -> SecurityMasterIngestionResult:
        if not isinstance(query, SecurityMasterIngestionQuery):
            raise TypeError("query must be SecurityMasterIngestionQuery")
        if not isinstance(provider, SecurityMasterProvider):
            raise TypeError("provider must implement SecurityMasterProvider")
        provider_name = _required_text(provider.name, field_name="provider.name")
        try:
            delivery = provider.fetch_security_master_delivery(query)
        except (SecurityMasterProviderError, SecurityMasterReconciliationError):
            raise
        except Exception as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            raise SecurityMasterProviderError(
                f"security-master provider {provider_name} failed"
            ) from error
        if not isinstance(delivery, SecurityMasterCatalogDelivery):
            raise SecurityMasterProviderError(
                f"security-master provider {provider_name} returned an invalid delivery"
            )
        if delivery.request_identifier != query.identifier:
            raise SecurityMasterProviderError(
                "provider delivery request identifier does not match ingestion query"
            )
        catalog = delivery.catalog
        if catalog.coverage.source.upper() != provider_name.upper():
            raise SecurityMasterProviderError(
                "catalog coverage source does not match provider identity"
            )

        catalog_event = self.catalog_store.append(
            catalog,
            recorded_at=query.requested_at,
        )
        integrity_verified = self.catalog_store.verify_integrity()
        quality = self.activation_policy.assess(
            delivery,
            query=query,
            integrity_verified=integrity_verified,
            evaluated_at=query.requested_at,
        )

        activation_identifier: str | None = None
        if query.activation_mode is SecurityMasterActivationMode.STORE_ONLY:
            disposition = SecurityMasterIngestionDisposition.STORED_ONLY
            reasons = ("activation was not requested",)
        elif quality.activatable:
            activation_identifier = query.identifier
            disposition = SecurityMasterIngestionDisposition.ACTIVATED
            reasons = ()
        elif query.activation_mode is SecurityMasterActivationMode.REQUIRE_ACTIVATION:
            disposition = SecurityMasterIngestionDisposition.ACTIVATION_REJECTED
            reasons = quality.issues
        else:
            disposition = SecurityMasterIngestionDisposition.STORED_NOT_ACTIVATED
            reasons = quality.issues

        result = SecurityMasterIngestionResult(
            identifier=query.identifier,
            provider=provider_name,
            catalog_identifier=catalog.identifier,
            catalog_content_hash=catalog_event.content_hash,
            ingested_at=query.requested_at,
            disposition=disposition,
            activation_identifier=activation_identifier,
            quality=quality,
            reasons=reasons,
        )
        self.operational_store.append_ingestion(result)
        if activation_identifier is not None:
            self.operational_store.append_activation(
                SecurityMasterActivationRecord(
                    identifier=activation_identifier,
                    ingestion_identifier=query.identifier,
                    catalog_identifier=catalog.identifier,
                    activated_at=query.requested_at,
                    policy_version=self.activation_policy.version,
                    quality=quality,
                )
            )
        self.operational_store.verify_integrity()

        if disposition is SecurityMasterIngestionDisposition.ACTIVATION_REJECTED:
            raise SecurityMasterActivationError(result)
        return result

    def active_catalog(
        self,
        *,
        evaluated_at: datetime | None = None,
    ) -> SecurityMasterCatalog:
        """Return only an activated, authoritative, intact, and fresh catalog."""

        evaluated = _aware(
            evaluated_at or datetime.now(timezone.utc),
            field_name="evaluated_at",
        )
        self.catalog_store.verify_integrity()
        self.operational_store.verify_integrity()
        activation = self.operational_store.latest_activation()
        if activation is None:
            raise LookupError("no security-master catalog has been activated")
        catalog = self.catalog_store.get(activation.catalog_identifier)
        if catalog is None:
            raise SecurityMasterIntegrityError(
                "active security-master catalog is missing from catalog storage"
            )
        catalog.coverage.require_authoritative()
        source_age_hours = (
            evaluated - activation.quality.source_observed_at
        ).total_seconds() / 3600.0
        if source_age_hours < 0:
            raise SecurityMasterError(
                "active security-master observation is later than the evaluation time"
            )
        if source_age_hours > self.activation_policy.maximum_catalog_age_hours:
            raise SecurityMasterError(
                "active security-master catalog is stale: "
                f"{source_age_hours:.2f}h > "
                f"{self.activation_policy.maximum_catalog_age_hours:.2f}h"
            )
        return catalog

    def status(
        self,
        *,
        evaluated_at: datetime | None = None,
    ) -> SecurityMasterOperationalStatus:
        """Return a non-mutating readiness view for operations and monitoring."""

        evaluated = _aware(
            evaluated_at or datetime.now(timezone.utc),
            field_name="evaluated_at",
        )
        catalog_integrity = self.catalog_store.verify_integrity()
        operation_integrity = self.operational_store.verify_integrity()
        latest_ingestion = self.operational_store.latest_ingestion()
        latest_activation = self.operational_store.latest_activation()
        reasons: list[str] = []
        active_catalog_identifier: str | None = None
        active_source_age_hours: float | None = None
        screening_ready = False
        if latest_activation is None:
            reasons.append("no authoritative security-master catalog is activated")
        else:
            active_catalog_identifier = latest_activation.catalog_identifier
            active_source_age_hours = max(
                0.0,
                (
                    evaluated - latest_activation.quality.source_observed_at
                ).total_seconds()
                / 3600.0,
            )
            try:
                self.active_catalog(evaluated_at=evaluated)
            except (LookupError, SecurityMasterError, SecurityMasterIntegrityError) as error:
                reasons.append(str(error))
            else:
                screening_ready = True
        return SecurityMasterOperationalStatus(
            evaluated_at=evaluated,
            catalog_integrity_verified=catalog_integrity,
            operation_integrity_verified=operation_integrity,
            latest_ingestion=latest_ingestion,
            latest_activation=latest_activation,
            active_catalog_identifier=active_catalog_identifier,
            active_source_age_hours=active_source_age_hours,
            screening_ready=screening_ready,
            reasons=tuple(reasons),
        )


@dataclass(frozen=True, slots=True)
class SecurityMasterReconciliationPolicy:
    """Explicit deterministic source order for de-duplication and conflict checks."""

    version: str
    source_priority: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "version",
            _required_text(self.version, field_name="version"),
        )
        if not isinstance(self.source_priority, tuple):
            raise TypeError("source_priority must be a tuple")
        normalized = tuple(
            _required_text(item, field_name="source_priority").upper()
            for item in self.source_priority
        )
        if not normalized:
            raise ValueError("source_priority cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("source_priority cannot contain duplicates")
        object.__setattr__(self, "source_priority", normalized)


@dataclass(frozen=True, slots=True)
class SecurityMasterReconciliationReport:
    identifier: str
    policy_version: str
    sources: tuple[str, ...]
    selected_record_count: int
    duplicate_record_count: int

    def __post_init__(self) -> None:
        for field_name in ("identifier", "policy_version"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.sources, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.sources
        ):
            raise TypeError("sources must contain non-empty strings")
        for field_name in ("selected_record_count", "duplicate_record_count"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} cannot be negative")


@dataclass(frozen=True, slots=True)
class ReconciledSecurityMaster:
    catalog: SecurityMasterCatalog
    report: SecurityMasterReconciliationReport

    def __post_init__(self) -> None:
        if not isinstance(self.catalog, SecurityMasterCatalog):
            raise TypeError("catalog must be SecurityMasterCatalog")
        if not isinstance(self.report, SecurityMasterReconciliationReport):
            raise TypeError("report must be SecurityMasterReconciliationReport")


class SecurityMasterReconciler:
    """Merge independent catalogs only when their overlapping facts agree."""

    def __init__(self, policy: SecurityMasterReconciliationPolicy) -> None:
        if not isinstance(policy, SecurityMasterReconciliationPolicy):
            raise TypeError("policy must be SecurityMasterReconciliationPolicy")
        self.policy = policy

    def reconcile(
        self,
        catalogs: tuple[SecurityMasterCatalog, ...],
        *,
        identifier: str,
        version: str,
    ) -> ReconciledSecurityMaster:
        if not isinstance(catalogs, tuple) or not all(
            isinstance(item, SecurityMasterCatalog) for item in catalogs
        ):
            raise TypeError("catalogs must contain SecurityMasterCatalog values")
        if not catalogs:
            raise ValueError("catalogs cannot be empty")
        sources = tuple(item.coverage.source.upper() for item in catalogs)
        if len(sources) != len(set(sources)):
            raise ValueError("catalogs cannot repeat a coverage source")
        unknown = tuple(
            source for source in sources if source not in self.policy.source_priority
        )
        if unknown:
            raise ValueError(
                "source priority is missing catalog source(s): "
                + ", ".join(sorted(unknown))
            )
        ranked = tuple(
            sorted(
                catalogs,
                key=lambda item: self.policy.source_priority.index(
                    item.coverage.source.upper()
                ),
            )
        )

        selected_count = 0
        duplicate_count = 0

        def merge_family(values, *, key, normalize, label):
            nonlocal selected_count, duplicate_count
            selected: dict[object, object] = {}
            normalized: dict[object, object] = {}
            for catalog in ranked:
                for item in values(catalog):
                    natural_key = key(item)
                    comparable = normalize(item)
                    current = selected.get(natural_key)
                    if current is None:
                        selected[natural_key] = item
                        normalized[natural_key] = comparable
                        selected_count += 1
                        continue
                    if normalized[natural_key] != comparable:
                        raise SecurityMasterReconciliationError(
                            f"conflicting {label} record at key {natural_key!r}"
                        )
                    duplicate_count += 1
            return tuple(selected.values())

        issuers = merge_family(
            lambda catalog: catalog.issuers,
            key=lambda item: (
                item.issuer.issuer_id,
                item.effective_from,
                item.effective_until,
                item.available_at,
            ),
            normalize=_issuer_record_semantic,
            label="issuer",
        )
        instruments = merge_family(
            lambda catalog: catalog.instruments,
            key=lambda item: (
                item.instrument.instrument_id,
                item.effective_from,
                item.effective_until,
                item.available_at,
            ),
            normalize=_instrument_record_semantic,
            label="instrument",
        )
        identifiers = merge_family(
            lambda catalog: catalog.identifiers,
            key=lambda item: (
                item.assignment_identifier,
                item.effective_from,
                item.effective_until,
                item.available_at,
            ),
            normalize=_identifier_assignment_semantic,
            label="identifier",
        )
        listings = merge_family(
            lambda catalog: catalog.listings,
            key=lambda item: (
                item.listing_identifier,
                item.effective_from,
                item.effective_until,
                item.available_at,
            ),
            normalize=_listing_record_semantic,
            label="listing",
        )
        actions = merge_family(
            lambda catalog: catalog.actions,
            key=lambda item: (
                item.action_identifier,
                item.effective_at,
                item.available_at,
            ),
            normalize=_action_semantic,
            label="corporate-action",
        )

        coverage = _reconciled_coverage(ranked)
        catalog = SecurityMasterCatalog(
            identifier=_required_text(identifier, field_name="identifier"),
            version=_required_text(version, field_name="version"),
            issuers=issuers,
            instruments=instruments,
            identifiers=identifiers,
            listings=listings,
            actions=actions,
            coverage=coverage,
        )
        return ReconciledSecurityMaster(
            catalog=catalog,
            report=SecurityMasterReconciliationReport(
                identifier=f"reconciliation:{catalog.identifier}",
                policy_version=self.policy.version,
                sources=tuple(item.coverage.source for item in ranked),
                selected_record_count=selected_count,
                duplicate_record_count=duplicate_count,
            ),
        )


class ReconciledSecurityMasterProvider:
    """Provider adapter that reconciles multiple independent source catalogs."""

    def __init__(
        self,
        providers: tuple[SecurityMasterProvider, ...],
        reconciler: SecurityMasterReconciler,
        *,
        name: str = "RECONCILED_SECURITY_MASTER",
        version: str = "security-master.reconciled.v1",
    ) -> None:
        if not isinstance(providers, tuple) or not providers:
            raise TypeError("providers must be a non-empty tuple")
        if not all(isinstance(item, SecurityMasterProvider) for item in providers):
            raise TypeError("providers must implement SecurityMasterProvider")
        if not isinstance(reconciler, SecurityMasterReconciler):
            raise TypeError("reconciler must be SecurityMasterReconciler")
        self.providers = providers
        self.reconciler = reconciler
        self._name = _required_text(name, field_name="name")
        self.version = _required_text(version, field_name="version")
        self.last_report: SecurityMasterReconciliationReport | None = None

    @property
    def name(self) -> str:
        return self._name

    def fetch_security_master_delivery(
        self,
        query: SecurityMasterIngestionQuery,
    ) -> SecurityMasterCatalogDelivery:
        if not isinstance(query, SecurityMasterIngestionQuery):
            raise TypeError("query must be SecurityMasterIngestionQuery")
        deliveries: list[SecurityMasterCatalogDelivery] = []
        for provider in self.providers:
            try:
                delivery = provider.fetch_security_master_delivery(query)
            except Exception as error:
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    raise
                raise SecurityMasterProviderError(
                    f"security-master provider {provider.name} failed during reconciliation"
                ) from error
            if not isinstance(delivery, SecurityMasterCatalogDelivery):
                raise SecurityMasterProviderError(
                    f"security-master provider {provider.name} returned an invalid delivery"
                )
            deliveries.append(delivery)
        result = self.reconciler.reconcile(
            tuple(item.catalog for item in deliveries),
            identifier=f"security-master:reconciled:{query.identifier}",
            version=self.version,
        )
        self.last_report = result.report
        composite = result.catalog.coverage
        catalog = replace(
            result.catalog,
            coverage=replace(
                composite,
                source=self.name,
                source_version=self.version,
            ),
        )
        return SecurityMasterCatalogDelivery(
            catalog=catalog,
            observed_at=min(item.observed_at for item in deliveries),
            retrieved_at=max(item.retrieved_at for item in deliveries),
            request_identifier=query.identifier,
        )


def _identifier_semantic(value) -> tuple[str, str]:
    return (value.scheme.value, value.value)


def _issuer_record_semantic(value: IssuerRecord) -> tuple[object, ...]:
    return (
        value.issuer.issuer_id,
        value.issuer.name,
        tuple(_identifier_semantic(item) for item in value.issuer.identifiers),
        value.effective_from,
        value.effective_until,
        value.available_at,
    )


def _instrument_record_semantic(value: InstrumentRecord) -> tuple[object, ...]:
    instrument = value.instrument
    return (
        instrument.instrument_id,
        instrument.name,
        instrument.asset_class.value,
        instrument.instrument_type.value,
        tuple(_identifier_semantic(item) for item in instrument.identifiers),
        instrument.issuer_id,
        instrument.base_asset,
        instrument.quote_currency,
        instrument.settlement_currency,
        instrument.network,
        value.effective_from,
        value.effective_until,
        value.available_at,
    )


def _identifier_assignment_semantic(
    value: IdentifierAssignment,
) -> tuple[object, ...]:
    return (
        value.assignment_identifier,
        value.entity_type.value,
        value.entity_identifier,
        _identifier_semantic(value.identifier),
        value.effective_from,
        value.effective_until,
        value.available_at,
    )


def _listing_record_semantic(value: ListingRecord) -> tuple[object, ...]:
    return (
        value.listing_identifier,
        value.instrument_identifier,
        value.venue,
        value.symbol,
        value.country_code,
        value.trading_calendar.value,
        value.status.value,
        value.primary,
        value.effective_from,
        value.effective_until,
        value.available_at,
    )


def _action_semantic(value: SecurityMasterAction) -> tuple[object, ...]:
    return (
        value.action_identifier,
        value.instrument_identifier,
        value.action_type.value,
        value.announced_at,
        value.effective_at,
        value.available_at,
        value.successor_instrument_identifier,
        value.new_symbol,
        value.new_venue,
        value.ratio,
    )


def _reconciled_coverage(
    catalogs: tuple[SecurityMasterCatalog, ...],
) -> SecurityMasterCoverage:
    values = tuple(item.coverage for item in catalogs)
    source = "+".join(item.source for item in values)
    source_version = "+".join(item.source_version for item in values)
    return SecurityMasterCoverage(
        source=source,
        source_version=source_version,
        licensed=all(item.licensed for item in values),
        complete_universe=all(item.complete_universe for item in values),
        point_in_time=all(item.point_in_time for item in values),
        historical_identifiers=all(item.historical_identifiers for item in values),
        listing_history=all(item.listing_history for item in values),
        delistings=all(item.delistings for item in values),
        corporate_actions=all(item.corporate_actions for item in values),
        provenance_complete=all(item.provenance_complete for item in values),
        service_level_defined=all(item.service_level_defined for item in values),
    )


def _quality_payload(value: SecurityMasterQualityReport) -> dict[str, Any]:
    return {
        "catalog_identifier": value.catalog_identifier,
        "policy_version": value.policy_version,
        "evaluated_at": value.evaluated_at.isoformat(),
        "as_of": value.as_of.isoformat(),
        "knowledge_cutoff": value.knowledge_cutoff.isoformat(),
        "source": value.source,
        "authoritative_coverage": value.authoritative_coverage,
        "integrity_verified": value.integrity_verified,
        "instrument_count": value.instrument_count,
        "active_listing_count": value.active_listing_count,
        "active_listing_ratio": value.active_listing_ratio,
        "classified_instrument_ratio": value.classified_instrument_ratio,
        "stable_identifier_ratio": value.stable_identifier_ratio,
        "duplicate_active_listing_count": value.duplicate_active_listing_count,
        "future_known_record_count": value.future_known_record_count,
        "source_observed_at": value.source_observed_at.isoformat(),
        "source_retrieved_at": value.source_retrieved_at.isoformat(),
        "latest_record_available_at": value.latest_record_available_at.isoformat(),
        "source_age_hours": value.source_age_hours,
        "coverage_deficiencies": list(value.coverage_deficiencies),
        "issues": list(value.issues),
    }


def _quality_from_payload(payload: dict[str, Any]) -> SecurityMasterQualityReport:
    return SecurityMasterQualityReport(
        catalog_identifier=str(payload["catalog_identifier"]),
        policy_version=str(payload["policy_version"]),
        evaluated_at=datetime.fromisoformat(str(payload["evaluated_at"])),
        as_of=datetime.fromisoformat(str(payload["as_of"])),
        knowledge_cutoff=datetime.fromisoformat(str(payload["knowledge_cutoff"])),
        source=str(payload["source"]),
        authoritative_coverage=bool(payload["authoritative_coverage"]),
        integrity_verified=bool(payload["integrity_verified"]),
        instrument_count=int(payload["instrument_count"]),
        active_listing_count=int(payload["active_listing_count"]),
        active_listing_ratio=float(payload["active_listing_ratio"]),
        classified_instrument_ratio=float(payload["classified_instrument_ratio"]),
        stable_identifier_ratio=float(payload["stable_identifier_ratio"]),
        duplicate_active_listing_count=int(payload["duplicate_active_listing_count"]),
        future_known_record_count=int(payload["future_known_record_count"]),
        source_observed_at=datetime.fromisoformat(str(payload["source_observed_at"])),
        source_retrieved_at=datetime.fromisoformat(str(payload["source_retrieved_at"])),
        latest_record_available_at=datetime.fromisoformat(
            str(payload["latest_record_available_at"])
        ),
        source_age_hours=float(payload["source_age_hours"]),
        coverage_deficiencies=tuple(payload["coverage_deficiencies"]),
        issues=tuple(payload["issues"]),
    )


def _ingestion_payload(value: SecurityMasterIngestionResult) -> dict[str, Any]:
    return {
        "identifier": value.identifier,
        "provider": value.provider,
        "catalog_identifier": value.catalog_identifier,
        "catalog_content_hash": value.catalog_content_hash,
        "ingested_at": value.ingested_at.isoformat(),
        "disposition": value.disposition.value,
        "activation_identifier": value.activation_identifier,
        "quality": _quality_payload(value.quality),
        "reasons": list(value.reasons),
    }


def _ingestion_from_payload(payload: dict[str, Any]) -> SecurityMasterIngestionResult:
    return SecurityMasterIngestionResult(
        identifier=str(payload["identifier"]),
        provider=str(payload["provider"]),
        catalog_identifier=str(payload["catalog_identifier"]),
        catalog_content_hash=str(payload["catalog_content_hash"]),
        ingested_at=datetime.fromisoformat(str(payload["ingested_at"])),
        disposition=SecurityMasterIngestionDisposition(payload["disposition"]),
        activation_identifier=payload.get("activation_identifier"),
        quality=_quality_from_payload(payload["quality"]),
        reasons=tuple(payload["reasons"]),
    )


def _activation_payload(value: SecurityMasterActivationRecord) -> dict[str, Any]:
    return {
        "identifier": value.identifier,
        "ingestion_identifier": value.ingestion_identifier,
        "catalog_identifier": value.catalog_identifier,
        "activated_at": value.activated_at.isoformat(),
        "policy_version": value.policy_version,
        "quality": _quality_payload(value.quality),
    }


def _activation_from_payload(payload: dict[str, Any]) -> SecurityMasterActivationRecord:
    return SecurityMasterActivationRecord(
        identifier=str(payload["identifier"]),
        ingestion_identifier=str(payload["ingestion_identifier"]),
        catalog_identifier=str(payload["catalog_identifier"]),
        activated_at=datetime.fromisoformat(str(payload["activated_at"])),
        policy_version=str(payload["policy_version"]),
        quality=_quality_from_payload(payload["quality"]),
    )


def _operation_hash(
    *,
    operation_identifier: str,
    operation_type: SecurityMasterOperationType,
    catalog_identifier: str,
    occurred_at: datetime,
    payload_json: str,
    previous_hash: str,
) -> str:
    material = "\n".join(
        (
            operation_identifier,
            operation_type.value,
            catalog_identifier,
            occurred_at.isoformat(),
            payload_json,
            previous_hash,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


__all__ = [
    "ReconciledSecurityMaster",
    "ReconciledSecurityMasterProvider",
    "SQLiteSecurityMasterOperationalStore",
    "SecurityMasterActivationError",
    "SecurityMasterActivationMode",
    "SecurityMasterActivationPolicy",
    "SecurityMasterActivationRecord",
    "SecurityMasterCatalogDelivery",
    "SecurityMasterIngestionDisposition",
    "SecurityMasterIngestionQuery",
    "SecurityMasterIngestionResult",
    "SecurityMasterIngestionService",
    "SecurityMasterOperationEvent",
    "SecurityMasterOperationType",
    "SecurityMasterOperationalStatus",
    "SecurityMasterProvider",
    "SecurityMasterProviderError",
    "SecurityMasterQualityReport",
    "SecurityMasterReconciliationError",
    "SecurityMasterReconciliationPolicy",
    "SecurityMasterReconciliationReport",
    "SecurityMasterReconciler",
]
