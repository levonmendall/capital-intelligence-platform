"""Temporal security-master and Version 1 universe construction contracts.

The security master separates stable issuer and instrument identity from symbols,
venues, and provider observations that change through time.  Every query carries
both an economic ``as_of`` timestamp and a ``knowledge_cutoff`` so historical
research cannot use identifiers, delistings, or corrections learned later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from cio.models import CandidateAssetClass, CandidateInstrument
from cio.universe import (
    RecommendationUniversePolicy,
    UniverseAssessment,
    UniverseDisposition,
)
from data.security import (
    AssetClass,
    Instrument,
    InstrumentIdentifier,
    Issuer,
    SecurityMasterError,
    SecurityMasterSnapshot,
    TradingCalendar,
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


def _optional_aware(value: object, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _aware(value, field_name=field_name)


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


def _interval(
    effective_from: object,
    effective_until: object,
) -> tuple[datetime, datetime | None]:
    start = _aware(effective_from, field_name="effective_from")
    end = _optional_aware(effective_until, field_name="effective_until")
    if end is not None and end <= start:
        raise ValueError("effective_until must follow effective_from")
    return start, end


def _contains(
    timestamp: datetime,
    effective_from: datetime,
    effective_until: datetime | None,
) -> bool:
    return effective_from <= timestamp and (
        effective_until is None or timestamp < effective_until
    )


class SecurityEntityType(str, Enum):
    ISSUER = "issuer"
    INSTRUMENT = "instrument"


class ListingStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELISTED = "delisted"


class SecurityMasterActionType(str, Enum):
    SYMBOL_CHANGE = "symbol_change"
    VENUE_CHANGE = "venue_change"
    RELISTING = "relisting"
    DELISTING = "delisting"
    MERGER = "merger"
    SPINOFF = "spinoff"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class SecurityMasterUniverseMembership:
    """Structural listing membership convertible to walk-forward evaluation."""

    symbol: str
    eligible_from: datetime
    eligible_until: datetime | None
    source_identifier: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "symbol",
            _required_text(self.symbol, field_name="symbol").upper(),
        )
        start, end = _interval(self.eligible_from, self.eligible_until)
        object.__setattr__(self, "eligible_from", start)
        object.__setattr__(self, "eligible_until", end)
        object.__setattr__(
            self,
            "source_identifier",
            _required_text(
                self.source_identifier,
                field_name="source_identifier",
            ),
        )

    def contains(self, timestamp: datetime) -> bool:
        resolved = _aware(timestamp, field_name="timestamp")
        return _contains(resolved, self.eligible_from, self.eligible_until)

    def to_walk_forward(self):
        """Create the evaluation-layer membership without a data-layer import cycle."""

        from evaluation.walk_forward import PointInTimeUniverseMembership

        return PointInTimeUniverseMembership(
            symbol=self.symbol,
            eligible_from=self.eligible_from,
            eligible_until=self.eligible_until,
            source_identifier=self.source_identifier,
        )


@dataclass(frozen=True, slots=True)
class SecurityMasterCoverage:
    """Disclosed source capabilities; incomplete coverage cannot claim authority."""

    source: str
    source_version: str
    licensed: bool
    complete_universe: bool
    point_in_time: bool
    historical_identifiers: bool
    listing_history: bool
    delistings: bool
    corporate_actions: bool
    provenance_complete: bool
    service_level_defined: bool

    def __post_init__(self) -> None:
        for field_name in ("source", "source_version"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "licensed",
            "complete_universe",
            "point_in_time",
            "historical_identifiers",
            "listing_history",
            "delistings",
            "corporate_actions",
            "provenance_complete",
            "service_level_defined",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")

    @property
    def deficiencies(self) -> tuple[str, ...]:
        checks = (
            ("licensed source", self.licensed),
            ("complete eligible-universe coverage", self.complete_universe),
            ("point-in-time availability", self.point_in_time),
            ("historical identifiers", self.historical_identifiers),
            ("listing and venue history", self.listing_history),
            ("delisted securities", self.delistings),
            ("corporate actions", self.corporate_actions),
            ("complete provenance", self.provenance_complete),
            ("service-level policy", self.service_level_defined),
        )
        return tuple(name for name, passed in checks if not passed)

    @property
    def authoritative(self) -> bool:
        return not self.deficiencies

    def require_authoritative(self) -> None:
        if self.deficiencies:
            raise SecurityMasterError(
                "security-master coverage is not authoritative: "
                + "; ".join(self.deficiencies)
            )


@dataclass(frozen=True, slots=True)
class IssuerRecord:
    record_identifier: str
    issuer: Issuer
    effective_from: datetime
    effective_until: datetime | None
    available_at: datetime
    source_identifier: str

    def __post_init__(self) -> None:
        for field_name in ("record_identifier", "source_identifier"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.issuer, Issuer):
            raise TypeError("issuer must be an Issuer")
        start, end = _interval(self.effective_from, self.effective_until)
        available = _aware(self.available_at, field_name="available_at")
        object.__setattr__(self, "effective_from", start)
        object.__setattr__(self, "effective_until", end)
        object.__setattr__(self, "available_at", available)

    def contains(self, timestamp: datetime) -> bool:
        return _contains(timestamp, self.effective_from, self.effective_until)


@dataclass(frozen=True, slots=True)
class InstrumentRecord:
    record_identifier: str
    instrument: Instrument
    effective_from: datetime
    effective_until: datetime | None
    available_at: datetime
    source_identifier: str

    def __post_init__(self) -> None:
        for field_name in ("record_identifier", "source_identifier"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.instrument, Instrument):
            raise TypeError("instrument must be an Instrument")
        start, end = _interval(self.effective_from, self.effective_until)
        available = _aware(self.available_at, field_name="available_at")
        object.__setattr__(self, "effective_from", start)
        object.__setattr__(self, "effective_until", end)
        object.__setattr__(self, "available_at", available)

    def contains(self, timestamp: datetime) -> bool:
        return _contains(timestamp, self.effective_from, self.effective_until)


@dataclass(frozen=True, slots=True)
class IdentifierAssignment:
    record_identifier: str
    assignment_identifier: str
    entity_type: SecurityEntityType
    entity_identifier: str
    identifier: InstrumentIdentifier
    effective_from: datetime
    effective_until: datetime | None
    available_at: datetime
    source_identifier: str

    def __post_init__(self) -> None:
        for field_name in (
            "record_identifier",
            "assignment_identifier",
            "entity_identifier",
            "source_identifier",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.entity_type, SecurityEntityType):
            raise TypeError("entity_type must be a SecurityEntityType")
        if not isinstance(self.identifier, InstrumentIdentifier):
            raise TypeError("identifier must be an InstrumentIdentifier")
        start, end = _interval(self.effective_from, self.effective_until)
        object.__setattr__(self, "effective_from", start)
        object.__setattr__(self, "effective_until", end)
        object.__setattr__(
            self,
            "available_at",
            _aware(self.available_at, field_name="available_at"),
        )

    def contains(self, timestamp: datetime) -> bool:
        return _contains(timestamp, self.effective_from, self.effective_until)


@dataclass(frozen=True, slots=True)
class ListingRecord:
    record_identifier: str
    listing_identifier: str
    instrument_identifier: str
    venue: str
    symbol: str
    country_code: str
    trading_calendar: TradingCalendar
    status: ListingStatus
    primary: bool
    effective_from: datetime
    effective_until: datetime | None
    available_at: datetime
    source_identifier: str

    def __post_init__(self) -> None:
        for field_name in (
            "record_identifier",
            "listing_identifier",
            "instrument_identifier",
            "venue",
            "symbol",
            "country_code",
            "source_identifier",
        ):
            value = _required_text(getattr(self, field_name), field_name=field_name)
            if field_name in {"venue", "symbol", "country_code"}:
                value = value.upper()
            object.__setattr__(self, field_name, value)
        if not isinstance(self.trading_calendar, TradingCalendar):
            raise TypeError("trading_calendar must be a TradingCalendar")
        if not isinstance(self.status, ListingStatus):
            raise TypeError("status must be a ListingStatus")
        if not isinstance(self.primary, bool):
            raise TypeError("primary must be a bool")
        start, end = _interval(self.effective_from, self.effective_until)
        object.__setattr__(self, "effective_from", start)
        object.__setattr__(self, "effective_until", end)
        object.__setattr__(
            self,
            "available_at",
            _aware(self.available_at, field_name="available_at"),
        )

    def contains(self, timestamp: datetime) -> bool:
        return _contains(timestamp, self.effective_from, self.effective_until)


@dataclass(frozen=True, slots=True)
class SecurityMasterAction:
    record_identifier: str
    action_identifier: str
    instrument_identifier: str
    action_type: SecurityMasterActionType
    announced_at: datetime
    effective_at: datetime
    available_at: datetime
    source_identifier: str
    successor_instrument_identifier: str | None = None
    new_symbol: str | None = None
    new_venue: str | None = None
    ratio: float | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "record_identifier",
            "action_identifier",
            "instrument_identifier",
            "source_identifier",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.action_type, SecurityMasterActionType):
            raise TypeError("action_type must be a SecurityMasterActionType")
        announced = _aware(self.announced_at, field_name="announced_at")
        effective = _aware(self.effective_at, field_name="effective_at")
        available = _aware(self.available_at, field_name="available_at")
        if available < announced:
            raise ValueError("available_at cannot predate announced_at")
        object.__setattr__(self, "announced_at", announced)
        object.__setattr__(self, "effective_at", effective)
        object.__setattr__(self, "available_at", available)
        for field_name in (
            "successor_instrument_identifier",
            "new_symbol",
            "new_venue",
        ):
            value = getattr(self, field_name)
            if value is not None:
                normalized = _required_text(value, field_name=field_name)
                if field_name in {"new_symbol", "new_venue"}:
                    normalized = normalized.upper()
                object.__setattr__(self, field_name, normalized)
        if self.ratio is not None:
            object.__setattr__(
                self,
                "ratio",
                _finite(self.ratio, field_name="ratio", minimum=0.0),
            )
        if self.action_type in {
            SecurityMasterActionType.MERGER,
            SecurityMasterActionType.SPINOFF,
        } and self.successor_instrument_identifier is None:
            raise ValueError("merger and spinoff actions require a successor instrument")
        if self.action_type is SecurityMasterActionType.SYMBOL_CHANGE and self.new_symbol is None:
            raise ValueError("symbol-change action requires new_symbol")
        if self.action_type is SecurityMasterActionType.VENUE_CHANGE and self.new_venue is None:
            raise ValueError("venue-change action requires new_venue")


@dataclass(frozen=True, slots=True)
class PointInTimeSecurityMasterSnapshot:
    identifier: str
    catalog_identifier: str
    catalog_version: str
    as_of: datetime
    knowledge_cutoff: datetime
    issuers: tuple[IssuerRecord, ...]
    instruments: tuple[InstrumentRecord, ...]
    identifiers: tuple[IdentifierAssignment, ...]
    listings: tuple[ListingRecord, ...]
    actions: tuple[SecurityMasterAction, ...]
    coverage: SecurityMasterCoverage

    def __post_init__(self) -> None:
        for field_name in ("identifier", "catalog_identifier", "catalog_version"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        as_of = _aware(self.as_of, field_name="as_of")
        cutoff = _aware(self.knowledge_cutoff, field_name="knowledge_cutoff")
        if cutoff < as_of:
            raise ValueError("knowledge_cutoff cannot predate as_of")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "knowledge_cutoff", cutoff)
        if not isinstance(self.coverage, SecurityMasterCoverage):
            raise TypeError("coverage must be SecurityMasterCoverage")
        expected = (
            ("issuers", IssuerRecord),
            ("instruments", InstrumentRecord),
            ("identifiers", IdentifierAssignment),
            ("listings", ListingRecord),
            ("actions", SecurityMasterAction),
        )
        for field_name, record_type in expected:
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, record_type) for item in values
            ):
                raise TypeError(f"{field_name} must contain {record_type.__name__} values")
            if any(item.available_at > cutoff for item in values):
                raise ValueError(f"{field_name} contains information unavailable at cutoff")
        instrument_ids = {item.instrument.instrument_id for item in self.instruments}
        issuer_ids = {item.issuer.issuer_id for item in self.issuers}
        for item in self.instruments:
            if item.instrument.issuer_id is not None and item.instrument.issuer_id not in issuer_ids:
                raise ValueError("snapshot instrument references an unavailable issuer")
        for item in self.listings:
            if item.instrument_identifier not in instrument_ids:
                raise ValueError("snapshot listing references an unavailable instrument")
        self._validate_listing_uniqueness()

    def _validate_listing_uniqueness(self) -> None:
        active = tuple(
            item for item in self.listings if item.status is ListingStatus.ACTIVE
        )
        venue_symbols = tuple((item.venue, item.symbol) for item in active)
        if len(venue_symbols) != len(set(venue_symbols)):
            raise ValueError("active venue-symbol listings must be unique")
        primary_instruments = tuple(
            item.instrument_identifier for item in active if item.primary
        )
        if len(primary_instruments) != len(set(primary_instruments)):
            raise ValueError("instrument cannot have multiple active primary listings")

    @property
    def source_record_identifiers(self) -> tuple[str, ...]:
        values = (
            *self.issuers,
            *self.instruments,
            *self.identifiers,
            *self.listings,
            *self.actions,
        )
        return tuple(item.record_identifier for item in values)

    def active_primary_listing(self, instrument_identifier: str) -> ListingRecord:
        normalized = _required_text(
            instrument_identifier,
            field_name="instrument_identifier",
        )
        matches = tuple(
            item
            for item in self.listings
            if item.instrument_identifier == normalized
            and item.primary
            and item.status is ListingStatus.ACTIVE
        )
        if not matches:
            raise SecurityMasterError(
                f"instrument {normalized!r} has no active primary listing"
            )
        if len(matches) > 1:
            raise SecurityMasterError(
                f"instrument {normalized!r} has ambiguous primary listings"
            )
        return matches[0]

    def resolve_symbol(self, symbol: str, *, venue: str | None = None) -> Instrument:
        normalized_symbol = _required_text(symbol, field_name="symbol").upper()
        normalized_venue = (
            _required_text(venue, field_name="venue").upper()
            if venue is not None
            else None
        )
        matches = tuple(
            item
            for item in self.listings
            if item.status is ListingStatus.ACTIVE
            and item.symbol == normalized_symbol
            and (normalized_venue is None or item.venue == normalized_venue)
        )
        if not matches:
            raise SecurityMasterError(
                f"symbol {normalized_symbol!r} is not active in this snapshot"
            )
        if len(matches) > 1:
            raise SecurityMasterError(
                f"symbol {normalized_symbol!r} is ambiguous; specify a venue"
            )
        by_id = {
            item.instrument.instrument_id: item.instrument for item in self.instruments
        }
        return by_id[matches[0].instrument_identifier]


@dataclass(frozen=True, slots=True)
class SecurityMasterCatalog:
    identifier: str
    version: str
    issuers: tuple[IssuerRecord, ...]
    instruments: tuple[InstrumentRecord, ...]
    identifiers: tuple[IdentifierAssignment, ...]
    listings: tuple[ListingRecord, ...]
    actions: tuple[SecurityMasterAction, ...]
    coverage: SecurityMasterCoverage

    def __post_init__(self) -> None:
        for field_name in ("identifier", "version"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.coverage, SecurityMasterCoverage):
            raise TypeError("coverage must be SecurityMasterCoverage")
        expected = (
            ("issuers", IssuerRecord),
            ("instruments", InstrumentRecord),
            ("identifiers", IdentifierAssignment),
            ("listings", ListingRecord),
            ("actions", SecurityMasterAction),
        )
        records: list[object] = []
        for field_name, record_type in expected:
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, record_type) for item in values
            ):
                raise TypeError(f"{field_name} must contain {record_type.__name__} values")
            records.extend(values)
        if not self.instruments:
            raise ValueError("security master must contain instruments")
        record_ids = tuple(item.record_identifier for item in records)
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("security-master record identifiers must be unique")
        instrument_ids = {item.instrument.instrument_id for item in self.instruments}
        issuer_ids = {item.issuer.issuer_id for item in self.issuers}
        for item in self.instruments:
            issuer_id = item.instrument.issuer_id
            if issuer_id is not None and issuer_id not in issuer_ids:
                raise ValueError("instrument references an unknown issuer")
        for item in self.identifiers:
            known = issuer_ids if item.entity_type is SecurityEntityType.ISSUER else instrument_ids
            if item.entity_identifier not in known:
                raise ValueError("identifier assignment references an unknown entity")
        for item in self.listings:
            if item.instrument_identifier not in instrument_ids:
                raise ValueError("listing references an unknown instrument")
        for item in self.actions:
            if item.instrument_identifier not in instrument_ids:
                raise ValueError("action references an unknown instrument")
            if (
                item.successor_instrument_identifier is not None
                and item.successor_instrument_identifier not in instrument_ids
            ):
                raise ValueError("action successor references an unknown instrument")

    @classmethod
    def from_current_snapshot(
        cls,
        snapshot: SecurityMasterSnapshot,
        *,
        identifier: str,
        version: str,
        coverage: SecurityMasterCoverage,
    ) -> "SecurityMasterCatalog":
        if not isinstance(snapshot, SecurityMasterSnapshot):
            raise TypeError("snapshot must be a SecurityMasterSnapshot")
        if not isinstance(coverage, SecurityMasterCoverage):
            raise TypeError("coverage must be SecurityMasterCoverage")
        issuer_records = tuple(
            IssuerRecord(
                record_identifier=f"{identifier}:issuer:{index}",
                issuer=issuer,
                effective_from=snapshot.observed_at,
                effective_until=None,
                available_at=snapshot.retrieved_at,
                source_identifier=f"{snapshot.source}:issuer:{issuer.issuer_id}",
            )
            for index, issuer in enumerate(snapshot.issuers, start=1)
        )
        instrument_records = tuple(
            InstrumentRecord(
                record_identifier=f"{identifier}:instrument:{index}",
                instrument=instrument,
                effective_from=snapshot.observed_at,
                effective_until=None,
                available_at=snapshot.retrieved_at,
                source_identifier=(
                    f"{snapshot.source}:instrument:{instrument.instrument_id}"
                ),
            )
            for index, instrument in enumerate(snapshot.instruments, start=1)
        )
        identifier_records: list[IdentifierAssignment] = []
        for entity_type, records in (
            (SecurityEntityType.ISSUER, snapshot.issuers),
            (SecurityEntityType.INSTRUMENT, snapshot.instruments),
        ):
            for entity in records:
                entity_identifier = (
                    entity.issuer_id
                    if entity_type is SecurityEntityType.ISSUER
                    else entity.instrument_id
                )
                for position, item in enumerate(entity.identifiers, start=1):
                    stable = f"{entity_type.value}:{entity_identifier}:{item.scheme.value}:{position}"
                    identifier_records.append(
                        IdentifierAssignment(
                            record_identifier=f"{identifier}:identifier:{stable}",
                            assignment_identifier=stable,
                            entity_type=entity_type,
                            entity_identifier=entity_identifier,
                            identifier=item,
                            effective_from=snapshot.observed_at,
                            effective_until=None,
                            available_at=snapshot.retrieved_at,
                            source_identifier=f"{snapshot.source}:{stable}",
                        )
                    )
        listing_records = tuple(
            ListingRecord(
                record_identifier=f"{identifier}:listing:{index}",
                listing_identifier=(
                    f"listing:{listing.instrument_id}:{listing.venue}:{listing.symbol}"
                ),
                instrument_identifier=listing.instrument_id,
                venue=listing.venue,
                symbol=listing.symbol,
                country_code="US",
                trading_calendar=listing.trading_calendar,
                status=ListingStatus.ACTIVE,
                primary=True,
                effective_from=snapshot.observed_at,
                effective_until=None,
                available_at=snapshot.retrieved_at,
                source_identifier=(
                    f"{snapshot.source}:listing:{listing.venue}:{listing.symbol}"
                ),
            )
            for index, listing in enumerate(snapshot.listings, start=1)
        )
        return cls(
            identifier=identifier,
            version=version,
            issuers=issuer_records,
            instruments=instrument_records,
            identifiers=tuple(identifier_records),
            listings=listing_records,
            actions=(),
            coverage=coverage,
        )

    def snapshot(
        self,
        *,
        as_of: datetime,
        knowledge_cutoff: datetime | None = None,
        require_authoritative: bool = False,
    ) -> PointInTimeSecurityMasterSnapshot:
        resolved_as_of = _aware(as_of, field_name="as_of")
        cutoff = _aware(
            knowledge_cutoff or resolved_as_of,
            field_name="knowledge_cutoff",
        )
        if cutoff < resolved_as_of:
            raise ValueError("knowledge_cutoff cannot predate as_of")
        if require_authoritative:
            self.coverage.require_authoritative()

        issuers = _latest_temporal(
            self.issuers,
            key=lambda item: item.issuer.issuer_id,
            as_of=resolved_as_of,
            cutoff=cutoff,
        )
        instruments = _latest_temporal(
            self.instruments,
            key=lambda item: item.instrument.instrument_id,
            as_of=resolved_as_of,
            cutoff=cutoff,
        )
        identifiers = _latest_temporal(
            self.identifiers,
            key=lambda item: item.assignment_identifier,
            as_of=resolved_as_of,
            cutoff=cutoff,
        )
        listings = _latest_temporal(
            self.listings,
            key=lambda item: item.listing_identifier,
            as_of=resolved_as_of,
            cutoff=cutoff,
        )
        actions = _latest_available(
            (
                item
                for item in self.actions
                if item.effective_at <= resolved_as_of
                and item.available_at <= cutoff
            ),
            key=lambda item: item.action_identifier,
        )
        return PointInTimeSecurityMasterSnapshot(
            identifier=(
                f"{self.identifier}:as-of:{resolved_as_of.isoformat()}:"
                f"known:{cutoff.isoformat()}"
            ),
            catalog_identifier=self.identifier,
            catalog_version=self.version,
            as_of=resolved_as_of,
            knowledge_cutoff=cutoff,
            issuers=issuers,
            instruments=instruments,
            identifiers=identifiers,
            listings=listings,
            actions=actions,
            coverage=self.coverage,
        )


def _latest_temporal(values, *, key, as_of: datetime, cutoff: datetime):
    return _latest_available(
        (
            item
            for item in values
            if item.available_at <= cutoff and item.contains(as_of)
        ),
        key=key,
    )


def _latest_available(values, *, key):
    selected: dict[object, object] = {}
    for item in values:
        group = key(item)
        current = selected.get(group)
        if current is None or (
            item.available_at,
            item.record_identifier,
        ) > (
            current.available_at,
            current.record_identifier,
        ):
            selected[group] = item
    return tuple(selected[group] for group in sorted(selected, key=str))


@dataclass(frozen=True, slots=True)
class SecurityMasterMarketMetrics:
    identifier: str
    instrument_identifier: str
    observed_at: datetime
    available_at: datetime
    average_daily_dollar_volume: float
    analytical_coverage: float
    is_us_treasury: bool = False
    effective_duration_years: float | None = None

    def __post_init__(self) -> None:
        for field_name in ("identifier", "instrument_identifier"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        observed = _aware(self.observed_at, field_name="observed_at")
        available = _aware(self.available_at, field_name="available_at")
        if available < observed:
            raise ValueError("available_at cannot predate observed_at")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(
            self,
            "average_daily_dollar_volume",
            _finite(
                self.average_daily_dollar_volume,
                field_name="average_daily_dollar_volume",
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "analytical_coverage",
            _finite(
                self.analytical_coverage,
                field_name="analytical_coverage",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        if not isinstance(self.is_us_treasury, bool):
            raise TypeError("is_us_treasury must be a bool")
        if self.effective_duration_years is not None:
            object.__setattr__(
                self,
                "effective_duration_years",
                _finite(
                    self.effective_duration_years,
                    field_name="effective_duration_years",
                    minimum=0.0,
                ),
            )


@dataclass(frozen=True, slots=True)
class Version1UniverseConstituent:
    instrument: CandidateInstrument
    assessment: UniverseAssessment
    listing_identifier: str
    metrics_identifier: str
    membership: SecurityMasterUniverseMembership

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, CandidateInstrument):
            raise TypeError("instrument must be a CandidateInstrument")
        if not isinstance(self.assessment, UniverseAssessment):
            raise TypeError("assessment must be a UniverseAssessment")
        if not self.assessment.direct_recommendation_allowed:
            raise ValueError("constituent must be eligible for direct recommendation")
        if not isinstance(self.membership, SecurityMasterUniverseMembership):
            raise TypeError("membership must be SecurityMasterUniverseMembership")
        for field_name in ("listing_identifier", "metrics_identifier"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )


@dataclass(frozen=True, slots=True)
class Version1UniverseExclusion:
    instrument_identifier: str
    symbol: str | None
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_identifier",
            _required_text(
                self.instrument_identifier,
                field_name="instrument_identifier",
            ),
        )
        if self.symbol is not None:
            object.__setattr__(
                self,
                "symbol",
                _required_text(self.symbol, field_name="symbol").upper(),
            )
        if not isinstance(self.reasons, tuple) or not self.reasons or not all(
            isinstance(item, str) and item.strip() for item in self.reasons
        ):
            raise TypeError("reasons must contain non-empty strings")


@dataclass(frozen=True, slots=True)
class Version1UniverseSnapshot:
    identifier: str
    as_of: datetime
    knowledge_cutoff: datetime
    security_master_snapshot_identifier: str
    policy_version: str
    authoritative: bool
    constituents: tuple[Version1UniverseConstituent, ...]
    exclusions: tuple[Version1UniverseExclusion, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "security_master_snapshot_identifier",
            "policy_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.as_of, field_name="as_of")
        _aware(self.knowledge_cutoff, field_name="knowledge_cutoff")
        if not isinstance(self.authoritative, bool):
            raise TypeError("authoritative must be a bool")
        if not isinstance(self.constituents, tuple) or not all(
            isinstance(item, Version1UniverseConstituent)
            for item in self.constituents
        ):
            raise TypeError("constituents must contain Version1UniverseConstituent values")
        if not isinstance(self.exclusions, tuple) or not all(
            isinstance(item, Version1UniverseExclusion) for item in self.exclusions
        ):
            raise TypeError("exclusions must contain Version1UniverseExclusion values")
        instrument_ids = tuple(item.instrument.instrument_id for item in self.constituents)
        if len(instrument_ids) != len(set(instrument_ids)):
            raise ValueError("universe constituents cannot contain duplicate instruments")


class Version1UniverseBuilder:
    """Build a reproducible direct-recommendation universe from one master snapshot."""

    def __init__(
        self,
        policy: RecommendationUniversePolicy | None = None,
    ) -> None:
        self.policy = policy or RecommendationUniversePolicy()

    def build(
        self,
        snapshot: PointInTimeSecurityMasterSnapshot,
        metrics: tuple[SecurityMasterMarketMetrics, ...],
        *,
        require_authoritative: bool = False,
    ) -> Version1UniverseSnapshot:
        if not isinstance(snapshot, PointInTimeSecurityMasterSnapshot):
            raise TypeError("snapshot must be PointInTimeSecurityMasterSnapshot")
        if not isinstance(metrics, tuple) or not all(
            isinstance(item, SecurityMasterMarketMetrics) for item in metrics
        ):
            raise TypeError("metrics must contain SecurityMasterMarketMetrics values")
        if require_authoritative:
            snapshot.coverage.require_authoritative()
        metric_by_instrument: dict[str, SecurityMasterMarketMetrics] = {}
        for item in metrics:
            if item.instrument_identifier in metric_by_instrument:
                raise ValueError("metrics cannot contain duplicate instruments")
            if item.observed_at > snapshot.as_of:
                raise ValueError("metrics observation cannot follow universe as_of")
            if item.available_at > snapshot.knowledge_cutoff:
                raise ValueError("metrics were unavailable at the knowledge cutoff")
            metric_by_instrument[item.instrument_identifier] = item

        constituents: list[Version1UniverseConstituent] = []
        exclusions: list[Version1UniverseExclusion] = []
        for record in snapshot.instruments:
            instrument = record.instrument
            try:
                listing = snapshot.active_primary_listing(instrument.instrument_id)
            except SecurityMasterError as error:
                exclusions.append(
                    Version1UniverseExclusion(
                        instrument_identifier=instrument.instrument_id,
                        symbol=None,
                        reasons=(str(error),),
                    )
                )
                continue
            metric = metric_by_instrument.get(instrument.instrument_id)
            if metric is None:
                exclusions.append(
                    Version1UniverseExclusion(
                        instrument_identifier=instrument.instrument_id,
                        symbol=listing.symbol,
                        reasons=("point-in-time liquidity and analytical coverage are unavailable",),
                    )
                )
                continue
            candidate = CandidateInstrument(
                instrument_id=instrument.instrument_id,
                symbol=listing.symbol,
                name=instrument.name,
                asset_class=_candidate_asset_class(instrument.asset_class, metric),
                venue=listing.venue,
                country_code=listing.country_code,
                average_daily_dollar_volume=metric.average_daily_dollar_volume,
                data_age_hours=max(
                    0.0,
                    (snapshot.as_of - metric.observed_at).total_seconds() / 3600.0,
                ),
                analytical_coverage=metric.analytical_coverage,
                security_master_snapshot_identifier=snapshot.identifier,
                security_master_record_identifiers=tuple(
                    dict.fromkeys(
                        (
                            record.record_identifier,
                            listing.record_identifier,
                        )
                    )
                ),
                is_us_treasury=metric.is_us_treasury,
                effective_duration_years=metric.effective_duration_years,
            )
            assessment = self.policy.evaluate(candidate)
            if assessment.disposition is not UniverseDisposition.DIRECT_RECOMMENDATION:
                exclusions.append(
                    Version1UniverseExclusion(
                        instrument_identifier=instrument.instrument_id,
                        symbol=listing.symbol,
                        reasons=assessment.reasons,
                    )
                )
                continue
            effective_until = _earliest(record.effective_until, listing.effective_until)
            membership = SecurityMasterUniverseMembership(
                symbol=listing.symbol,
                eligible_from=max(record.effective_from, listing.effective_from),
                eligible_until=effective_until,
                source_identifier=(
                    f"{snapshot.identifier}:{listing.record_identifier}:"
                    f"{metric.identifier}:{self.policy.version}"
                ),
            )
            constituents.append(
                Version1UniverseConstituent(
                    instrument=candidate,
                    assessment=assessment,
                    listing_identifier=listing.listing_identifier,
                    metrics_identifier=metric.identifier,
                    membership=membership,
                )
            )
        constituents.sort(key=lambda item: (item.instrument.symbol, item.instrument.instrument_id))
        exclusions.sort(key=lambda item: (item.symbol or "", item.instrument_identifier))
        return Version1UniverseSnapshot(
            identifier=(
                f"version1-universe:{snapshot.as_of.isoformat()}:"
                f"known:{snapshot.knowledge_cutoff.isoformat()}"
            ),
            as_of=snapshot.as_of,
            knowledge_cutoff=snapshot.knowledge_cutoff,
            security_master_snapshot_identifier=snapshot.identifier,
            policy_version=self.policy.version,
            authoritative=snapshot.coverage.authoritative,
            constituents=tuple(constituents),
            exclusions=tuple(exclusions),
        )


def _candidate_asset_class(
    asset_class: AssetClass,
    metric: SecurityMasterMarketMetrics,
) -> CandidateAssetClass:
    if asset_class is AssetClass.EQUITY:
        return CandidateAssetClass.US_EQUITY
    if asset_class is AssetClass.ETF:
        return CandidateAssetClass.US_ETF
    if asset_class is AssetClass.FIXED_INCOME and metric.is_us_treasury:
        return CandidateAssetClass.CASH_EQUIVALENT
    if asset_class is AssetClass.FIXED_INCOME:
        return CandidateAssetClass.FIXED_INCOME
    if asset_class is AssetClass.COMMODITY:
        return CandidateAssetClass.COMMODITY
    if asset_class is AssetClass.FX:
        return CandidateAssetClass.FX
    if asset_class is AssetClass.CRYPTO:
        return CandidateAssetClass.CRYPTO
    return CandidateAssetClass.OTHER


def _earliest(first: datetime | None, second: datetime | None) -> datetime | None:
    if first is None:
        return second
    if second is None:
        return first
    return min(first, second)


__all__ = [
    "IdentifierAssignment",
    "InstrumentRecord",
    "IssuerRecord",
    "ListingRecord",
    "ListingStatus",
    "PointInTimeSecurityMasterSnapshot",
    "SecurityEntityType",
    "SecurityMasterAction",
    "SecurityMasterActionType",
    "SecurityMasterCatalog",
    "SecurityMasterCoverage",
    "SecurityMasterMarketMetrics",
    "SecurityMasterUniverseMembership",
    "Version1UniverseBuilder",
    "Version1UniverseConstituent",
    "Version1UniverseExclusion",
    "Version1UniverseSnapshot",
]
