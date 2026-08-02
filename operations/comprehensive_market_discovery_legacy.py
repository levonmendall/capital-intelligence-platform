"""Comprehensive six-lane liquid-market discovery for the canonical paper CIO.

The engine scans provider catalogs before deep analysis, retains current holdings and
unresolved learning symbols, and publishes a bounded daily investable shortlist across
international equities, spot FX, spot crypto, dated futures, direct bonds, and
long-premium defined-risk options. Discovery has no ranking, sizing, construction,
execution, policy-promotion, or real-money authority beyond nominating instruments for
the existing canonical evidence and CIO path.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import pstdev
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

import requests

from cio import CandidateAssetClass
from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from governance import TradingSessionModel
from operations.free_paper_pilot import FreePaperPilotInstrument
from providers.databento_options import (
    DATABENTO_OPRA_DATASET,
    DatabentoOptionsError,
    DatabentoOptionsProvider,
)
from providers.eodhd import EODHDProvider, EODHDProviderError, build_eodhd_provider
from providers.alpaca_paper import AlpacaPaperClient, create_alpaca_paper_client

DEFAULT_DISCOVERY_CONFIG_PATH = Path("config/comprehensive_market_discovery.json")
_PROVIDER_DIRECTORY_CERTIFICATION_LIMIT = 1_000_000

_DISCOVERY_CALENDAR_TIMEZONE = ZoneInfo("America/New_York")
_DISCOVERY_LANES = (
    CandidateAssetClass.INTERNATIONAL_EQUITY,
    CandidateAssetClass.FX,
    CandidateAssetClass.CRYPTO,
    CandidateAssetClass.FUTURE,
    CandidateAssetClass.FIXED_INCOME,
    CandidateAssetClass.OPTION,
)
_WEEKEND_DISCOVERY_LANES = frozenset({CandidateAssetClass.CRYPTO})


class ComprehensiveMarketDiscoveryError(RuntimeError):
    """Raised when the complete cross-market discovery publication is invalid."""


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def scheduled_discovery_lanes(as_of: datetime) -> frozenset[CandidateAssetClass]:
    """Return market families scheduled for fresh discovery at ``as_of``.

    Saturday and Sunday discovery is limited to direct crypto, the governed 24/7
    lane. Exchange-local and 24/5 lanes remain fully fail-closed on weekdays and
    are marked scheduled-closed on weekends instead of being treated as provider
    failures.
    """

    timestamp = _aware(as_of, field_name="as_of")
    if timestamp.astimezone(_DISCOVERY_CALENDAR_TIMEZONE).weekday() >= 5:
        return _WEEKEND_DISCOVERY_LANES
    return frozenset(_DISCOVERY_LANES)


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be empty")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _number(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    result = float(value)
    return result if math.isfinite(result) else default


def _slug(value: object) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return normalized.strip("-") or "unknown"


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    ).hexdigest()


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        try:
            return _aware(value, field_name="timestamp")
        except (TypeError, ValueError):
            return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _period_return(closes: Sequence[float], periods: int) -> float:
    if len(closes) <= periods or closes[-periods - 1] <= 0.0:
        return 0.0
    return closes[-1] / closes[-periods - 1] - 1.0


@dataclass(frozen=True, slots=True)
class ComprehensiveMarketDiscoveryPolicy:
    version: str = "comprehensive-liquid-market-discovery.v1"
    maximum_directory_records_per_source: int | None = None
    maximum_deep_candidates_per_lane: int = 80
    selected_global_equities: int = 20
    selected_fx_pairs: int = 20
    selected_crypto_assets: int = 20
    selected_futures_contracts: int = 24
    selected_bonds: int = 20
    selected_options: int = 20
    minimum_history_bars: int = 252
    history_days: int = 760
    minimum_price: float = 0.01
    minimum_daily_dollar_volume: float = 1_000_000.0
    option_minimum_days_to_expiry: int = 30
    option_maximum_days_to_expiry: int = 365
    maximum_global_equity_weight: float = 0.03
    maximum_fx_weight: float = 0.05
    maximum_crypto_weight: float = 0.025
    maximum_future_weight: float = 0.05
    maximum_bond_weight: float = 0.05
    maximum_option_weight: float = 0.01

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        if self.maximum_directory_records_per_source is not None and (
            isinstance(self.maximum_directory_records_per_source, bool)
            or not isinstance(self.maximum_directory_records_per_source, int)
            or self.maximum_directory_records_per_source < 1
        ):
            raise ValueError(
                "maximum_directory_records_per_source must be a positive integer or None"
            )
        for field_name in (
            "maximum_deep_candidates_per_lane",
            "selected_global_equities",
            "selected_fx_pairs",
            "selected_crypto_assets",
            "selected_futures_contracts",
            "selected_bonds",
            "selected_options",
            "minimum_history_bars",
            "history_days",
            "option_minimum_days_to_expiry",
            "option_maximum_days_to_expiry",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.option_minimum_days_to_expiry >= self.option_maximum_days_to_expiry:
            raise ValueError("option expiry bounds are invalid")
        for field_name in (
            "minimum_price",
            "minimum_daily_dollar_volume",
            "maximum_global_equity_weight",
            "maximum_fx_weight",
            "maximum_crypto_weight",
            "maximum_future_weight",
            "maximum_bond_weight",
            "maximum_option_weight",
        ):
            value = float(getattr(self, field_name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{field_name} must be finite and positive")
        if any(
            float(getattr(self, name)) > 0.10
            for name in (
                "maximum_global_equity_weight",
                "maximum_fx_weight",
                "maximum_crypto_weight",
                "maximum_future_weight",
                "maximum_bond_weight",
                "maximum_option_weight",
            )
        ):
            raise ValueError("exploratory discovery weights cannot exceed 10%")

    def selected_limit(self, asset_class: CandidateAssetClass) -> int:
        return {
            CandidateAssetClass.INTERNATIONAL_EQUITY: self.selected_global_equities,
            CandidateAssetClass.FX: self.selected_fx_pairs,
            CandidateAssetClass.CRYPTO: self.selected_crypto_assets,
            CandidateAssetClass.FUTURE: self.selected_futures_contracts,
            CandidateAssetClass.FIXED_INCOME: self.selected_bonds,
            CandidateAssetClass.OPTION: self.selected_options,
        }.get(asset_class, 1_000_000)

    def maximum_weight(self, asset_class: CandidateAssetClass) -> float:
        return {
            CandidateAssetClass.INTERNATIONAL_EQUITY: self.maximum_global_equity_weight,
            CandidateAssetClass.FX: self.maximum_fx_weight,
            CandidateAssetClass.CRYPTO: self.maximum_crypto_weight,
            CandidateAssetClass.FUTURE: self.maximum_future_weight,
            CandidateAssetClass.FIXED_INCOME: self.maximum_bond_weight,
            CandidateAssetClass.OPTION: self.maximum_option_weight,
            CandidateAssetClass.COMMODITY: self.maximum_future_weight,
            CandidateAssetClass.REAL_ESTATE: self.maximum_global_equity_weight,
            CandidateAssetClass.VOLATILITY: self.maximum_option_weight,
            CandidateAssetClass.ALTERNATIVE: self.maximum_global_equity_weight,
            CandidateAssetClass.US_EQUITY: self.maximum_global_equity_weight,
            CandidateAssetClass.US_ETF: self.maximum_global_equity_weight,
            CandidateAssetClass.CASH_EQUIVALENT: self.maximum_bond_weight,
        }.get(asset_class, self.maximum_global_equity_weight)


@dataclass(frozen=True, slots=True)
class DiscoveryCatalogRecord:
    symbol: str
    provider_symbol: str
    name: str
    asset_class: CandidateAssetClass
    economic_exposure: str
    venue: str
    country_code: str
    currency: str
    settlement_currency: str
    instrument_type: str
    provider_kind: str
    source_identifier: str
    instrument_identifier: str | None = None
    contract_multiplier: float = 1.0
    quote_spread_bps: float = 5.0
    expiration_at: datetime | None = None
    underlying_symbol: str | None = None
    strike: float | None = None
    option_right: str | None = None
    provider_dataset: str | None = None
    provider_stype_in: str | None = None
    provider_instrument_id: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "symbol",
            "provider_symbol",
            "name",
            "economic_exposure",
            "venue",
            "country_code",
            "currency",
            "settlement_currency",
            "instrument_type",
            "provider_kind",
            "source_identifier",
        ):
            value = _text(getattr(self, field_name), field_name=field_name)
            if field_name in {
                "symbol",
                "venue",
                "country_code",
                "currency",
                "settlement_currency",
            }:
                value = value.upper()
            elif field_name in {"economic_exposure", "instrument_type", "provider_kind"}:
                value = value.lower()
            object.__setattr__(self, field_name, value)
        if self.instrument_identifier is not None:
            object.__setattr__(
                self,
                "instrument_identifier",
                _text(
                    self.instrument_identifier,
                    field_name="instrument_identifier",
                ),
            )
        if self.asset_class is CandidateAssetClass.OTHER:
            raise ValueError(
                "unclassified catalog records cannot enter governed discovery"
            )
        if self.expiration_at is not None:
            object.__setattr__(
                self,
                "expiration_at",
                _aware(self.expiration_at, field_name="expiration_at"),
            )
        if self.provider_instrument_id is not None:
            if (
                isinstance(self.provider_instrument_id, bool)
                or not isinstance(self.provider_instrument_id, int)
                or self.provider_instrument_id < 1
            ):
                raise ValueError("provider_instrument_id must be a positive integer")
        if self.asset_class is CandidateAssetClass.OPTION:
            if (
                self.expiration_at is None
                or self.underlying_symbol is None
                or self.strike is None
                or self.option_right not in {"call", "put"}
            ):
                raise ValueError("option catalog records require complete defined-risk terms")
        if (
            self.asset_class is CandidateAssetClass.FUTURE
            and self.instrument_type == "future"
            and self.expiration_at is None
        ):
            raise ValueError("dated futures catalog records require expiration_at")
        if self.contract_multiplier <= 0.0 or self.quote_spread_bps <= 0.0:
            raise ValueError("contract multiplier and quote spread must be positive")


@dataclass(frozen=True, slots=True)
class DiscoveryMarketFeatures:
    price: float
    observed_at: datetime
    one_month_return: float
    three_month_return: float
    six_month_return: float
    twelve_month_return: float
    annualized_volatility: float
    maximum_drawdown: float
    average_daily_dollar_volume: float
    history_bars: int
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.price <= 0.0 or self.history_bars < 1:
            raise ValueError("discovery market features require price and history")
        _aware(self.observed_at, field_name="observed_at")

    @property
    def score(self) -> float:
        consistency = 1.0 - min(1.0, max(0.0, self.annualized_volatility))
        liquidity = min(
            1.0,
            max(0.0, (math.log10(max(self.average_daily_dollar_volume, 1.0)) - 5.0) / 5.0),
        )
        drawdown = 1.0 - min(1.0, abs(min(0.0, self.maximum_drawdown)))
        momentum = max(
            -1.0,
            min(
                1.0,
                0.15 * self.one_month_return
                + 0.20 * self.three_month_return
                + 0.25 * self.six_month_return
                + 0.40 * self.twelve_month_return,
            ),
        )
        return round(
            0.45 * momentum + 0.25 * liquidity + 0.15 * consistency + 0.15 * drawdown,
            10,
        )


@dataclass(frozen=True, slots=True)
class DiscoveredMarketInstrument:
    catalog: DiscoveryCatalogRecord
    features: DiscoveryMarketFeatures
    retained_for_state: bool = False

    @property
    def score(self) -> float:
        return self.features.score + (1.0 if self.retained_for_state else 0.0)

    def instrument(
        self,
        *,
        policy: ComprehensiveMarketDiscoveryPolicy,
        currently_owned: bool,
    ) -> FreePaperPilotInstrument:
        item = self.catalog
        maximum = policy.maximum_weight(item.asset_class)
        if currently_owned:
            maximum = max(maximum, min(0.10, maximum * 2.0))
        session = (
            TradingSessionModel.CONTINUOUS_24_7
            if (
                item.asset_class is CandidateAssetClass.CRYPTO
                or (
                    item.instrument_type == "perpetual"
                    and item.economic_exposure == "crypto"
                )
            )
            else TradingSessionModel.CONTINUOUS_24_5
            if (
                item.asset_class is CandidateAssetClass.FX
                or item.instrument_type in {"forward", "swap"}
            )
            else TradingSessionModel.DEALER_24_5
            if item.asset_class is CandidateAssetClass.FIXED_INCOME
            else TradingSessionModel.EXCHANGE_LOCAL
        )
        return FreePaperPilotInstrument(
            symbol=item.symbol,
            instrument_identifier=(
                item.instrument_identifier
                or f"instrument:{item.asset_class.value}:{_slug(item.venue)}:{_slug(item.symbol)}"
            ),
            name=item.name,
            execution_asset_class=item.asset_class,
            economic_exposure=item.economic_exposure,
            venue=item.venue,
            country_code=item.country_code,
            currency=item.currency,
            settlement_currency=item.settlement_currency,
            instrument_type=item.instrument_type,
            maximum_weight=maximum,
            provider_symbol=item.provider_symbol,
            provider_kind=item.provider_kind,
            provider_dataset=item.provider_dataset,
            provider_stype_in=item.provider_stype_in,
            contract_multiplier=item.contract_multiplier,
            trading_session_model=session,
            quote_spread_bps=item.quote_spread_bps,
            expiration_at=(
                None if item.expiration_at is None else item.expiration_at.isoformat()
            ),
            underlying_symbol=item.underlying_symbol,
            strike=item.strike,
            option_right=item.option_right,
        )


@dataclass(frozen=True, slots=True)
class DiscoveryLaneResult:
    asset_class: CandidateAssetClass
    catalog_count: int
    deep_analyzed_count: int
    selected: tuple[DiscoveredMarketInstrument, ...]
    exclusions: tuple[tuple[str, str], ...]
    source_identifiers: tuple[str, ...]
    scheduled: bool = True
    schedule_reason: str | None = None

    def __post_init__(self) -> None:
        if self.catalog_count < 0 or self.deep_analyzed_count < 0 or self.deep_analyzed_count > self.catalog_count:
            raise ValueError("lane counts are invalid")
        if any(item.catalog.asset_class is not self.asset_class for item in self.selected):
            raise ValueError("lane contains a mismatched asset class")
        if not isinstance(self.scheduled, bool):
            raise TypeError("scheduled must be a bool")
        if self.scheduled and self.schedule_reason is not None:
            raise ValueError("scheduled lanes cannot carry a schedule_reason")
        if not self.scheduled:
            if not isinstance(self.schedule_reason, str) or not self.schedule_reason.strip():
                raise ValueError("scheduled-closed lanes require a schedule_reason")
            if (
                self.catalog_count
                or self.deep_analyzed_count
                or self.selected
                or self.source_identifiers
            ):
                raise ValueError(
                    "scheduled-closed lanes cannot contain evaluated market data"
                )


@dataclass(frozen=True, slots=True)
class ComprehensiveMarketDiscoveryResult:
    identifier: str
    as_of: datetime
    policy_version: str
    lanes: tuple[DiscoveryLaneResult, ...]
    manifest_fingerprint: str

    @property
    def selected(self) -> tuple[DiscoveredMarketInstrument, ...]:
        return tuple(item for lane in self.lanes for item in lane.selected)

    @property
    def source_identifiers(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item for lane in self.lanes for item in lane.source_identifiers))

    def instruments_for_holdings(
        self,
        held_symbols: Sequence[str],
        *,
        policy: ComprehensiveMarketDiscoveryPolicy | None = None,
    ) -> tuple[FreePaperPilotInstrument, ...]:
        resolved = policy or ComprehensiveMarketDiscoveryPolicy()
        held = {str(item).strip().upper() for item in held_symbols if str(item).strip()}
        return tuple(
            item.instrument(
                policy=resolved,
                currently_owned=item.catalog.symbol in held,
            )
            for item in self.selected
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "comprehensive-market-discovery-result.v1",
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "policy_version": self.policy_version,
            "manifest_fingerprint": self.manifest_fingerprint,
            "lanes": [
                {
                    "asset_class": lane.asset_class.value,
                    "scheduled": lane.scheduled,
                    "schedule_reason": lane.schedule_reason,
                    "catalog_count": lane.catalog_count,
                    "deep_analyzed_count": lane.deep_analyzed_count,
                    "selected": [
                        {
                            "symbol": item.catalog.symbol,
                            "provider_symbol": item.catalog.provider_symbol,
                            "name": item.catalog.name,
                            "score": item.score,
                            "price": item.features.price,
                            "average_daily_dollar_volume": item.features.average_daily_dollar_volume,
                            "history_bars": item.features.history_bars,
                            "retained_for_state": item.retained_for_state,
                            "expiration_at": (
                                None
                                if item.catalog.expiration_at is None
                                else item.catalog.expiration_at.isoformat()
                            ),
                            "underlying_symbol": item.catalog.underlying_symbol,
                            "strike": item.catalog.strike,
                            "option_right": item.catalog.option_right,
                        }
                        for item in lane.selected
                    ],
                    "exclusions": [list(item) for item in lane.exclusions],
                    "source_identifiers": list(lane.source_identifiers),
                }
                for lane in self.lanes
            ],
            "paper_only": True,
            "real_money_authorized": False,
        }


CatalogProbe = Callable[[datetime], Mapping[CandidateAssetClass, Sequence[DiscoveryCatalogRecord]]]
MarketProbe = Callable[
    [Sequence[DiscoveryCatalogRecord], datetime, ComprehensiveMarketDiscoveryPolicy],
    Mapping[str, DiscoveryMarketFeatures],
]


@dataclass(frozen=True, slots=True)
class ComprehensiveMarketDiscoveryConfig:
    eodhd_exchange_codes: tuple[str, ...]
    futures_roots: tuple[Mapping[str, Any], ...]
    option_underlyings: tuple[str, ...]
    yahoo_exchange_suffixes: tuple[tuple[str, str], ...]

    @property
    def yahoo_suffix_map(self) -> dict[str, str]:
        return dict(self.yahoo_exchange_suffixes)


def load_comprehensive_market_discovery_config(
    path: str | Path = DEFAULT_DISCOVERY_CONFIG_PATH,
) -> ComprehensiveMarketDiscoveryConfig:
    source = Path(path).expanduser()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComprehensiveMarketDiscoveryError(
            f"cannot load comprehensive discovery config {str(source)!r}"
        ) from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "comprehensive-market-discovery.v1":
        raise ComprehensiveMarketDiscoveryError("unsupported comprehensive discovery config")
    suffixes = payload.get("yahoo_exchange_suffixes", {})
    if not isinstance(suffixes, Mapping):
        raise ComprehensiveMarketDiscoveryError("yahoo_exchange_suffixes must be an object")
    return ComprehensiveMarketDiscoveryConfig(
        eodhd_exchange_codes=tuple(
            str(item).strip().upper() for item in payload.get("eodhd_exchange_codes", ())
            if str(item).strip()
        ),
        futures_roots=tuple(
            dict(item) for item in payload.get("futures_roots", ()) if isinstance(item, Mapping)
        ),
        option_underlyings=tuple(
            str(item).strip().upper() for item in payload.get("option_underlyings", ())
            if str(item).strip()
        ),
        yahoo_exchange_suffixes=tuple(
            (str(key).strip().upper(), str(value).strip())
            for key, value in suffixes.items()
            if str(key).strip() and str(value).strip()
        ),
    )


def _directory_records(snapshot: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(snapshot, Mapping):
        return ()
    active = snapshot.get("active")
    if not isinstance(active, Sequence) or isinstance(active, (str, bytes)):
        return ()
    return tuple(item for item in active if isinstance(item, Mapping))


def _directory_text(item: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = item.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _catalog_from_eodhd(
    *,
    as_of: datetime,
    config: ComprehensiveMarketDiscoveryConfig,
    provider: EODHDProvider,
    policy: ComprehensiveMarketDiscoveryPolicy,
    requested_asset_classes: frozenset[CandidateAssetClass] | None = None,
) -> Mapping[CandidateAssetClass, Sequence[DiscoveryCatalogRecord]]:
    directory_lanes = frozenset(
        item for item in CandidateAssetClass if item is not CandidateAssetClass.OTHER
    )
    requested = (
        directory_lanes
        if requested_asset_classes is None
        else frozenset(requested_asset_classes) & directory_lanes
    )
    result: dict[CandidateAssetClass, list[DiscoveryCatalogRecord]] = {
        item: [] for item in requested
    }
    suffix_map = config.yahoo_suffix_map
    exchange_lanes = {
        "CC": frozenset({CandidateAssetClass.CRYPTO}),
        "FOREX": frozenset({CandidateAssetClass.FX}),
        "BOND": frozenset({CandidateAssetClass.FIXED_INCOME}),
        "GBOND": frozenset({CandidateAssetClass.FIXED_INCOME}),
    }
    for exchange in config.eodhd_exchange_codes:
        possible_lanes = exchange_lanes.get(
            exchange,
            frozenset(
                {
                    CandidateAssetClass.INTERNATIONAL_EQUITY,
                    CandidateAssetClass.REAL_ESTATE,
                    CandidateAssetClass.ALTERNATIVE,
                    CandidateAssetClass.COMMODITY,
                }
            ),
        )
        if not possible_lanes & requested:
            continue
        snapshot = provider.fetch_dataset(
            ProviderDatasetQuery(
                dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
                provider_symbol=exchange,
                as_of=as_of,
                # This provider-contract maximum is a completeness sentinel, not a
                # selection cutoff. Hitting it fails closed instead of certifying a
                # silently truncated investment universe.
                limit=_PROVIDER_DIRECTORY_CERTIFICATION_LIMIT,
            )
        )
        directory_records = _directory_records(snapshot.payload)
        if len(directory_records) >= _PROVIDER_DIRECTORY_CERTIFICATION_LIMIT:
            raise ComprehensiveMarketDiscoveryError(
                f"provider directory {exchange} reached the completeness sentinel; "
                "use provider pagination or a certified complete catalog export"
            )
        for item in directory_records:
            code = _directory_text(item, "Code", "code", "Symbol", "symbol")
            name = _directory_text(item, "Name", "name") or code
            raw_type = (_directory_text(item, "Type", "type") or "").lower()
            currency = (_directory_text(item, "Currency", "currency") or "USD").upper()
            country = (
                _directory_text(item, "CountryISO2", "country_iso2", "Country", "country")
                or "GLOBAL"
            ).upper()
            venue = (_directory_text(item, "Exchange", "exchange") or exchange).upper()
            if not code:
                continue
            provider_symbol = code.upper()
            eodhd_suffix = f".{exchange}"
            if not provider_symbol.endswith(eodhd_suffix):
                provider_symbol += eodhd_suffix
            # EODHD's virtual CC exchange is authoritative for crypto. Its
            # symbol-directory rows are intentionally typed as ``Currency``, so
            # classifying by the generic row type first incorrectly routes every
            # crypto pair into the FX parser and rejects it as a non-six-letter
            # spot pair. Preserve the provider's venue semantics before applying
            # generic type-based fallbacks.
            if exchange == "CC":
                asset_class = CandidateAssetClass.CRYPTO
                instrument_type = "token"
                economic_exposure = "crypto"
            elif "common stock" in raw_type or "preferred stock" in raw_type:
                if country == "US" or exchange in {"US", "NASDAQ", "NYSE", "AMEX"}:
                    continue
                asset_class = CandidateAssetClass.INTERNATIONAL_EQUITY
                instrument_type = "preferred_stock" if "preferred" in raw_type else "common_stock"
                economic_exposure = "international_equity"
            elif any(
                marker in raw_type
                for marker in ("reit", "real estate investment trust")
            ):
                asset_class = CandidateAssetClass.REAL_ESTATE
                instrument_type = "reit"
                economic_exposure = "real_estate"
            elif any(
                marker in raw_type
                for marker in (
                    "etf", "fund", "closed-end", "investment trust", "unit trust"
                )
            ):
                asset_class = CandidateAssetClass.INTERNATIONAL_EQUITY
                instrument_type = "fund"
                economic_exposure = "international_equity"
            elif "warrant" in raw_type or "right" in raw_type:
                asset_class = CandidateAssetClass.ALTERNATIVE
                instrument_type = "warrant" if "warrant" in raw_type else "right"
                economic_exposure = "special_situations"
            elif "commodity" in raw_type or "metal" in raw_type:
                asset_class = CandidateAssetClass.COMMODITY
                instrument_type = "spot"
                economic_exposure = "broad_commodities"
            elif "currency" in raw_type or "forex" in raw_type:
                asset_class = CandidateAssetClass.FX
                instrument_type = "spot"
                economic_exposure = "foreign_exchange"
            elif "crypto" in raw_type:
                asset_class = CandidateAssetClass.CRYPTO
                instrument_type = "token"
                economic_exposure = "crypto"
            elif "bond" in raw_type:
                asset_class = CandidateAssetClass.FIXED_INCOME
                instrument_type = "bond"
                economic_exposure = "government_bonds" if "treasury" in name.lower() or "government" in name.lower() else "investment_grade_credit"
            else:
                continue
            if asset_class not in requested:
                continue
            yahoo_suffix = suffix_map.get(exchange, "")
            yahoo_symbol = code.upper() + yahoo_suffix
            selected_provider_kind = "yahoo" if yahoo_suffix or asset_class in {CandidateAssetClass.FX, CandidateAssetClass.CRYPTO} else "eodhd"
            if asset_class is CandidateAssetClass.FX:
                compact = re.sub(r"[^A-Z]", "", code.upper())
                if len(compact) != 6:
                    continue
                yahoo_symbol = f"{compact}=X"
            elif asset_class is CandidateAssetClass.CRYPTO:
                compact = code.upper().replace("_", "-").replace("/", "-")
                if "-" not in compact:
                    continue
                yahoo_symbol = compact
            result[asset_class].append(
                DiscoveryCatalogRecord(
                    symbol=(
                        re.sub(r"[^A-Z0-9]+", "", code.upper())
                        + ("_" + exchange if asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY else "")
                    ),
                    provider_symbol=(yahoo_symbol if selected_provider_kind == "yahoo" else provider_symbol),
                    name=name,
                    asset_class=asset_class,
                    economic_exposure=economic_exposure,
                    venue=venue,
                    country_code=country,
                    currency=currency,
                    settlement_currency=currency,
                    instrument_type=instrument_type,
                    provider_kind=selected_provider_kind,
                    source_identifier=f"{snapshot.provider_record_id}:{code}",
                    quote_spread_bps=(2.0 if asset_class is CandidateAssetClass.FX else 12.0 if asset_class is CandidateAssetClass.CRYPTO else 8.0),
                )
            )
    return result


def _futures_catalog(
    *,
    as_of: datetime,
    config: ComprehensiveMarketDiscoveryConfig,
) -> Sequence[DiscoveryCatalogRecord]:
    month_codes = "FGHJKMNQUVXZ"
    result: list[DiscoveryCatalogRecord] = []
    start_year = as_of.year
    for root in config.futures_roots:
        symbol_root = str(root.get("root", "")).strip().upper()
        provider_root = str(root.get("provider_root", symbol_root)).strip().upper()
        if not symbol_root:
            continue
        venue = str(root.get("venue", "CME")).strip().upper()
        economic_exposure = str(root.get("economic_exposure", "broad_commodities"))
        multiplier = float(root.get("contract_multiplier", 1.0))
        spread = float(root.get("quote_spread_bps", 3.0))
        months = tuple(str(item).strip().upper() for item in root.get("month_codes", month_codes))
        years_forward = int(root.get("years_forward", 2))
        for year in range(start_year, start_year + max(1, years_forward) + 1):
            for month_index, code in enumerate(month_codes, start=1):
                if code not in months:
                    continue
                expiration = datetime(year, month_index, 20, 21, 0, tzinfo=timezone.utc)
                if expiration <= as_of + timedelta(days=7):
                    continue
                yy = str(year)[-2:]
                contract_symbol = f"{symbol_root}{code}{yy}"
                provider_symbol = f"{provider_root}{code}{yy}.{venue}"
                result.append(
                    DiscoveryCatalogRecord(
                        symbol=contract_symbol,
                        provider_symbol=provider_symbol,
                        name=f"{root.get('name', symbol_root)} {code}{yy} dated future",
                        asset_class=CandidateAssetClass.FUTURE,
                        economic_exposure=economic_exposure,
                        venue=venue,
                        country_code=str(root.get("country_code", "US")),
                        currency=str(root.get("currency", "USD")),
                        settlement_currency=str(root.get("settlement_currency", "USD")),
                        instrument_type="future",
                        provider_kind=str(root.get("provider_kind", "databento")),
                        provider_dataset=_optional_text(root.get("dataset")),
                        provider_stype_in=str(root.get("stype_in", "raw_symbol")),
                        source_identifier=f"configured-futures-root:{symbol_root}:{contract_symbol}",
                        contract_multiplier=multiplier,
                        quote_spread_bps=spread,
                        expiration_at=expiration,
                    )
                )
    return result


def _option_catalog(
    *,
    as_of: datetime,
    config: ComprehensiveMarketDiscoveryConfig,
    policy: ComprehensiveMarketDiscoveryPolicy,
    http_get: Callable[..., Any] = requests.get,
    databento_options_provider: DatabentoOptionsProvider | None = None,
) -> Sequence[DiscoveryCatalogRecord]:
    provider = databento_options_provider or DatabentoOptionsProvider()
    if not provider.configured:
        raise ComprehensiveMarketDiscoveryError(
            "Databento OPRA credentials are required for defined-risk option discovery"
        )
    result: list[DiscoveryCatalogRecord] = []
    for underlying in config.option_underlyings:
        underlying_record = DiscoveryCatalogRecord(
            symbol=underlying,
            provider_symbol=underlying,
            name=underlying,
            asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
            economic_exposure="us_equity",
            venue="US",
            country_code="US",
            currency="USD",
            settlement_currency="USD",
            instrument_type="common_stock",
            provider_kind="yahoo",
            source_identifier=f"yahoo-chart:{underlying}",
        )
        rows = _yahoo_rows(
            underlying_record,
            as_of=as_of,
            history_days=15,
            http_get=http_get,
        )
        if not rows:
            continue
        underlying_price = float(rows[-1]["c"])
        try:
            selections = provider.select_contracts(
                underlying,
                underlying_price=underlying_price,
                as_of=as_of,
                minimum_days_to_expiry=policy.option_minimum_days_to_expiry,
                maximum_days_to_expiry=policy.option_maximum_days_to_expiry,
            )
        except (DatabentoOptionsError, OSError, TypeError, ValueError):
            continue
        for selection in selections:
            definition = selection.definition
            bar = selection.bar
            result.append(
                DiscoveryCatalogRecord(
                    symbol=definition.symbol,
                    provider_symbol=definition.raw_symbol,
                    name=(
                        f"{definition.underlying} {definition.expiration_at.date()} "
                        f"{definition.strike:g} {definition.option_right}"
                    ),
                    asset_class=CandidateAssetClass.OPTION,
                    economic_exposure="option_strategies",
                    venue="OPRA",
                    country_code="US",
                    currency="USD",
                    settlement_currency="USD",
                    instrument_type="option",
                    provider_kind="databento",
                    provider_dataset=DATABENTO_OPRA_DATASET,
                    provider_stype_in="instrument_id",
                    provider_instrument_id=definition.instrument_id,
                    source_identifier=(
                        "databento-opra-definition:"
                        f"{definition.session_date.isoformat()}:"
                        f"{definition.symbol}:bar:{bar.observed_at.isoformat()}"
                    ),
                    contract_multiplier=definition.contract_multiplier,
                    quote_spread_bps=15.0,
                    expiration_at=definition.expiration_at,
                    underlying_symbol=definition.underlying,
                    strike=definition.strike,
                    option_right=definition.option_right,
                )
            )
    return result


def default_catalog_probe(
    as_of: datetime,
    *,
    config: ComprehensiveMarketDiscoveryConfig | None = None,
    policy: ComprehensiveMarketDiscoveryPolicy | None = None,
    eodhd_provider: EODHDProvider | None = None,
    databento_options_provider: DatabentoOptionsProvider | None = None,
) -> Mapping[CandidateAssetClass, Sequence[DiscoveryCatalogRecord]]:
    timestamp = _aware(as_of, field_name="as_of")
    resolved_config = config or load_comprehensive_market_discovery_config()
    resolved_policy = policy or ComprehensiveMarketDiscoveryPolicy()
    active_lanes = scheduled_discovery_lanes(timestamp)
    provider = eodhd_provider or build_eodhd_provider()
    result = {
        key: list(value)
        for key, value in _catalog_from_eodhd(
            as_of=timestamp,
            config=resolved_config,
            provider=provider,
            policy=resolved_policy,
            requested_asset_classes=active_lanes,
        ).items()
    }
    for asset_class in _DISCOVERY_LANES:
        result.setdefault(asset_class, [])
    if CandidateAssetClass.FUTURE in active_lanes:
        result[CandidateAssetClass.FUTURE] = list(
            _futures_catalog(as_of=timestamp, config=resolved_config)
        )
    if CandidateAssetClass.OPTION in active_lanes:
        result[CandidateAssetClass.OPTION] = list(
            _option_catalog(
                as_of=timestamp,
                config=resolved_config,
                policy=resolved_policy,
                databento_options_provider=databento_options_provider,
            )
        )
    return result


def _yahoo_rows(
    record: DiscoveryCatalogRecord,
    *,
    as_of: datetime,
    history_days: int,
    http_get: Callable[..., Any],
) -> tuple[dict[str, object], ...]:
    end = int(as_of.timestamp())
    start = int((as_of - timedelta(days=history_days)).timestamp())
    try:
        response = http_get(
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            + requests.utils.quote(record.provider_symbol, safe=""),
            params={
                "period1": start,
                "period2": end,
                "interval": "1d",
                "events": "history",
                "includePrePost": "true",
            },
            headers={"User-Agent": "capital-intelligence-paper-research/1.0"},
            timeout=20,
        )
        if int(getattr(response, "status_code", 0)) != 200:
            return ()
        chart = response.json()["chart"]["result"][0]
        timestamps = chart.get("timestamp", ())
        quote = chart.get("indicators", {}).get("quote", ())[0]
    except (KeyError, IndexError, TypeError, ValueError, requests.RequestException):
        return ()
    result: list[dict[str, object]] = []
    for index, raw_timestamp in enumerate(timestamps):
        try:
            close = quote["close"][index]
            volume = quote.get("volume", ())[index] or 0.0
        except (KeyError, IndexError, TypeError):
            continue
        if close is None or float(close) <= 0.0:
            continue
        observed = datetime.fromtimestamp(float(raw_timestamp), tz=timezone.utc)
        if observed <= as_of:
            result.append({"t": observed, "c": float(close), "v": max(0.0, float(volume))})
    return tuple(result)


def _eodhd_rows(
    record: DiscoveryCatalogRecord,
    *,
    as_of: datetime,
    history_days: int,
    provider: EODHDProvider,
) -> tuple[dict[str, object], ...]:
    try:
        snapshot = provider.fetch_dataset(
            ProviderDatasetQuery(
                dataset_type=ProviderDatasetType.MARKET_HISTORY,
                provider_symbol=record.provider_symbol,
                as_of=as_of,
                start_at=as_of - timedelta(days=history_days),
                end_at=as_of,
                limit=10_000,
            )
        )
    except (EODHDProviderError, TypeError, ValueError):
        return ()
    payload = snapshot.payload
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        return ()
    rows: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        observed = _timestamp(item.get("date"))
        if observed is None:
            raw_date = str(item.get("date", ""))
            try:
                observed = datetime.fromisoformat(raw_date[:10]).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        close = _number(item.get("adjusted_close", item.get("close")))
        volume = _number(item.get("volume"))
        if observed <= as_of and close > 0.0:
            rows.append({"t": observed, "c": close, "v": max(0.0, volume)})
    return tuple(rows)


def default_market_probe(
    records: Sequence[DiscoveryCatalogRecord],
    as_of: datetime,
    policy: ComprehensiveMarketDiscoveryPolicy,
    *,
    http_get: Callable[..., Any] = requests.get,
    eodhd_provider: EODHDProvider | None = None,
    databento_options_provider: DatabentoOptionsProvider | None = None,
    alpaca_client: AlpacaPaperClient | None = None,
) -> Mapping[str, DiscoveryMarketFeatures]:
    timestamp = _aware(as_of, field_name="as_of")
    provider = eodhd_provider or build_eodhd_provider()
    options_provider = databento_options_provider or DatabentoOptionsProvider()
    option_records = tuple(
        item for item in records if item.asset_class is CandidateAssetClass.OPTION
    )
    option_histories: Mapping[str, tuple[object, ...]] = {}
    alpaca_records = tuple(item for item in records if item.provider_kind == "alpaca")
    alpaca_histories: dict[str, Sequence[Mapping[str, object]]] = {}
    if alpaca_records:
        client = alpaca_client or create_alpaca_paper_client()
        alpaca_symbols = tuple(item.provider_symbol for item in alpaca_records)
        for start in range(0, len(alpaca_symbols), 200):
            batch = alpaca_symbols[start : start + 200]
            try:
                histories = client.historical_bars(
                    batch,
                    start=timestamp - timedelta(days=policy.history_days),
                    end=timestamp,
                    timeframe="1Day",
                )
            except (OSError, TypeError, ValueError):
                histories = {}
            for symbol, values in histories.items():
                alpaca_histories[str(symbol).strip().upper()] = values
    if option_records and options_provider.configured:
        try:
            option_instruments = tuple(
                (item.provider_instrument_id, item.provider_symbol)
                for item in option_records
                if item.provider_instrument_id is not None
            )
            if len(option_instruments) != len(option_records):
                raise DatabentoOptionsError(
                    "option records are missing provider instrument IDs"
                )
            _option_session, option_histories = options_provider.latest_daily_bars(
                option_instruments,
                as_of=timestamp,
                history_days=min(policy.history_days, 365),
            )
        except (DatabentoOptionsError, OSError, TypeError, ValueError):
            option_histories = {}
    result: dict[str, DiscoveryMarketFeatures] = {}
    for record in records:
        option_evidence: tuple[str, ...] = ()
        if record.asset_class is CandidateAssetClass.OPTION and record.underlying_symbol:
            underlying = DiscoveryCatalogRecord(
                symbol=record.underlying_symbol,
                provider_symbol=record.underlying_symbol,
                name=record.underlying_symbol,
                asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
                economic_exposure="international_equity",
                venue="US",
                country_code="US",
                currency="USD",
                settlement_currency="USD",
                instrument_type="common_stock",
                provider_kind="yahoo",
                source_identifier=record.source_identifier,
            )
            rows = _yahoo_rows(
                underlying,
                as_of=timestamp,
                history_days=policy.history_days,
                http_get=http_get,
            )
            option_rows = option_histories.get(record.provider_symbol.upper(), ())
            option_price = float(option_rows[-1].close) if option_rows else 0.0
            if option_rows:
                option_material = [
                    {
                        "t": item.observed_at.isoformat(),
                        "c": item.close,
                        "v": item.volume,
                    }
                    for item in option_rows
                ]
                option_evidence = (
                    f"databento-opra-bars:{record.symbol}:{_hash(option_material)}",
                )
        elif record.provider_kind == "alpaca":
            raw_rows = alpaca_histories.get(record.provider_symbol.upper(), ())
            parsed_rows: list[dict[str, object]] = []
            for raw in raw_rows:
                if not isinstance(raw, Mapping):
                    continue
                observed = _timestamp(raw.get("t"))
                close = _number(raw.get("c"))
                volume = _number(raw.get("v"))
                if observed is None or observed > timestamp or close <= 0.0:
                    continue
                parsed_rows.append(
                    {"t": observed, "c": close, "v": max(0.0, volume)}
                )
            rows = tuple(parsed_rows)
            option_price = 0.0
        elif record.provider_kind == "yahoo":
            rows = _yahoo_rows(
                record,
                as_of=timestamp,
                history_days=policy.history_days,
                http_get=http_get,
            )
            option_price = 0.0
        elif record.provider_kind == "eodhd":
            rows = _eodhd_rows(
                record,
                as_of=timestamp,
                history_days=policy.history_days,
                provider=provider,
            )
            option_price = 0.0
        else:
            # Databento and other provider-native records are ranked only after a
            # runtime probe supplies point-in-time bars. Missing evidence remains
            # an explicit exclusion rather than being synthesized.
            continue
        if len(rows) < policy.minimum_history_bars:
            continue
        if record.asset_class is CandidateAssetClass.OPTION and option_price <= 0.0:
            continue
        closes = [float(item["c"]) for item in rows]
        volumes = [float(item["v"]) for item in rows]
        daily = [
            closes[index] / closes[index - 1] - 1.0
            for index in range(1, len(closes))
            if closes[index - 1] > 0.0
        ]
        volatility = pstdev(daily[-252:]) * math.sqrt(252.0) if len(daily) > 1 else 0.0
        peak = closes[0]
        drawdown = 0.0
        for close in closes:
            peak = max(peak, close)
            drawdown = min(drawdown, close / peak - 1.0)
        adv = sum(
            closes[index] * volumes[index]
            for index in range(max(0, len(closes) - 20), len(closes))
        ) / min(20, len(closes))
        price = option_price if option_price > 0.0 else closes[-1]
        material = [
            {"t": item["t"].isoformat(), "c": item["c"], "v": item["v"]}
            for item in rows
        ]
        observed_at = (
            option_rows[-1].observed_at
            if record.asset_class is CandidateAssetClass.OPTION and option_rows
            else rows[-1]["t"]
        )
        result[record.symbol] = DiscoveryMarketFeatures(
            price=price,
            observed_at=observed_at,
            one_month_return=_period_return(closes, 21),
            three_month_return=_period_return(closes, 63),
            six_month_return=_period_return(closes, 126),
            twelve_month_return=_period_return(closes, 252),
            annualized_volatility=volatility,
            maximum_drawdown=drawdown,
            average_daily_dollar_volume=max(0.0, adv),
            history_bars=len(rows),
            evidence_identifiers=(
                record.source_identifier,
                f"discovery-bars:{record.symbol}:{_hash(material)}",
                *option_evidence,
            ),
        )
    return result


def _deduplicate(records: Sequence[DiscoveryCatalogRecord]) -> tuple[DiscoveryCatalogRecord, ...]:
    by_identity: dict[tuple[CandidateAssetClass, str], DiscoveryCatalogRecord] = {}
    for item in records:
        key = (item.asset_class, item.symbol)
        existing = by_identity.get(key)
        if existing is None or item.source_identifier < existing.source_identifier:
            by_identity[key] = item
    return tuple(by_identity[key] for key in sorted(by_identity, key=lambda item: (item[0].value, item[1])))


def discover_comprehensive_markets(
    *,
    as_of: datetime,
    held_symbols: Sequence[str] = (),
    tracked_symbols: Sequence[str] = (),
    excluded_symbols: Sequence[str] = (),
    catalog_probe: CatalogProbe | None = None,
    market_probe: MarketProbe | None = None,
    policy: ComprehensiveMarketDiscoveryPolicy | None = None,
) -> ComprehensiveMarketDiscoveryResult:
    """Scan every configured lane and publish a bounded point-in-time shortlist."""

    timestamp = _aware(as_of, field_name="as_of")
    resolved = policy or ComprehensiveMarketDiscoveryPolicy()
    scheduled_lanes = scheduled_discovery_lanes(timestamp)
    catalogs = (catalog_probe or default_catalog_probe)(timestamp)
    if not isinstance(catalogs, Mapping):
        raise ComprehensiveMarketDiscoveryError("catalog probe must return a mapping")
    held = {str(item).strip().upper() for item in held_symbols if str(item).strip()}
    tracked = {str(item).strip().upper() for item in tracked_symbols if str(item).strip()}
    excluded = {str(item).strip().upper() for item in excluded_symbols if str(item).strip()}
    lanes: list[DiscoveryLaneResult] = []
    manifest_material: list[dict[str, object]] = []
    for asset_class in _DISCOVERY_LANES:
        if asset_class not in scheduled_lanes:
            schedule_reason = "weekend_market_closed"
            lanes.append(
                DiscoveryLaneResult(
                    asset_class=asset_class,
                    catalog_count=0,
                    deep_analyzed_count=0,
                    selected=(),
                    exclusions=(("__lane__", schedule_reason),),
                    source_identifiers=(),
                    scheduled=False,
                    schedule_reason=schedule_reason,
                )
            )
            manifest_material.append(
                {
                    "asset_class": asset_class.value,
                    "scheduled": False,
                    "schedule_reason": schedule_reason,
                    "catalog": 0,
                    "deep": 0,
                    "selected": [],
                    "sources": [],
                    "candidate_count_limit_applied": False,
                }
            )
            continue
        raw = catalogs.get(asset_class, ())
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise ComprehensiveMarketDiscoveryError(
                f"{asset_class.value} catalog must be a sequence"
            )
        records = tuple(
            item
            for item in _deduplicate(tuple(raw))
            if item.symbol not in excluded
            and (item.expiration_at is None or item.expiration_at > timestamp + timedelta(days=7))
        )
        state_symbols = held | tracked
        retained = [item for item in records if item.symbol in state_symbols]
        ordinary = [item for item in records if item.symbol not in state_symbols]
        ordinary.sort(key=lambda item: (item.source_identifier, item.symbol))
        # Compatibility implementation also processes the complete eligible catalog.
        # Legacy count fields remain readable but have no selection authority.
        deep_records = tuple(dict.fromkeys((*retained, *ordinary)))
        features = (market_probe or default_market_probe)(deep_records, timestamp, resolved)
        selected: list[DiscoveredMarketInstrument] = []
        exclusions: list[tuple[str, str]] = []
        for record in deep_records:
            item_features = features.get(record.symbol)
            if item_features is None:
                exclusions.append((record.symbol, "point_in_time_market_evidence_unavailable"))
                continue
            if item_features.price < resolved.minimum_price:
                exclusions.append((record.symbol, "price_below_policy_floor"))
                continue
            if (
                record.asset_class
                not in {CandidateAssetClass.FX, CandidateAssetClass.FIXED_INCOME, CandidateAssetClass.OPTION}
                and item_features.average_daily_dollar_volume < resolved.minimum_daily_dollar_volume
            ):
                exclusions.append((record.symbol, "liquidity_below_policy_floor"))
                continue
            selected.append(
                DiscoveredMarketInstrument(
                    catalog=record,
                    features=item_features,
                    retained_for_state=record.symbol in state_symbols,
                )
            )
        selected.sort(key=lambda item: (item.score, item.catalog.symbol), reverse=True)
        # Ordering is informational only; every instrument passing evidence, price,
        # history, and liquidity checks remains in the result.
        final = tuple(selected)
        source_identifiers = tuple(
            dict.fromkeys(item.catalog.source_identifier for item in final)
        )
        lanes.append(
            DiscoveryLaneResult(
                asset_class=asset_class,
                catalog_count=len(records),
                deep_analyzed_count=len(deep_records),
                selected=final,
                exclusions=tuple(exclusions),
                source_identifiers=source_identifiers,
            )
        )
        manifest_material.append(
            {
                "asset_class": asset_class.value,
                "scheduled": True,
                "schedule_reason": None,
                "catalog": len(records),
                "deep": len(deep_records),
                "selected": [item.catalog.symbol for item in final],
                "sources": list(source_identifiers),
                "candidate_count_limit_applied": False,
            }
        )
    if any(lane.scheduled and not lane.selected for lane in lanes):
        missing = tuple(
            lane.asset_class.value
            for lane in lanes
            if lane.scheduled and not lane.selected
        )
        raise ComprehensiveMarketDiscoveryError(
            "complete discovery cannot certify an empty requested lane: " + ", ".join(missing)
        )
    fingerprint = _hash(
        {
            "as_of": timestamp.isoformat(),
            "policy": resolved.version,
            "candidate_count_limit_applied": False,
            "lanes": manifest_material,
        }
    )
    return ComprehensiveMarketDiscoveryResult(
        identifier=f"comprehensive-market-discovery:{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}:{fingerprint[:16]}",
        as_of=timestamp,
        policy_version=resolved.version,
        lanes=tuple(lanes),
        manifest_fingerprint=fingerprint,
    )


__all__ = [
    "CatalogProbe",
    "ComprehensiveMarketDiscoveryConfig",
    "ComprehensiveMarketDiscoveryError",
    "ComprehensiveMarketDiscoveryPolicy",
    "ComprehensiveMarketDiscoveryResult",
    "DEFAULT_DISCOVERY_CONFIG_PATH",
    "DiscoveryCatalogRecord",
    "DiscoveryLaneResult",
    "DiscoveryMarketFeatures",
    "DiscoveredMarketInstrument",
    "MarketProbe",
    "default_catalog_probe",
    "default_market_probe",
    "discover_comprehensive_markets",
    "load_comprehensive_market_discovery_config",
    "scheduled_discovery_lanes",
]
