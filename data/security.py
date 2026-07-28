"""Immutable multi-asset identity and point-in-time master contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite


class SecurityMasterError(LookupError):
    """Raised when an instrument identity cannot be resolved safely."""


class AssetClass(str, Enum):
    """Broad economic exposure of an instrument."""

    UNKNOWN = "unknown"
    EQUITY = "equity"
    ETF = "etf"
    FIXED_INCOME = "fixed_income"
    COMMODITY = "commodity"
    FX = "fx"
    CRYPTO = "crypto"
    REAL_ESTATE = "real_estate"
    VOLATILITY = "volatility"
    ALTERNATIVE = "alternative"


class InstrumentType(str, Enum):
    """Tradable instrument structure."""

    COMMON_STOCK = "common_stock"
    PREFERRED_STOCK = "preferred_stock"
    FUND = "fund"
    BOND = "bond"
    SPOT = "spot"
    TOKEN = "token"
    STABLECOIN = "stablecoin"
    FUTURE = "future"
    PERPETUAL = "perpetual"
    OPTION = "option"
    OTHER = "other"


class IdentifierScheme(str, Enum):
    """Namespaces used to identify issuers and instruments."""

    CIK = "cik"
    TICKER = "ticker"
    ISIN = "isin"
    FIGI = "figi"
    CUSIP = "cusip"
    CONTRACT_ADDRESS = "contract_address"
    PROVIDER = "provider"


class TradingCalendar(str, Enum):
    """High-level trading-session behavior."""

    EXCHANGE = "exchange"
    CONTINUOUS = "continuous_24_7"


def normalize_cik(value: object) -> str:
    """Return a canonical ten-digit SEC Central Index Key."""

    if isinstance(value, bool):
        raise TypeError("cik must be an int or digit string")
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise TypeError("cik must be an int or digit string")
    if not text.isdigit() or not 1 <= len(text) <= 10:
        raise ValueError("cik must contain between 1 and 10 digits")
    return text.zfill(10)


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _optional_text(
    value: object,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name=field_name)


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class InstrumentIdentifier:
    """One namespaced identity observed for an issuer or instrument."""

    scheme: IdentifierScheme
    value: str
    provider: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scheme, IdentifierScheme):
            raise TypeError("scheme must be an IdentifierScheme")
        value = _required_text(self.value, field_name="value")
        if self.scheme is IdentifierScheme.CIK:
            value = normalize_cik(value)
        elif self.scheme in {
            IdentifierScheme.TICKER,
            IdentifierScheme.ISIN,
            IdentifierScheme.FIGI,
            IdentifierScheme.CUSIP,
        }:
            value = value.upper()
        object.__setattr__(self, "value", value)
        object.__setattr__(
            self,
            "provider",
            _optional_text(self.provider, field_name="provider"),
        )


@dataclass(frozen=True, slots=True)
class Issuer:
    """Economic or legal issuer distinct from its tradable instruments."""

    issuer_id: str
    name: str
    identifiers: tuple[InstrumentIdentifier, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "issuer_id",
            _required_text(self.issuer_id, field_name="issuer_id"),
        )
        object.__setattr__(
            self,
            "name",
            _required_text(self.name, field_name="name"),
        )
        _validate_identifiers(self.identifiers)


@dataclass(frozen=True, slots=True)
class Instrument:
    """Provider-neutral tradable instrument identity."""

    instrument_id: str
    name: str
    asset_class: AssetClass
    instrument_type: InstrumentType
    identifiers: tuple[InstrumentIdentifier, ...] = ()
    issuer_id: str | None = None
    base_asset: str | None = None
    quote_currency: str | None = None
    settlement_currency: str | None = None
    network: str | None = None
    economic_exposure: AssetClass | None = None
    leverage_multiplier: float = 1.0
    uses_derivatives: bool = False
    replication_method: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_id",
            _required_text(
                self.instrument_id,
                field_name="instrument_id",
            ),
        )
        object.__setattr__(
            self,
            "name",
            _required_text(self.name, field_name="name"),
        )
        if not isinstance(self.asset_class, AssetClass):
            raise TypeError("asset_class must be an AssetClass")
        if not isinstance(self.instrument_type, InstrumentType):
            raise TypeError(
                "instrument_type must be an InstrumentType"
            )
        _validate_identifiers(self.identifiers)
        for field_name in (
            "issuer_id",
            "base_asset",
            "quote_currency",
            "settlement_currency",
            "network",
        ):
            value = _optional_text(
                getattr(self, field_name),
                field_name=field_name,
            )
            if field_name in {
                "base_asset",
                "quote_currency",
                "settlement_currency",
            } and value is not None:
                value = value.upper()
            object.__setattr__(self, field_name, value)

        if self.instrument_type in {
            InstrumentType.SPOT,
            InstrumentType.PERPETUAL,
            InstrumentType.FUTURE,
        } and (
            self.base_asset is None
            or self.quote_currency is None
        ):
            raise ValueError(
                "spot and derivative instruments require "
                "base_asset and quote_currency"
            )
        if (
            self.asset_class is AssetClass.CRYPTO
            and self.instrument_type
            in {
                InstrumentType.COMMON_STOCK,
                InstrumentType.PREFERRED_STOCK,
            }
        ):
            raise ValueError(
                "crypto instruments cannot use an equity type"
            )
        if self.economic_exposure is not None and not isinstance(
            self.economic_exposure,
            AssetClass,
        ):
            raise TypeError("economic_exposure must be an AssetClass")
        if isinstance(self.leverage_multiplier, bool) or not isinstance(
            self.leverage_multiplier,
            (int, float),
        ):
            raise TypeError("leverage_multiplier must be numeric")
        leverage = float(self.leverage_multiplier)
        if not isfinite(leverage) or not -10.0 <= leverage <= 10.0:
            raise ValueError(
                "leverage_multiplier must be finite and between -10 and 10"
            )
        if abs(leverage) < 0.00000001:
            raise ValueError("leverage_multiplier cannot be zero")
        object.__setattr__(self, "leverage_multiplier", leverage)
        if not isinstance(self.uses_derivatives, bool):
            raise TypeError("uses_derivatives must be a bool")
        object.__setattr__(
            self,
            "replication_method",
            _optional_text(
                self.replication_method,
                field_name="replication_method",
            ),
        )


@dataclass(frozen=True, slots=True)
class VenueListing:
    """Venue-specific symbol and trading behavior for an instrument."""

    instrument_id: str
    venue: str
    symbol: str
    trading_calendar: TradingCalendar

    def __post_init__(self) -> None:
        for field_name in ("instrument_id", "venue", "symbol"):
            value = _required_text(
                getattr(self, field_name),
                field_name=field_name,
            )
            if field_name in {"venue", "symbol"}:
                value = value.upper()
            object.__setattr__(self, field_name, value)
        if not isinstance(self.trading_calendar, TradingCalendar):
            raise TypeError(
                "trading_calendar must be a TradingCalendar"
            )


@dataclass(frozen=True, slots=True)
class SecurityMasterSnapshot:
    """Immutable multi-asset identities known at one retrieval boundary."""

    observed_at: datetime
    retrieved_at: datetime
    issuers: tuple[Issuer, ...]
    instruments: tuple[Instrument, ...]
    listings: tuple[VenueListing, ...]
    source: str

    def __post_init__(self) -> None:
        observed_at = _aware_datetime(
            self.observed_at,
            field_name="observed_at",
        )
        retrieved_at = _aware_datetime(
            self.retrieved_at,
            field_name="retrieved_at",
        )
        if observed_at > retrieved_at:
            raise ValueError(
                "observed_at cannot be later than retrieved_at"
            )
        _validate_tuple(
            self.issuers,
            Issuer,
            field_name="issuers",
            allow_empty=True,
        )
        _validate_tuple(
            self.instruments,
            Instrument,
            field_name="instruments",
        )
        _validate_tuple(
            self.listings,
            VenueListing,
            field_name="listings",
        )
        object.__setattr__(
            self,
            "source",
            _required_text(self.source, field_name="source"),
        )

        issuer_ids = tuple(issuer.issuer_id for issuer in self.issuers)
        instrument_ids = tuple(
            instrument.instrument_id
            for instrument in self.instruments
        )
        _require_unique(issuer_ids, field_name="issuer IDs")
        _require_unique(
            instrument_ids,
            field_name="instrument IDs",
        )
        instrument_id_set = set(instrument_ids)
        issuer_id_set = set(issuer_ids)
        for instrument in self.instruments:
            if (
                instrument.issuer_id is not None
                and instrument.issuer_id not in issuer_id_set
            ):
                raise ValueError(
                    "instrument references an unknown issuer"
                )
        for listing in self.listings:
            if listing.instrument_id not in instrument_id_set:
                raise ValueError(
                    "listing references an unknown instrument"
                )
        listing_keys = tuple(
            (listing.venue, listing.symbol)
            for listing in self.listings
        )
        _require_unique(
            listing_keys,
            field_name="venue-symbol listings",
        )

    def resolve_symbol(
        self,
        symbol: str,
        *,
        venue: str | None = None,
    ) -> Instrument:
        """Resolve a symbol without silently crossing venues."""

        normalized_symbol = _required_text(
            symbol,
            field_name="symbol",
        ).upper()
        normalized_venue = (
            _required_text(venue, field_name="venue").upper()
            if venue is not None
            else None
        )
        matches = tuple(
            listing
            for listing in self.listings
            if listing.symbol == normalized_symbol
            and (
                normalized_venue is None
                or listing.venue == normalized_venue
            )
        )
        if not matches:
            raise SecurityMasterError(
                f"symbol {normalized_symbol!r} is not in this snapshot"
            )
        if len(matches) > 1:
            raise SecurityMasterError(
                f"symbol {normalized_symbol!r} is ambiguous; "
                "specify a venue"
            )
        instrument_by_id = {
            instrument.instrument_id: instrument
            for instrument in self.instruments
        }
        return instrument_by_id[matches[0].instrument_id]

    def instruments_for_issuer(
        self,
        issuer_id: str,
    ) -> tuple[Instrument, ...]:
        """Return every instrument associated with an issuer."""

        normalized = _required_text(
            issuer_id,
            field_name="issuer_id",
        )
        return tuple(
            instrument
            for instrument in self.instruments
            if instrument.issuer_id == normalized
        )


def _validate_identifiers(
    identifiers: tuple[InstrumentIdentifier, ...],
) -> None:
    _validate_tuple(
        identifiers,
        InstrumentIdentifier,
        field_name="identifiers",
        allow_empty=True,
    )
    keys = tuple(
        (identifier.scheme, identifier.provider, identifier.value)
        for identifier in identifiers
    )
    _require_unique(keys, field_name="identifiers")


def _validate_tuple(
    values: object,
    expected_type: type,
    *,
    field_name: str,
    allow_empty: bool = False,
) -> None:
    if not isinstance(values, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    if not allow_empty and not values:
        raise ValueError(f"{field_name} cannot be empty")
    if not all(isinstance(value, expected_type) for value in values):
        raise TypeError(
            f"{field_name} must contain {expected_type.__name__} values"
        )


def _require_unique(
    values: tuple[object, ...],
    *,
    field_name: str,
) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must be unique")
