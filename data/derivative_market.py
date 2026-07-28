"""Canonical derivative contracts, margin records, and volatility surfaces.

Provider payloads are normalized into these records before they can satisfy the
all-market paper readiness gate.  The module intentionally does not infer
margin from volatility or fabricate option quotes from settlement prices.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Iterable


class DerivativeDataError(RuntimeError):
    """Raised when derivative data cannot be normalized or certified."""


class DerivativeContractType(str, Enum):
    FUTURE = "future"
    OPTION = "option"
    OPTION_ON_FUTURE = "option_on_future"


class OptionRight(str, Enum):
    CALL = "call"
    PUT = "put"


class ExerciseStyle(str, Enum):
    EUROPEAN = "european"
    AMERICAN = "american"


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


def _finite_positive(value: object, *, field_name: str, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if normalized < 0 or (not allow_zero and normalized == 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{field_name} must be {qualifier}")
    return normalized


@dataclass(frozen=True, slots=True)
class DerivativeContractRecord:
    instrument_id: str
    parent_instrument_id: str
    underlying_instrument_id: str
    venue: str
    currency: str
    contract_type: DerivativeContractType
    multiplier: float
    minimum_tick: float
    listing_at: datetime
    expiration_at: datetime
    observed_at: datetime
    available_at: datetime
    source_identifier: str
    strike: float | None = None
    option_right: OptionRight | None = None
    exercise_style: ExerciseStyle | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "instrument_id",
            "parent_instrument_id",
            "underlying_instrument_id",
            "venue",
            "currency",
            "source_identifier",
        ):
            value = _text(getattr(self, field_name), field_name=field_name)
            if field_name in {"venue", "currency"}:
                value = value.upper()
            object.__setattr__(self, field_name, value)
        if not isinstance(self.contract_type, DerivativeContractType):
            raise TypeError("contract_type must be DerivativeContractType")
        object.__setattr__(
            self, "multiplier", _finite_positive(self.multiplier, field_name="multiplier")
        )
        object.__setattr__(
            self, "minimum_tick", _finite_positive(self.minimum_tick, field_name="minimum_tick")
        )
        listing = _aware(self.listing_at, field_name="listing_at")
        expiration = _aware(self.expiration_at, field_name="expiration_at")
        observed = _aware(self.observed_at, field_name="observed_at")
        available = _aware(self.available_at, field_name="available_at")
        if listing >= expiration:
            raise ValueError("listing_at must precede expiration_at")
        if observed > available:
            raise ValueError("observed_at cannot follow available_at")
        is_option = self.contract_type in {
            DerivativeContractType.OPTION,
            DerivativeContractType.OPTION_ON_FUTURE,
        }
        if is_option:
            if self.strike is None:
                raise ValueError("option contracts require strike")
            object.__setattr__(
                self,
                "strike",
                _finite_positive(self.strike, field_name="strike"),
            )
            if not isinstance(self.option_right, OptionRight):
                raise TypeError("option contracts require OptionRight")
            if not isinstance(self.exercise_style, ExerciseStyle):
                raise TypeError("option contracts require ExerciseStyle")
        elif any(
            value is not None
            for value in (self.strike, self.option_right, self.exercise_style)
        ):
            raise ValueError("future contracts cannot define option fields")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DerivativeContractRecord":
        contract_type = DerivativeContractType(str(payload["contract_type"]))
        return cls(
            instrument_id=str(payload["instrument_id"]),
            parent_instrument_id=str(payload["parent_instrument_id"]),
            underlying_instrument_id=str(payload["underlying_instrument_id"]),
            venue=str(payload["venue"]),
            currency=str(payload["currency"]),
            contract_type=contract_type,
            multiplier=float(payload["multiplier"]),
            minimum_tick=float(payload["minimum_tick"]),
            listing_at=datetime.fromisoformat(str(payload["listing_at"]).replace("Z", "+00:00")),
            expiration_at=datetime.fromisoformat(str(payload["expiration_at"]).replace("Z", "+00:00")),
            observed_at=datetime.fromisoformat(str(payload["observed_at"]).replace("Z", "+00:00")),
            available_at=datetime.fromisoformat(str(payload["available_at"]).replace("Z", "+00:00")),
            source_identifier=str(payload["source_identifier"]),
            strike=None if payload.get("strike") is None else float(payload["strike"]),
            option_right=(
                None
                if payload.get("option_right") is None
                else OptionRight(str(payload["option_right"]))
            ),
            exercise_style=(
                None
                if payload.get("exercise_style") is None
                else ExerciseStyle(str(payload["exercise_style"]))
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "derivative-contract-record.v1",
            "instrument_id": self.instrument_id,
            "parent_instrument_id": self.parent_instrument_id,
            "underlying_instrument_id": self.underlying_instrument_id,
            "venue": self.venue,
            "currency": self.currency,
            "contract_type": self.contract_type.value,
            "multiplier": self.multiplier,
            "minimum_tick": self.minimum_tick,
            "listing_at": self.listing_at.isoformat(),
            "expiration_at": self.expiration_at.isoformat(),
            "observed_at": self.observed_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "source_identifier": self.source_identifier,
            "strike": self.strike,
            "option_right": None if self.option_right is None else self.option_right.value,
            "exercise_style": None if self.exercise_style is None else self.exercise_style.value,
        }


@dataclass(frozen=True, slots=True)
class MarginRequirementRecord:
    instrument_id: str
    venue: str
    currency: str
    initial_margin: float
    maintenance_margin: float
    effective_at: datetime
    available_at: datetime
    methodology_identifier: str
    source_identifier: str

    def __post_init__(self) -> None:
        for field_name in (
            "instrument_id",
            "venue",
            "currency",
            "methodology_identifier",
            "source_identifier",
        ):
            value = _text(getattr(self, field_name), field_name=field_name)
            if field_name in {"venue", "currency"}:
                value = value.upper()
            object.__setattr__(self, field_name, value)
        initial = _finite_positive(self.initial_margin, field_name="initial_margin", allow_zero=True)
        maintenance = _finite_positive(
            self.maintenance_margin,
            field_name="maintenance_margin",
            allow_zero=True,
        )
        if maintenance > initial:
            raise ValueError("maintenance_margin cannot exceed initial_margin")
        object.__setattr__(self, "initial_margin", initial)
        object.__setattr__(self, "maintenance_margin", maintenance)
        _aware(self.effective_at, field_name="effective_at")
        _aware(self.available_at, field_name="available_at")
        # Clearing houses commonly publish margin schedules before their
        # effective time.  Availability controls whether the schedule may be
        # used in a decision; effective_at controls which schedule applies to
        # the simulated trade.  Either temporal ordering is therefore valid.

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MarginRequirementRecord":
        return cls(
            instrument_id=str(payload["instrument_id"]),
            venue=str(payload["venue"]),
            currency=str(payload["currency"]),
            initial_margin=float(payload["initial_margin"]),
            maintenance_margin=float(payload["maintenance_margin"]),
            effective_at=datetime.fromisoformat(str(payload["effective_at"]).replace("Z", "+00:00")),
            available_at=datetime.fromisoformat(str(payload["available_at"]).replace("Z", "+00:00")),
            methodology_identifier=str(payload["methodology_identifier"]),
            source_identifier=str(payload["source_identifier"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "margin-requirement-record.v1",
            "instrument_id": self.instrument_id,
            "venue": self.venue,
            "currency": self.currency,
            "initial_margin": self.initial_margin,
            "maintenance_margin": self.maintenance_margin,
            "effective_at": self.effective_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "methodology_identifier": self.methodology_identifier,
            "source_identifier": self.source_identifier,
        }


@dataclass(frozen=True, slots=True)
class OptionQuoteRecord:
    instrument_id: str
    underlying_instrument_id: str
    expiration_at: datetime
    strike: float
    option_right: OptionRight
    exercise_style: ExerciseStyle
    bid: float
    ask: float
    underlying_price: float
    risk_free_rate: float
    dividend_yield: float
    observed_at: datetime
    available_at: datetime
    source_identifier: str

    def __post_init__(self) -> None:
        for field_name in (
            "instrument_id",
            "underlying_instrument_id",
            "source_identifier",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.option_right, OptionRight):
            raise TypeError("option_right must be OptionRight")
        if not isinstance(self.exercise_style, ExerciseStyle):
            raise TypeError("exercise_style must be ExerciseStyle")
        object.__setattr__(self, "strike", _finite_positive(self.strike, field_name="strike"))
        bid = _finite_positive(self.bid, field_name="bid", allow_zero=True)
        ask = _finite_positive(self.ask, field_name="ask", allow_zero=True)
        if bid > ask:
            raise ValueError("bid cannot exceed ask")
        if ask == 0:
            raise ValueError("ask must be positive")
        object.__setattr__(self, "bid", bid)
        object.__setattr__(self, "ask", ask)
        object.__setattr__(
            self,
            "underlying_price",
            _finite_positive(self.underlying_price, field_name="underlying_price"),
        )
        for field_name in ("risk_free_rate", "dividend_yield"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be numeric")
            normalized = float(value)
            if not math.isfinite(normalized) or not -1.0 <= normalized <= 1.0:
                raise ValueError(f"{field_name} must be finite and between -1 and 1")
            object.__setattr__(self, field_name, normalized)
        expiration = _aware(self.expiration_at, field_name="expiration_at")
        observed = _aware(self.observed_at, field_name="observed_at")
        available = _aware(self.available_at, field_name="available_at")
        if observed > available:
            raise ValueError("observed_at cannot follow available_at")
        if expiration <= observed:
            raise ValueError("option quote must precede expiration")

    @property
    def midpoint(self) -> float:
        return (self.bid + self.ask) / 2.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OptionQuoteRecord":
        return cls(
            instrument_id=str(payload["instrument_id"]),
            underlying_instrument_id=str(payload["underlying_instrument_id"]),
            expiration_at=datetime.fromisoformat(str(payload["expiration_at"]).replace("Z", "+00:00")),
            strike=float(payload["strike"]),
            option_right=OptionRight(str(payload["option_right"])),
            exercise_style=ExerciseStyle(str(payload.get("exercise_style", "european"))),
            bid=float(payload["bid"]),
            ask=float(payload["ask"]),
            underlying_price=float(payload["underlying_price"]),
            risk_free_rate=float(payload.get("risk_free_rate", 0.0)),
            dividend_yield=float(payload.get("dividend_yield", 0.0)),
            observed_at=datetime.fromisoformat(str(payload["observed_at"]).replace("Z", "+00:00")),
            available_at=datetime.fromisoformat(str(payload["available_at"]).replace("Z", "+00:00")),
            source_identifier=str(payload["source_identifier"]),
        )


@dataclass(frozen=True, slots=True)
class VolatilitySurfacePoint:
    instrument_id: str
    expiration_at: datetime
    strike: float
    option_right: OptionRight
    midpoint: float
    implied_volatility: float
    time_to_expiry_years: float
    source_identifier: str
    exercise_style: ExerciseStyle

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "expiration_at": self.expiration_at.isoformat(),
            "strike": self.strike,
            "option_right": self.option_right.value,
            "midpoint": self.midpoint,
            "implied_volatility": self.implied_volatility,
            "time_to_expiry_years": self.time_to_expiry_years,
            "source_identifier": self.source_identifier,
            "exercise_style": self.exercise_style.value,
        }


@dataclass(frozen=True, slots=True)
class VolatilitySurfaceSnapshot:
    underlying_instrument_id: str
    as_of: datetime
    method_version: str
    points: tuple[VolatilitySurfacePoint, ...]
    source_identifiers: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "underlying_instrument_id",
            _text(self.underlying_instrument_id, field_name="underlying_instrument_id"),
        )
        _aware(self.as_of, field_name="as_of")
        object.__setattr__(
            self, "method_version", _text(self.method_version, field_name="method_version")
        )
        if not isinstance(self.points, tuple) or not self.points:
            raise ValueError("points must not be empty")
        if not all(isinstance(item, VolatilitySurfacePoint) for item in self.points):
            raise TypeError("points must contain VolatilitySurfacePoint values")
        if not isinstance(self.source_identifiers, tuple) or not self.source_identifiers:
            raise ValueError("source_identifiers must not be empty")
        if len(self.source_identifiers) != len(set(self.source_identifiers)):
            raise ValueError("source_identifiers cannot contain duplicates")
        if not isinstance(self.limitations, tuple):
            raise TypeError("limitations must be a tuple")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "volatility-surface-snapshot.v1",
            "underlying_instrument_id": self.underlying_instrument_id,
            "as_of": self.as_of.isoformat(),
            "method_version": self.method_version,
            "source_identifiers": list(self.source_identifiers),
            "limitations": list(self.limitations),
            "points": [item.to_dict() for item in self.points],
        }


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _black_scholes_price(
    *,
    spot: float,
    strike: float,
    time_years: float,
    rate: float,
    dividend_yield: float,
    volatility: float,
    right: OptionRight,
) -> float:
    if time_years <= 0:
        intrinsic = max(spot - strike, 0.0) if right is OptionRight.CALL else max(strike - spot, 0.0)
        return intrinsic
    sigma_sqrt = volatility * math.sqrt(time_years)
    if sigma_sqrt <= 0:
        forward_spot = spot * math.exp(-dividend_yield * time_years)
        discounted_strike = strike * math.exp(-rate * time_years)
        return max(forward_spot - discounted_strike, 0.0) if right is OptionRight.CALL else max(discounted_strike - forward_spot, 0.0)
    d1 = (
        math.log(spot / strike)
        + (rate - dividend_yield + 0.5 * volatility * volatility) * time_years
    ) / sigma_sqrt
    d2 = d1 - sigma_sqrt
    if right is OptionRight.CALL:
        return (
            spot * math.exp(-dividend_yield * time_years) * _normal_cdf(d1)
            - strike * math.exp(-rate * time_years) * _normal_cdf(d2)
        )
    return (
        strike * math.exp(-rate * time_years) * _normal_cdf(-d2)
        - spot * math.exp(-dividend_yield * time_years) * _normal_cdf(-d1)
    )


def _implied_volatility(quote: OptionQuoteRecord, *, as_of: datetime) -> float:
    time_years = (quote.expiration_at - as_of).total_seconds() / (365.25 * 86400.0)
    if time_years <= 0:
        raise DerivativeDataError("option has expired")
    target = quote.midpoint
    lower = _black_scholes_price(
        spot=quote.underlying_price,
        strike=quote.strike,
        time_years=time_years,
        rate=quote.risk_free_rate,
        dividend_yield=quote.dividend_yield,
        volatility=1e-8,
        right=quote.option_right,
    )
    upper = _black_scholes_price(
        spot=quote.underlying_price,
        strike=quote.strike,
        time_years=time_years,
        rate=quote.risk_free_rate,
        dividend_yield=quote.dividend_yield,
        volatility=8.0,
        right=quote.option_right,
    )
    tolerance = max(1e-8, target * 1e-8)
    if target < lower - tolerance or target > upper + tolerance:
        raise DerivativeDataError(
            f"option midpoint {target} violates no-arbitrage model bounds [{lower}, {upper}]"
        )
    lo, hi = 1e-8, 8.0
    for _ in range(120):
        mid = (lo + hi) / 2.0
        price = _black_scholes_price(
            spot=quote.underlying_price,
            strike=quote.strike,
            time_years=time_years,
            rate=quote.risk_free_rate,
            dividend_yield=quote.dividend_yield,
            volatility=mid,
            right=quote.option_right,
        )
        if abs(price - target) <= tolerance:
            return mid
        if price < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def build_volatility_surface(
    quotes: Iterable[OptionQuoteRecord],
    *,
    as_of: datetime,
    minimum_expirations: int = 2,
    minimum_strikes_per_expiration: int = 5,
) -> VolatilitySurfaceSnapshot:
    timestamp = _aware(as_of, field_name="as_of")
    values = tuple(quotes)
    if not values:
        raise DerivativeDataError("option quotes cannot be empty")
    if not all(isinstance(item, OptionQuoteRecord) for item in values):
        raise TypeError("quotes must contain OptionQuoteRecord values")
    underlyings = {item.underlying_instrument_id for item in values}
    if len(underlyings) != 1:
        raise DerivativeDataError("one volatility surface cannot mix underlyings")
    for item in values:
        if item.available_at > timestamp:
            raise DerivativeDataError(
                f"quote {item.instrument_id} was unavailable at surface as_of"
            )
    by_expiration: dict[datetime, set[float]] = {}
    points: list[VolatilitySurfacePoint] = []
    limitations: set[str] = set()
    for quote in values:
        by_expiration.setdefault(quote.expiration_at, set()).add(quote.strike)
        implied = _implied_volatility(quote, as_of=timestamp)
        years = (quote.expiration_at - timestamp).total_seconds() / (365.25 * 86400.0)
        points.append(
            VolatilitySurfacePoint(
                instrument_id=quote.instrument_id,
                expiration_at=quote.expiration_at,
                strike=quote.strike,
                option_right=quote.option_right,
                midpoint=quote.midpoint,
                implied_volatility=implied,
                time_to_expiry_years=years,
                source_identifier=quote.source_identifier,
                exercise_style=quote.exercise_style,
            )
        )
        if quote.exercise_style is ExerciseStyle.AMERICAN:
            limitations.add(
                "American-style options use a European implied-volatility approximation; exercise-premium risk remains in the option risk model."
            )
    if len(by_expiration) < minimum_expirations:
        raise DerivativeDataError(
            f"surface requires at least {minimum_expirations} expirations"
        )
    sparse = {
        expiration.isoformat(): len(strikes)
        for expiration, strikes in by_expiration.items()
        if len(strikes) < minimum_strikes_per_expiration
    }
    if sparse:
        raise DerivativeDataError(
            "surface expirations lack required strike breadth: "
            + ", ".join(f"{key}={value}" for key, value in sorted(sparse.items()))
        )
    points.sort(key=lambda item: (item.expiration_at, item.strike, item.option_right.value))
    return VolatilitySurfaceSnapshot(
        underlying_instrument_id=next(iter(underlyings)),
        as_of=timestamp,
        method_version="black-scholes-bisection.v1",
        points=tuple(points),
        source_identifiers=tuple(sorted({item.source_identifier for item in values})),
        limitations=tuple(sorted(limitations)),
    )


@dataclass(frozen=True, slots=True)
class DerivativeDataCertificationReport:
    evaluated_at: datetime
    certified: bool
    contract_count: int
    margin_count: int
    volatility_surface_count: int
    covered_venues: tuple[str, ...]
    blockers: tuple[str, ...]

    @classmethod
    def from_dict(
        cls, payload: dict[str, Any]
    ) -> "DerivativeDataCertificationReport":
        if payload.get("schema_version") != "derivative-data-certification-report.v1":
            raise ValueError("unsupported derivative data certification schema")
        return cls(
            evaluated_at=datetime.fromisoformat(
                str(payload["evaluated_at"]).replace("Z", "+00:00")
            ),
            certified=_boolean(payload["certified"], field_name="certified"),
            contract_count=int(payload["contract_count"]),
            margin_count=int(payload["margin_count"]),
            volatility_surface_count=int(payload["volatility_surface_count"]),
            covered_venues=tuple(str(item).upper() for item in payload.get("covered_venues", ())),
            blockers=tuple(str(item) for item in payload.get("blockers", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "derivative-data-certification-report.v1",
            "evaluated_at": self.evaluated_at.isoformat(),
            "certified": self.certified,
            "contract_count": self.contract_count,
            "margin_count": self.margin_count,
            "volatility_surface_count": self.volatility_surface_count,
            "covered_venues": list(self.covered_venues),
            "blockers": list(self.blockers),
            "real_money_authorized": False,
        }


def certify_derivative_data(
    *,
    contracts: Iterable[DerivativeContractRecord],
    margins: Iterable[MarginRequirementRecord],
    surfaces: Iterable[VolatilitySurfaceSnapshot],
    evaluated_at: datetime,
    required_venues: tuple[str, ...] = ("CME", "OCC", "ICE"),
    maximum_age_hours: float = 36.0,
) -> DerivativeDataCertificationReport:
    timestamp = _aware(evaluated_at, field_name="evaluated_at")
    contract_values = tuple(contracts)
    margin_values = tuple(margins)
    surface_values = tuple(surfaces)
    if not all(isinstance(item, DerivativeContractRecord) for item in contract_values):
        raise TypeError("contracts must contain DerivativeContractRecord values")
    if not all(isinstance(item, MarginRequirementRecord) for item in margin_values):
        raise TypeError("margins must contain MarginRequirementRecord values")
    if not all(isinstance(item, VolatilitySurfaceSnapshot) for item in surface_values):
        raise TypeError("surfaces must contain VolatilitySurfaceSnapshot values")
    if maximum_age_hours <= 0:
        raise ValueError("maximum_age_hours must be positive")
    blockers: list[str] = []
    contract_ids = {item.instrument_id for item in contract_values}
    if not contract_ids:
        blockers.append("no derivative contracts were supplied")
    duplicate_contracts = len(contract_ids) != len(contract_values)
    if duplicate_contracts:
        blockers.append("derivative contracts contain duplicate instrument identities")
    margin_ids = {item.instrument_id for item in margin_values}
    uncovered = contract_ids - margin_ids
    if uncovered:
        blockers.append(
            "contracts lack margin coverage: " + ", ".join(sorted(uncovered))
        )
    maximum_age_seconds = maximum_age_hours * 3600.0
    for item in contract_values:
        if item.available_at > timestamp:
            blockers.append(f"contract {item.instrument_id} was unavailable at evaluation time")
        elif (timestamp - item.available_at).total_seconds() > maximum_age_seconds:
            blockers.append(f"contract {item.instrument_id} is stale")
    for item in margin_values:
        if item.available_at > timestamp:
            blockers.append(f"margin {item.instrument_id} was unavailable at evaluation time")
        elif item.effective_at > timestamp:
            blockers.append(f"margin {item.instrument_id} is not yet effective")
        elif (timestamp - item.available_at).total_seconds() > maximum_age_seconds:
            blockers.append(f"margin {item.instrument_id} is stale")
    for item in surface_values:
        if item.as_of > timestamp:
            blockers.append(
                f"volatility surface {item.underlying_instrument_id} is from the future"
            )
        elif (timestamp - item.as_of).total_seconds() > maximum_age_seconds:
            blockers.append(
                f"volatility surface {item.underlying_instrument_id} is stale"
            )
    covered_venues = tuple(sorted({item.venue for item in contract_values} | {item.venue for item in margin_values}))
    missing_venues = {item.upper() for item in required_venues} - set(covered_venues)
    if missing_venues:
        blockers.append(
            "missing required derivative venues: "
            + ", ".join(sorted(missing_venues))
        )
    option_underlyings = {
        item.underlying_instrument_id
        for item in contract_values
        if item.contract_type in {
            DerivativeContractType.OPTION,
            DerivativeContractType.OPTION_ON_FUTURE,
        }
    }
    surface_underlyings = {item.underlying_instrument_id for item in surface_values}
    missing_surfaces = option_underlyings - surface_underlyings
    if missing_surfaces:
        blockers.append(
            "option underlyings lack volatility surfaces: "
            + ", ".join(sorted(missing_surfaces))
        )
    return DerivativeDataCertificationReport(
        evaluated_at=timestamp,
        certified=not blockers,
        contract_count=len(contract_values),
        margin_count=len(margin_values),
        volatility_surface_count=len(surface_values),
        covered_venues=covered_venues,
        blockers=tuple(dict.fromkeys(blockers)),
    )


__all__ = [
    "DerivativeContractRecord",
    "DerivativeContractType",
    "DerivativeDataCertificationReport",
    "DerivativeDataError",
    "ExerciseStyle",
    "MarginRequirementRecord",
    "OptionQuoteRecord",
    "OptionRight",
    "VolatilitySurfacePoint",
    "VolatilitySurfaceSnapshot",
    "build_volatility_surface",
    "certify_derivative_data",
]
