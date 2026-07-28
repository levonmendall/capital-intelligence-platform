"""Canonical mark-to-market and cash-flow accounting for the paper portfolio.

The module updates valuation without requiring a trade, books non-trade cash effects,
and preserves an append-only audit trail.  It is accounting infrastructure only; it
creates no investment, brokerage, or real-money authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from math import isfinite
from typing import Mapping, Protocol, runtime_checkable

from portfolio.multi_asset_controls import MultiAssetInstrumentProfile
from portfolio.multi_asset_execution import MultiAssetQuote, MultiAssetQuoteProvider
from portfolio.state import (
    CanonicalCurrencyBalance,
    CanonicalImplementationEvent,
    CanonicalPortfolioPosition,
    CanonicalPortfolioSnapshot,
    SQLiteCanonicalPortfolioStore,
)


class PortfolioPerformanceError(RuntimeError):
    """Raised when portfolio performance cannot be measured reliably."""


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


def _number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return round(normalized, 12)


@dataclass(frozen=True, slots=True)
class PortfolioValuationPolicy:
    version: str = "portfolio-mark-to-market.v1"
    maximum_quote_age_minutes: int = 15
    maximum_fx_age_minutes: int = 15
    reconciliation_tolerance: float = 0.01

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _text(self.version, field_name="version"))
        for field_name in ("maximum_quote_age_minutes", "maximum_fx_age_minutes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 1:
                raise ValueError(f"{field_name} must be positive")
        tolerance = _number(
            self.reconciliation_tolerance,
            field_name="reconciliation_tolerance",
        )
        if tolerance < 0.0:
            raise ValueError("reconciliation_tolerance cannot be negative")
        object.__setattr__(self, "reconciliation_tolerance", tolerance)


@dataclass(frozen=True, slots=True)
class CurrencyRateMark:
    currency: str
    base_currency: str
    rate_to_base: float
    observed_at: datetime
    source_identifier: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", _text(self.currency, field_name="currency").upper())
        object.__setattr__(
            self,
            "base_currency",
            _text(self.base_currency, field_name="base_currency").upper(),
        )
        rate = _number(self.rate_to_base, field_name="rate_to_base")
        if rate <= 0.0:
            raise ValueError("rate_to_base must be positive")
        object.__setattr__(self, "rate_to_base", rate)
        _aware(self.observed_at, field_name="observed_at")
        object.__setattr__(
            self,
            "source_identifier",
            _text(self.source_identifier, field_name="source_identifier"),
        )


@runtime_checkable
class CurrencyRateProvider(Protocol):
    def rates(
        self,
        currencies: tuple[str, ...],
        *,
        base_currency: str,
        as_of: datetime,
    ) -> Mapping[str, CurrencyRateMark]: ...


@dataclass(frozen=True, slots=True)
class PositionValuationChange:
    symbol: str
    instrument_identifier: str
    prior_market_value: float
    current_market_value: float
    change_base: float
    unrealized_pnl_base: float
    quote_source_identifier: str


@dataclass(frozen=True, slots=True)
class PortfolioValuationReport:
    identifier: str
    as_of: datetime
    beginning_snapshot_identifier: str
    ending_snapshot_identifier: str
    beginning_nav: float
    ending_nav: float
    mark_change_base: float
    expected_mark_change_base: float
    reconciliation_difference: float
    total_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    cash_fx_pnl: float
    non_trade_pnl: float
    net_external_flows: float
    accounting_residual: float
    position_changes: tuple[PositionValuationChange, ...]
    policy_version: str
    complete: bool
    real_money_authorized: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "beginning_snapshot_identifier": self.beginning_snapshot_identifier,
            "ending_snapshot_identifier": self.ending_snapshot_identifier,
            "beginning_nav": self.beginning_nav,
            "ending_nav": self.ending_nav,
            "mark_change_base": self.mark_change_base,
            "expected_mark_change_base": self.expected_mark_change_base,
            "reconciliation_difference": self.reconciliation_difference,
            "total_pnl": self.total_pnl,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "cash_fx_pnl": self.cash_fx_pnl,
            "non_trade_pnl": self.non_trade_pnl,
            "net_external_flows": self.net_external_flows,
            "accounting_residual": self.accounting_residual,
            "position_changes": [
                {
                    "symbol": item.symbol,
                    "instrument_identifier": item.instrument_identifier,
                    "prior_market_value": item.prior_market_value,
                    "current_market_value": item.current_market_value,
                    "change_base": item.change_base,
                    "unrealized_pnl_base": item.unrealized_pnl_base,
                    "quote_source_identifier": item.quote_source_identifier,
                }
                for item in self.position_changes
            ],
            "policy_version": self.policy_version,
            "complete": self.complete,
            "real_money_authorized": False,
            "schema_version": "portfolio-valuation-report.v1",
        }


class PortfolioMarkToMarketService:
    """Revalue every current holding and currency balance at one exact timestamp."""

    def __init__(
        self,
        *,
        quote_provider: MultiAssetQuoteProvider,
        portfolio_store: SQLiteCanonicalPortfolioStore,
        currency_rate_provider: CurrencyRateProvider | None = None,
        policy: PortfolioValuationPolicy | None = None,
    ) -> None:
        if not isinstance(quote_provider, MultiAssetQuoteProvider):
            raise TypeError("quote_provider must implement MultiAssetQuoteProvider")
        if not isinstance(portfolio_store, SQLiteCanonicalPortfolioStore):
            raise TypeError("portfolio_store must be SQLiteCanonicalPortfolioStore")
        if currency_rate_provider is not None and not isinstance(
            currency_rate_provider,
            CurrencyRateProvider,
        ):
            raise TypeError("currency_rate_provider must implement CurrencyRateProvider")
        self.quote_provider = quote_provider
        self.currency_rate_provider = currency_rate_provider
        self.portfolio_store = portfolio_store
        self.policy = policy or PortfolioValuationPolicy()

    def mark(
        self,
        *,
        portfolio: CanonicalPortfolioSnapshot,
        profiles: Mapping[str, MultiAssetInstrumentProfile],
        as_of: datetime,
    ) -> PortfolioValuationReport:
        if not isinstance(portfolio, CanonicalPortfolioSnapshot):
            raise TypeError("portfolio must be a CanonicalPortfolioSnapshot")
        timestamp = _aware(as_of, field_name="as_of")
        if portfolio.as_of > timestamp:
            raise PortfolioPerformanceError("portfolio snapshot cannot follow valuation time")
        normalized_profiles = {str(key).strip().upper(): value for key, value in profiles.items()}
        symbols = {item.symbol for item in portfolio.positions}
        if set(normalized_profiles) != symbols:
            raise PortfolioPerformanceError(
                "valuation profiles must exactly match current positions: "
                f"missing={sorted(symbols-set(normalized_profiles))} "
                f"extra={sorted(set(normalized_profiles)-symbols)}"
            )
        for position in portfolio.positions:
            profile = normalized_profiles[position.symbol]
            self._validate_profile(position, profile)

        quotes: Mapping[str, MultiAssetQuote] = {}
        if portfolio.positions:
            quotes = self.quote_provider.quotes(
                tuple(normalized_profiles[item.symbol] for item in portfolio.positions),
                as_of=timestamp,
            )
            if not isinstance(quotes, Mapping) or set(quotes) != symbols:
                raise PortfolioPerformanceError(
                    "valuation quote coverage must exactly match current positions"
                )

        updated_positions: list[CanonicalPortfolioPosition] = []
        position_changes: list[PositionValuationChange] = []
        sources: list[str] = []
        expected_change = 0.0
        for position in portfolio.positions:
            profile = normalized_profiles[position.symbol]
            quote = quotes[position.symbol]
            self._validate_quote(
                quote=quote,
                position=position,
                profile=profile,
                as_of=timestamp,
                base_currency=portfolio.base_currency,
            )
            updated = replace(
                position,
                mark_price=quote.last,
                updated_at=timestamp,
                fx_rate_to_base=quote.fx_rate_to_base,
                fx_rate_observed_at=quote.fx_observed_at,
                fx_rate_source_identifier=quote.fx_source_identifier,
            )
            change = round(updated.market_value - position.market_value, 8)
            expected_change += change
            updated_positions.append(updated)
            sources.extend(
                (
                    quote.quote_source_identifier,
                    quote.fx_source_identifier,
                    quote.quote_certification_identifier,
                )
            )
            position_changes.append(
                PositionValuationChange(
                    symbol=position.symbol,
                    instrument_identifier=profile.instrument_identifier,
                    prior_market_value=position.market_value,
                    current_market_value=updated.market_value,
                    change_base=change,
                    unrealized_pnl_base=updated.unrealized_gain,
                    quote_source_identifier=quote.quote_source_identifier,
                )
            )

        updated_balances = self._mark_currency_balances(
            portfolio,
            as_of=timestamp,
            sources=sources,
        )
        expected_change += sum(
            updated.base_value - prior.base_value
            for prior, updated in zip(
                portfolio.currency_balances,
                updated_balances,
                strict=True,
            )
        )
        expected_change = round(expected_change, 8)
        digest = hashlib.sha256(
            "|".join(
                (
                    portfolio.identifier,
                    timestamp.isoformat(),
                    self.policy.version,
                    *sorted(dict.fromkeys(sources)),
                )
            ).encode("utf-8")
        ).hexdigest()[:24]
        ending = CanonicalPortfolioSnapshot(
            identifier=f"portfolio-mark:{portfolio.portfolio_code}:{timestamp.isoformat()}:{digest}",
            portfolio_code=portfolio.portfolio_code,
            display_name=portfolio.display_name,
            constraint_profile=portfolio.constraint_profile,
            as_of=timestamp,
            starting_capital=portfolio.starting_capital,
            cash_amount=portfolio.cash_amount,
            positions=tuple(updated_positions),
            implementation_events=portfolio.implementation_events,
            source_identifiers=tuple(
                dict.fromkeys(
                    portfolio.source_identifiers
                    + tuple(sources)
                    + (self.policy.version,)
                )
            ),
            schema_version=portfolio.schema_version,
            base_currency=portfolio.base_currency,
            currency_balances=updated_balances,
        )
        mark_change = round(ending.nav - portfolio.nav, 8)
        difference = round(mark_change - expected_change, 8)
        complete = (
            abs(difference) <= self.policy.reconciliation_tolerance
            and abs(ending.accounting_residual) <= self.policy.reconciliation_tolerance
        )
        if not complete:
            raise PortfolioPerformanceError(
                "portfolio mark-to-market did not reconcile: "
                f"valuation_difference={difference:.8f}, "
                f"accounting_residual={ending.accounting_residual:.8f}"
            )
        self.portfolio_store.verify_integrity()
        self.portfolio_store.append(ending)
        self.portfolio_store.verify_integrity()
        return PortfolioValuationReport(
            identifier=f"valuation-report:{ending.identifier}",
            as_of=timestamp,
            beginning_snapshot_identifier=portfolio.identifier,
            ending_snapshot_identifier=ending.identifier,
            beginning_nav=portfolio.nav,
            ending_nav=ending.nav,
            mark_change_base=mark_change,
            expected_mark_change_base=expected_change,
            reconciliation_difference=difference,
            total_pnl=ending.total_pnl,
            realized_pnl=ending.realized_pnl,
            unrealized_pnl=ending.unrealized_pnl,
            cash_fx_pnl=ending.cash_fx_pnl,
            non_trade_pnl=ending.non_trade_pnl,
            net_external_flows=ending.net_external_flows,
            accounting_residual=ending.accounting_residual,
            position_changes=tuple(position_changes),
            policy_version=self.policy.version,
            complete=True,
        )

    def _mark_currency_balances(
        self,
        portfolio: CanonicalPortfolioSnapshot,
        *,
        as_of: datetime,
        sources: list[str],
    ) -> tuple[CanonicalCurrencyBalance, ...]:
        if not portfolio.currency_balances:
            return ()
        if self.currency_rate_provider is None:
            raise PortfolioPerformanceError(
                "non-base cash balances require a currency-rate provider"
            )
        currencies = tuple(item.currency for item in portfolio.currency_balances)
        marks = self.currency_rate_provider.rates(
            currencies,
            base_currency=portfolio.base_currency,
            as_of=as_of,
        )
        if not isinstance(marks, Mapping) or set(marks) != set(currencies):
            raise PortfolioPerformanceError(
                "currency-rate coverage must exactly match non-base cash balances"
            )
        result: list[CanonicalCurrencyBalance] = []
        for balance in portfolio.currency_balances:
            mark = marks[balance.currency]
            if not isinstance(mark, CurrencyRateMark):
                raise TypeError("currency-rate provider returned an invalid mark")
            if mark.currency != balance.currency or mark.base_currency != portfolio.base_currency:
                raise PortfolioPerformanceError("currency-rate identity does not match cash balance")
            if mark.observed_at > as_of:
                raise PortfolioPerformanceError("currency-rate evidence is future-known")
            if as_of - mark.observed_at > timedelta(minutes=self.policy.maximum_fx_age_minutes):
                raise PortfolioPerformanceError("currency-rate evidence is stale")
            sources.append(mark.source_identifier)
            result.append(
                CanonicalCurrencyBalance(
                    currency=balance.currency,
                    amount=balance.amount,
                    fx_rate_to_base=mark.rate_to_base,
                    updated_at=mark.observed_at,
                    fx_rate_source_identifier=mark.source_identifier,
                    cost_basis_base=balance.preserved_cost_basis_base,
                )
            )
        return tuple(result)

    @staticmethod
    def _validate_profile(
        position: CanonicalPortfolioPosition,
        profile: MultiAssetInstrumentProfile,
    ) -> None:
        if not isinstance(profile, MultiAssetInstrumentProfile):
            raise TypeError("profiles must contain MultiAssetInstrumentProfile values")
        if profile.symbol != position.symbol:
            raise PortfolioPerformanceError("profile symbol does not match position")
        if position.instrument_identifier is None:
            raise PortfolioPerformanceError(
                f"{position.symbol} is missing canonical instrument identity"
            )
        if profile.instrument_identifier != position.instrument_identifier:
            raise PortfolioPerformanceError("profile instrument does not match position")
        if position.venue is None or profile.venue != position.venue:
            raise PortfolioPerformanceError("profile venue does not match position")
        if profile.price_currency != position.price_currency:
            raise PortfolioPerformanceError("profile currency does not match position")
        if abs(profile.contract_multiplier - position.contract_multiplier) > 1e-12:
            raise PortfolioPerformanceError("profile contract multiplier does not match position")

    def _validate_quote(
        self,
        *,
        quote: MultiAssetQuote,
        position: CanonicalPortfolioPosition,
        profile: MultiAssetInstrumentProfile,
        as_of: datetime,
        base_currency: str,
    ) -> None:
        if not isinstance(quote, MultiAssetQuote):
            raise TypeError("quote provider returned an invalid quote")
        if quote.symbol != position.symbol:
            raise PortfolioPerformanceError("quote symbol does not match position")
        if quote.instrument_identifier != profile.instrument_identifier:
            raise PortfolioPerformanceError("quote instrument does not match position")
        if quote.venue != profile.venue:
            raise PortfolioPerformanceError("quote venue does not match position")
        if quote.price_currency != profile.price_currency:
            raise PortfolioPerformanceError("quote currency does not match position")
        if quote.observed_at > as_of or quote.fx_observed_at > as_of:
            raise PortfolioPerformanceError("quote or FX evidence is future-known")
        if as_of - quote.observed_at > timedelta(minutes=self.policy.maximum_quote_age_minutes):
            raise PortfolioPerformanceError("portfolio valuation quote is stale")
        if as_of - quote.fx_observed_at > timedelta(minutes=self.policy.maximum_fx_age_minutes):
            raise PortfolioPerformanceError("portfolio valuation FX evidence is stale")
        if profile.price_currency == base_currency and abs(quote.fx_rate_to_base - 1.0) > 1e-12:
            raise PortfolioPerformanceError("base-currency quote must use an FX rate of 1.0")
        if quote.halted:
            raise PortfolioPerformanceError("halted instruments cannot receive a fresh executable mark")


class PortfolioCashFlowKind(str, Enum):
    DIVIDEND = "dividend"
    INTEREST = "interest"
    COUPON = "coupon"
    FEE = "fee"
    TAX = "tax"
    CORPORATE_ACTION = "corporate_action"
    VARIATION_MARGIN = "variation_margin"
    CONTRIBUTION = "contribution"
    WITHDRAWAL = "withdrawal"


@dataclass(frozen=True, slots=True)
class PortfolioCashFlowBooking:
    event_identifier: str
    snapshot_identifier: str
    kind: PortfolioCashFlowKind
    amount_base: float
    as_of: datetime
    total_pnl: float
    net_external_flows: float
    accounting_residual: float
    real_money_authorized: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "event_identifier": self.event_identifier,
            "snapshot_identifier": self.snapshot_identifier,
            "kind": self.kind.value,
            "amount_base": self.amount_base,
            "as_of": self.as_of.isoformat(),
            "total_pnl": self.total_pnl,
            "net_external_flows": self.net_external_flows,
            "accounting_residual": self.accounting_residual,
            "real_money_authorized": False,
            "schema_version": "portfolio-cash-flow-booking.v1",
        }


class PortfolioCashFlowService:
    """Book dividends, interest, fees, taxes, lifecycle cash and external flows."""

    _EXTERNAL = {
        PortfolioCashFlowKind.CONTRIBUTION,
        PortfolioCashFlowKind.WITHDRAWAL,
    }
    _NEGATIVE = {PortfolioCashFlowKind.FEE, PortfolioCashFlowKind.TAX, PortfolioCashFlowKind.WITHDRAWAL}
    _POSITIVE = {PortfolioCashFlowKind.DIVIDEND, PortfolioCashFlowKind.INTEREST, PortfolioCashFlowKind.COUPON, PortfolioCashFlowKind.CONTRIBUTION}

    def __init__(self, store: SQLiteCanonicalPortfolioStore) -> None:
        if not isinstance(store, SQLiteCanonicalPortfolioStore):
            raise TypeError("store must be SQLiteCanonicalPortfolioStore")
        self.store = store

    def book(
        self,
        *,
        portfolio: CanonicalPortfolioSnapshot,
        event_identifier: str,
        kind: PortfolioCashFlowKind,
        amount_base: float,
        as_of: datetime,
        source_identifier: str,
        rationale: str,
        symbol: str | None = None,
        instrument_identifier: str | None = None,
    ) -> PortfolioCashFlowBooking:
        if not isinstance(portfolio, CanonicalPortfolioSnapshot):
            raise TypeError("portfolio must be a CanonicalPortfolioSnapshot")
        if not isinstance(kind, PortfolioCashFlowKind):
            raise TypeError("kind must be PortfolioCashFlowKind")
        timestamp = _aware(as_of, field_name="as_of")
        if portfolio.as_of > timestamp:
            raise PortfolioPerformanceError("cash flow cannot predate the portfolio")
        amount = _number(amount_base, field_name="amount_base")
        if amount == 0.0:
            raise ValueError("amount_base cannot be zero")
        if kind in self._NEGATIVE and amount > 0.0:
            raise ValueError(f"{kind.value} must use a negative amount")
        if kind in self._POSITIVE and amount < 0.0:
            raise ValueError(f"{kind.value} must use a positive amount")
        next_cash = round(portfolio.cash_amount + amount, 8)
        if next_cash < 0.0:
            raise PortfolioPerformanceError("cash flow would make base-currency cash negative")
        identifier = _text(event_identifier, field_name="event_identifier")
        source = _text(source_identifier, field_name="source_identifier")
        reason = _text(rationale, field_name="rationale")
        resolved_symbol = None if symbol is None else _text(symbol, field_name="symbol").upper()
        resolved_instrument = (
            None
            if instrument_identifier is None
            else _text(instrument_identifier, field_name="instrument_identifier")
        )
        if any(item.identifier == identifier for item in portfolio.implementation_events):
            existing = next(
                item
                for item in portfolio.implementation_events
                if item.identifier == identifier
            )
            same = (
                existing.action == kind.value.upper()
                and abs(
                    existing.non_trade_pnl_base
                    + existing.external_flow_amount_base
                    - amount
                )
                <= 1e-8
                and existing.source_identifier == source
                and existing.rationale == reason
                and existing.symbol == resolved_symbol
                and existing.instrument_identifier == resolved_instrument
            )
            if not same:
                raise PortfolioPerformanceError(
                    "cash-flow event identifier already exists with different content"
                )
            return PortfolioCashFlowBooking(
                event_identifier=identifier,
                snapshot_identifier=portfolio.identifier,
                kind=kind,
                amount_base=amount,
                as_of=timestamp,
                total_pnl=portfolio.total_pnl,
                net_external_flows=portfolio.net_external_flows,
                accounting_residual=portfolio.accounting_residual,
            )
        event = CanonicalImplementationEvent(
            identifier=identifier,
            occurred_at=timestamp,
            action=kind.value,
            symbol=resolved_symbol,
            instrument_identifier=resolved_instrument,
            quantity=0.0,
            price=0.0,
            gross_amount=abs(amount),
            cost_amount=abs(amount) if kind in {PortfolioCashFlowKind.FEE, PortfolioCashFlowKind.TAX} else 0.0,
            non_trade_pnl_base=0.0 if kind in self._EXTERNAL else amount,
            external_flow_amount_base=amount if kind in self._EXTERNAL else 0.0,
            rationale=reason,
            source_identifier=source,
            asset_class="cash_flow",
            price_currency=portfolio.base_currency,
            settlement_currency=portfolio.base_currency,
            fx_rate_to_base=1.0,
        )
        digest = hashlib.sha256(
            f"{portfolio.identifier}|{identifier}|{kind.value}|{amount}|{timestamp.isoformat()}".encode("utf-8")
        ).hexdigest()[:24]
        ending = CanonicalPortfolioSnapshot(
            identifier=f"portfolio-cash-flow:{portfolio.portfolio_code}:{digest}",
            portfolio_code=portfolio.portfolio_code,
            display_name=portfolio.display_name,
            constraint_profile=portfolio.constraint_profile,
            as_of=timestamp,
            starting_capital=portfolio.starting_capital,
            cash_amount=next_cash,
            positions=portfolio.positions,
            implementation_events=portfolio.implementation_events + (event,),
            source_identifiers=tuple(
                dict.fromkeys(portfolio.source_identifiers + (event.source_identifier,))
            ),
            schema_version=portfolio.schema_version,
            base_currency=portfolio.base_currency,
            currency_balances=portfolio.currency_balances,
        )
        if abs(ending.accounting_residual) > 0.01:
            raise PortfolioPerformanceError(
                f"cash-flow booking did not reconcile: {ending.accounting_residual:.8f}"
            )
        self.store.verify_integrity()
        self.store.append(ending)
        self.store.verify_integrity()
        return PortfolioCashFlowBooking(
            event_identifier=identifier,
            snapshot_identifier=ending.identifier,
            kind=kind,
            amount_base=amount,
            as_of=timestamp,
            total_pnl=ending.total_pnl,
            net_external_flows=ending.net_external_flows,
            accounting_residual=ending.accounting_residual,
        )


@dataclass(frozen=True, slots=True)
class PortfolioAccountingMigrationReport:
    identifier: str
    beginning_snapshot_identifier: str
    ending_snapshot_identifier: str
    enriched_sell_events: int
    beginning_accounting_residual: float
    ending_accounting_residual: float
    as_of: datetime
    complete: bool
    real_money_authorized: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "beginning_snapshot_identifier": self.beginning_snapshot_identifier,
            "ending_snapshot_identifier": self.ending_snapshot_identifier,
            "enriched_sell_events": self.enriched_sell_events,
            "beginning_accounting_residual": self.beginning_accounting_residual,
            "ending_accounting_residual": self.ending_accounting_residual,
            "as_of": self.as_of.isoformat(),
            "complete": self.complete,
            "real_money_authorized": False,
            "schema_version": "portfolio-accounting-migration-report.v1",
        }


class PortfolioAccountingMigrationService:
    """Backfill realized P&L fields from complete historical paper fills."""

    def __init__(
        self,
        store: SQLiteCanonicalPortfolioStore,
        *,
        tolerance: float = 0.01,
    ) -> None:
        if not isinstance(store, SQLiteCanonicalPortfolioStore):
            raise TypeError("store must be SQLiteCanonicalPortfolioStore")
        resolved = _number(tolerance, field_name="tolerance")
        if resolved < 0.0:
            raise ValueError("tolerance cannot be negative")
        self.store = store
        self.tolerance = resolved

    @staticmethod
    def _key(event: CanonicalImplementationEvent) -> str:
        if event.instrument_identifier is not None:
            return event.instrument_identifier
        if event.symbol is None:
            raise PortfolioPerformanceError(
                "trade history is missing both instrument identity and symbol"
            )
        return f"legacy-symbol:{event.symbol}"

    def enrich(
        self,
        *,
        portfolio: CanonicalPortfolioSnapshot,
        as_of: datetime,
        source_identifier: str,
    ) -> PortfolioAccountingMigrationReport:
        if not isinstance(portfolio, CanonicalPortfolioSnapshot):
            raise TypeError("portfolio must be a CanonicalPortfolioSnapshot")
        timestamp = _aware(as_of, field_name="as_of")
        if portfolio.as_of > timestamp:
            raise PortfolioPerformanceError("migration cannot predate the portfolio")
        source = _text(source_identifier, field_name="source_identifier")
        sells = tuple(
            item for item in portfolio.implementation_events if item.action == "SELL"
        )
        if (
            abs(portfolio.accounting_residual) <= self.tolerance
            and all(item.cost_basis_relieved_base > 0.0 for item in sells)
        ):
            return PortfolioAccountingMigrationReport(
                identifier=f"accounting-migration-report:{portfolio.identifier}",
                beginning_snapshot_identifier=portfolio.identifier,
                ending_snapshot_identifier=portfolio.identifier,
                enriched_sell_events=0,
                beginning_accounting_residual=portfolio.accounting_residual,
                ending_accounting_residual=portfolio.accounting_residual,
                as_of=timestamp,
                complete=True,
            )
        ledger: dict[str, dict[str, float]] = {}
        enriched_events: list[CanonicalImplementationEvent] = []
        enriched_sells = 0
        for event in sorted(
            portfolio.implementation_events,
            key=lambda item: (item.occurred_at, item.identifier),
        ):
            if event.action not in {"BUY", "SELL", "SPLIT"}:
                enriched_events.append(event)
                continue
            key = self._key(event)
            account = ledger.setdefault(
                key,
                {"quantity": 0.0, "local_cost": 0.0, "base_cost": 0.0},
            )
            if event.action == "BUY":
                account["quantity"] = round(account["quantity"] + event.quantity, 12)
                account["local_cost"] = round(
                    account["local_cost"] + event.gross_amount + event.cost_amount,
                    12,
                )
                account["base_cost"] = round(
                    account["base_cost"]
                    + event.gross_amount_base
                    + event.cost_amount_base,
                    8,
                )
                enriched_events.append(
                    replace(
                        event,
                        cost_basis_relieved=0.0,
                        cost_basis_relieved_base=0.0,
                        realized_pnl=0.0,
                        realized_pnl_base=0.0,
                    )
                )
                continue
            if event.action == "SPLIT":
                if account["quantity"] <= 0.0 or event.quantity <= 0.0:
                    raise PortfolioPerformanceError(
                        "split history cannot be replayed without an owned quantity"
                    )
                account["quantity"] = event.quantity
                enriched_events.append(event)
                continue
            if event.quantity > account["quantity"] + 1e-9:
                raise PortfolioPerformanceError(
                    f"sell {event.identifier} exceeds replayed owned quantity"
                )
            fraction = event.quantity / account["quantity"]
            relieved_local = round(account["local_cost"] * fraction, 12)
            relieved_base = round(account["base_cost"] * fraction, 8)
            realized_local = round(
                event.gross_amount - event.cost_amount - relieved_local,
                12,
            )
            realized_base = round(
                event.gross_amount_base - event.cost_amount_base - relieved_base,
                8,
            )
            account["quantity"] = round(account["quantity"] - event.quantity, 12)
            account["local_cost"] = round(
                max(0.0, account["local_cost"] - relieved_local),
                12,
            )
            account["base_cost"] = round(
                max(0.0, account["base_cost"] - relieved_base),
                8,
            )
            enriched = replace(
                event,
                cost_basis_relieved=relieved_local,
                cost_basis_relieved_base=relieved_base,
                realized_pnl=realized_local,
                realized_pnl_base=realized_base,
            )
            if enriched != event:
                enriched_sells += 1
            enriched_events.append(enriched)

        for position in portfolio.positions:
            key = (
                position.instrument_identifier
                if position.instrument_identifier is not None
                else f"legacy-symbol:{position.symbol}"
            )
            account = ledger.get(key)
            if account is None:
                continue
            if abs(account["quantity"] - position.quantity) > 1e-8:
                raise PortfolioPerformanceError(
                    f"replayed quantity does not match current position for {position.symbol}"
                )
            if abs(account["local_cost"] - position.local_cost_basis) > self.tolerance:
                raise PortfolioPerformanceError(
                    f"replayed local cost basis does not match {position.symbol}"
                )
            if abs(account["base_cost"] - position.cost_basis) > self.tolerance:
                raise PortfolioPerformanceError(
                    f"replayed base cost basis does not match {position.symbol}"
                )

        ending = CanonicalPortfolioSnapshot(
            identifier=(
                f"portfolio-accounting-migration:{portfolio.portfolio_code}:"
                + hashlib.sha256(
                    f"{portfolio.identifier}|{timestamp.isoformat()}|{source}".encode(
                        "utf-8"
                    )
                ).hexdigest()[:24]
            ),
            portfolio_code=portfolio.portfolio_code,
            display_name=portfolio.display_name,
            constraint_profile=portfolio.constraint_profile,
            as_of=timestamp,
            starting_capital=portfolio.starting_capital,
            cash_amount=portfolio.cash_amount,
            positions=portfolio.positions,
            implementation_events=tuple(enriched_events),
            source_identifiers=tuple(
                dict.fromkeys(portfolio.source_identifiers + (source,))
            ),
            schema_version=portfolio.schema_version,
            base_currency=portfolio.base_currency,
            currency_balances=portfolio.currency_balances,
        )
        if abs(ending.accounting_residual) > self.tolerance:
            raise PortfolioPerformanceError(
                "historical fills are insufficient to reconcile portfolio P&L: "
                f"remaining_residual={ending.accounting_residual:.8f}"
            )
        self.store.verify_integrity()
        self.store.append(ending)
        self.store.verify_integrity()
        return PortfolioAccountingMigrationReport(
            identifier=f"accounting-migration-report:{ending.identifier}",
            beginning_snapshot_identifier=portfolio.identifier,
            ending_snapshot_identifier=ending.identifier,
            enriched_sell_events=enriched_sells,
            beginning_accounting_residual=portfolio.accounting_residual,
            ending_accounting_residual=ending.accounting_residual,
            as_of=timestamp,
            complete=True,
        )


@dataclass(frozen=True, slots=True)
class PortfolioPositionAdjustment:
    event_identifier: str
    snapshot_identifier: str
    symbol: str
    instrument_identifier: str
    split_ratio: float
    prior_quantity: float
    current_quantity: float
    as_of: datetime
    accounting_residual: float
    real_money_authorized: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "event_identifier": self.event_identifier,
            "snapshot_identifier": self.snapshot_identifier,
            "symbol": self.symbol,
            "instrument_identifier": self.instrument_identifier,
            "split_ratio": self.split_ratio,
            "prior_quantity": self.prior_quantity,
            "current_quantity": self.current_quantity,
            "as_of": self.as_of.isoformat(),
            "accounting_residual": self.accounting_residual,
            "real_money_authorized": False,
            "schema_version": "portfolio-position-adjustment.v1",
        }


class PortfolioPositionAdjustmentService:
    """Apply evidenced non-cash share splits without manufacturing P&L."""

    def __init__(self, store: SQLiteCanonicalPortfolioStore) -> None:
        if not isinstance(store, SQLiteCanonicalPortfolioStore):
            raise TypeError("store must be SQLiteCanonicalPortfolioStore")
        self.store = store

    def apply_split(
        self,
        *,
        portfolio: CanonicalPortfolioSnapshot,
        event_identifier: str,
        symbol: str,
        instrument_identifier: str,
        split_ratio: float,
        as_of: datetime,
        source_identifier: str,
        rationale: str,
    ) -> PortfolioPositionAdjustment:
        if not isinstance(portfolio, CanonicalPortfolioSnapshot):
            raise TypeError("portfolio must be a CanonicalPortfolioSnapshot")
        timestamp = _aware(as_of, field_name="as_of")
        if portfolio.as_of > timestamp:
            raise PortfolioPerformanceError("position adjustment cannot predate the portfolio")
        ratio = _number(split_ratio, field_name="split_ratio")
        if ratio <= 0.0:
            raise ValueError("split_ratio must be positive")
        resolved_symbol = _text(symbol, field_name="symbol").upper()
        resolved_instrument = _text(
            instrument_identifier,
            field_name="instrument_identifier",
        )
        matches = tuple(
            item
            for item in portfolio.positions
            if item.symbol == resolved_symbol
            and item.instrument_identifier == resolved_instrument
        )
        if len(matches) != 1:
            raise PortfolioPerformanceError(
                "split adjustment requires one exact owned instrument"
            )
        current = matches[0]
        adjusted = replace(
            current,
            quantity=round(current.quantity * ratio, 12),
            average_cost=round(current.average_cost / ratio, 12),
            average_cost_base=(
                None
                if current.average_cost_base is None
                else round(current.average_cost_base / ratio, 12)
            ),
            mark_price=round(current.mark_price / ratio, 12),
            updated_at=timestamp,
        )
        if abs(adjusted.cost_basis - current.cost_basis) > 0.01:
            raise PortfolioPerformanceError("split changed preserved cost basis")
        if abs(adjusted.market_value - current.market_value) > 0.01:
            raise PortfolioPerformanceError("split manufactured market value")
        identifier = _text(event_identifier, field_name="event_identifier")
        if any(item.identifier == identifier for item in portfolio.implementation_events):
            raise PortfolioPerformanceError(
                "position-adjustment event identifier already exists"
            )
        event = CanonicalImplementationEvent(
            identifier=identifier,
            occurred_at=timestamp,
            action="split",
            symbol=current.symbol,
            instrument_identifier=resolved_instrument,
            venue=current.venue,
            asset_class=current.asset_class,
            quantity=adjusted.quantity,
            price=adjusted.mark_price,
            gross_amount=0.0,
            cost_amount=0.0,
            contract_multiplier=current.contract_multiplier,
            rationale=_text(rationale, field_name="rationale"),
            source_identifier=_text(
                source_identifier,
                field_name="source_identifier",
            ),
            price_currency=current.price_currency,
            settlement_currency=current.settlement_currency,
            fx_rate_to_base=current.fx_rate_to_base,
            fx_rate_source_identifier=current.fx_rate_source_identifier,
        )
        positions = tuple(
            adjusted if item is current else item for item in portfolio.positions
        )
        digest = hashlib.sha256(
            f"{portfolio.identifier}|{identifier}|{ratio}|{timestamp.isoformat()}".encode("utf-8")
        ).hexdigest()[:24]
        ending = CanonicalPortfolioSnapshot(
            identifier=f"portfolio-position-adjustment:{portfolio.portfolio_code}:{digest}",
            portfolio_code=portfolio.portfolio_code,
            display_name=portfolio.display_name,
            constraint_profile=portfolio.constraint_profile,
            as_of=timestamp,
            starting_capital=portfolio.starting_capital,
            cash_amount=portfolio.cash_amount,
            positions=positions,
            implementation_events=portfolio.implementation_events + (event,),
            source_identifiers=tuple(
                dict.fromkeys(portfolio.source_identifiers + (event.source_identifier,))
            ),
            schema_version=portfolio.schema_version,
            base_currency=portfolio.base_currency,
            currency_balances=portfolio.currency_balances,
        )
        residual_change = round(
            ending.accounting_residual - portfolio.accounting_residual,
            8,
        )
        if abs(residual_change) > 0.01:
            raise PortfolioPerformanceError(
                "position adjustment changed the accounting residual"
            )
        self.store.verify_integrity()
        self.store.append(ending)
        self.store.verify_integrity()
        return PortfolioPositionAdjustment(
            event_identifier=identifier,
            snapshot_identifier=ending.identifier,
            symbol=current.symbol,
            instrument_identifier=resolved_instrument,
            split_ratio=ratio,
            prior_quantity=current.quantity,
            current_quantity=adjusted.quantity,
            as_of=timestamp,
            accounting_residual=ending.accounting_residual,
        )


__all__ = [
    "CurrencyRateMark",
    "CurrencyRateProvider",
    "PortfolioAccountingMigrationReport",
    "PortfolioAccountingMigrationService",
    "PortfolioCashFlowBooking",
    "PortfolioCashFlowKind",
    "PortfolioCashFlowService",
    "PortfolioMarkToMarketService",
    "PortfolioPerformanceError",
    "PortfolioValuationPolicy",
    "PortfolioValuationReport",
    "PortfolioPositionAdjustment",
    "PortfolioPositionAdjustmentService",
    "PositionValuationChange",
]
