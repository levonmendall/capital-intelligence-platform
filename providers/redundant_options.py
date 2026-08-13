"""Governed redundant router for U.S. option evidence.

Alpaca's authenticated indicative option feed is the opportunity-complete primary path.
Tradier supplies independent active-contract history/chain validation where available,
and Massive remains a bounded tertiary source. Databento is intentionally absent from
the active routing graph.

Provider switching never synthesizes evidence and never weakens option qualification,
CIO, construction, or paper-only controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Mapping, Sequence

from providers.alpaca_indicative_options import (
    ALPACA_INDICATIVE_OPTIONS_DATASET,
    AlpacaIndicativeOptionBar,
    AlpacaIndicativeOptionSelection,
    AlpacaIndicativeOptionsError,
    AlpacaIndicativeOptionsProvider,
)
from providers.massive_options import (
    MASSIVE_OPRA_DATASET,
    MassiveOptionBar,
    MassiveOptionSelection,
    MassiveOptionsError,
    MassiveOptionsProvider,
)
from providers.redundancy_audit import ProviderCapabilityKey, current_redundancy_ledger
from providers.single_pass_massive_options import SinglePassMassiveOptionsProvider
from providers.tradier_market_data import (
    TRADIER_OPTIONS_DATASET,
    TradierMarketDataError,
    TradierMarketDataProvider,
    TradierOptionBar,
    TradierOptionSelection,
)

_OPPORTUNITY_COMPLETE_MAX_EXPIRATIONS = 1_000
_MASSIVE_BASIC_SAFE_MAX_EXPIRATIONS = 1
_TRADIER_OPTIONS_DATASET = TRADIER_OPTIONS_DATASET
_TRADIER_HISTORY_DATASET = "markets/history"


class RedundantOptionsError(RuntimeError):
    """Raised when no configured certified option provider can satisfy the request."""

    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _failure_class(error: BaseException | None) -> str:
    if error is None:
        return "none"
    status = getattr(error, "status_code", None)
    if status in {401, 403}:
        return "authentication_or_entitlement"
    if status == 402:
        return "access_or_credit_cap"
    if status == 429:
        return "rate_limit"
    if isinstance(status, int) and 500 <= status <= 599:
        return "provider_5xx"
    if bool(getattr(error, "retryable", False)):
        return "transient_provider_failure"
    return "provider_evidence_unavailable"


def _failure_detail(error: BaseException | None) -> str:
    if error is None:
        return "none"
    if not isinstance(error, (AlpacaIndicativeOptionsError, TradierMarketDataError, MassiveOptionsError, RedundantOptionsError)):
        return type(error).__name__
    detail = " ".join(str(error).strip().split())
    return (detail or type(error).__name__)[:300]


def _massive_ticker(raw_symbol: str) -> str:
    compact = "".join(str(raw_symbol).strip().upper().split())
    return compact if compact.startswith("O:") else f"O:{compact}"


def _alpaca_ticker(raw_symbol: str) -> str:
    compact = "".join(str(raw_symbol).strip().upper().split())
    return compact[2:] if compact.startswith("O:") else compact


def _tradier_ticker(raw_symbol: str) -> str:
    return _alpaca_ticker(raw_symbol)


@dataclass(frozen=True, slots=True)
class RedundantOptionDefinition:
    symbol: str
    raw_symbol: str
    underlying: str
    option_right: str
    expiration_at: datetime
    strike: float
    contract_multiplier: float
    session_date: date
    provider_kind: str
    provider_dataset: str
    provider_stype_in: str
    provider_instrument_id: int | None
    source_identifier: str


@dataclass(frozen=True, slots=True)
class RedundantOptionBar:
    raw_symbol: str
    observed_at: datetime
    close: float
    volume: float
    provider_kind: str
    source_identifier: str


@dataclass(frozen=True, slots=True)
class RedundantOptionSelection:
    definition: RedundantOptionDefinition
    bar: RedundantOptionBar


def _adapt_alpaca_bar(bar: AlpacaIndicativeOptionBar, *, raw_symbol: str | None = None) -> RedundantOptionBar:
    return RedundantOptionBar(
        raw_symbol=raw_symbol or bar.raw_symbol,
        observed_at=bar.observed_at,
        close=bar.close,
        volume=bar.volume,
        provider_kind="alpaca_indicative",
        source_identifier=bar.source_identifier,
    )


def _adapt_alpaca_selection(selection: AlpacaIndicativeOptionSelection) -> RedundantOptionSelection:
    definition = selection.definition
    return RedundantOptionSelection(
        definition=RedundantOptionDefinition(
            symbol=definition.symbol,
            raw_symbol=definition.raw_symbol,
            underlying=definition.underlying,
            option_right=definition.option_right,
            expiration_at=definition.expiration_at,
            strike=definition.strike,
            contract_multiplier=definition.contract_multiplier,
            session_date=definition.session_date,
            provider_kind="alpaca_indicative",
            provider_dataset=ALPACA_INDICATIVE_OPTIONS_DATASET,
            provider_stype_in="raw_symbol",
            provider_instrument_id=None,
            source_identifier=definition.source_identifier,
        ),
        bar=_adapt_alpaca_bar(selection.bar),
    )


def _adapt_massive_bar(bar: MassiveOptionBar, *, raw_symbol: str | None = None) -> RedundantOptionBar:
    return RedundantOptionBar(
        raw_symbol=raw_symbol or bar.raw_symbol,
        observed_at=bar.observed_at,
        close=bar.close,
        volume=bar.volume,
        provider_kind="massive",
        source_identifier=bar.source_identifier,
    )


def _adapt_massive_selection(selection: MassiveOptionSelection) -> RedundantOptionSelection:
    definition = selection.definition
    return RedundantOptionSelection(
        definition=RedundantOptionDefinition(
            symbol=definition.symbol,
            raw_symbol=definition.raw_symbol,
            underlying=definition.underlying,
            option_right=definition.option_right,
            expiration_at=definition.expiration_at,
            strike=definition.strike,
            contract_multiplier=definition.contract_multiplier,
            session_date=definition.session_date,
            provider_kind="massive",
            provider_dataset=MASSIVE_OPRA_DATASET,
            provider_stype_in="raw_symbol",
            provider_instrument_id=None,
            source_identifier=definition.source_identifier,
        ),
        bar=_adapt_massive_bar(selection.bar),
    )


def _adapt_tradier_bar(
    bar: TradierOptionBar,
    *,
    raw_symbol: str | None = None,
) -> RedundantOptionBar:
    return RedundantOptionBar(
        raw_symbol=raw_symbol or bar.raw_symbol,
        observed_at=bar.observed_at,
        close=bar.close,
        volume=bar.volume,
        provider_kind="tradier",
        source_identifier=bar.source_identifier,
    )


def _adapt_tradier_selection(
    selection: TradierOptionSelection,
) -> RedundantOptionSelection:
    definition = selection.definition
    return RedundantOptionSelection(
        definition=RedundantOptionDefinition(
            symbol=definition.symbol,
            raw_symbol=definition.raw_symbol,
            underlying=definition.underlying,
            option_right=definition.option_right,
            expiration_at=definition.expiration_at,
            strike=definition.strike,
            contract_multiplier=definition.contract_multiplier,
            session_date=definition.session_date,
            provider_kind="tradier",
            provider_dataset=TRADIER_OPTIONS_DATASET,
            provider_stype_in="raw_symbol",
            provider_instrument_id=None,
            source_identifier=definition.source_identifier,
        ),
        bar=_adapt_tradier_bar(selection.bar),
    )


def _option_audit_keys(capability: str):
    ledger = current_redundancy_ledger()
    tradier_dataset = (
        _TRADIER_OPTIONS_DATASET
        if capability == "option_contract_selection"
        else _TRADIER_HISTORY_DATASET
    )
    return (
        ledger,
        ProviderCapabilityKey("alpaca_indicative", capability, ALPACA_INDICATIVE_OPTIONS_DATASET),
        ProviderCapabilityKey("tradier", capability, tradier_dataset),
        ProviderCapabilityKey("massive", capability, MASSIVE_OPRA_DATASET),
    )


def _selection_sources(selections: Sequence[RedundantOptionSelection]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(source for item in selections for source in (item.definition.source_identifier, item.bar.source_identifier) if source))


def _declare(ledger, key: ProviderCapabilityKey, *, configured: bool) -> None:
    if ledger is not None:
        ledger.declare(key, configured=configured, authenticated=False, routed=True, certified_for_evidence_role=True)


def _tradier_bars(provider: TradierMarketDataProvider, raw_symbol: str, *, as_of: datetime, history_days: int) -> tuple[RedundantOptionBar, ...]:
    symbol = _tradier_ticker(raw_symbol)
    rows = provider.daily_history(symbol, as_of=as_of, history_days=history_days)
    bars: list[RedundantOptionBar] = []
    for row in rows:
        observed = row.get("t")
        if not isinstance(observed, datetime):
            continue
        try:
            close = float(row.get("c"))
            volume = max(0.0, float(row.get("v", 0.0)))
        except (TypeError, ValueError):
            continue
        if close <= 0.0:
            continue
        bars.append(RedundantOptionBar(
            raw_symbol=raw_symbol,
            observed_at=observed,
            close=close,
            volume=volume,
            provider_kind="tradier",
            source_identifier=f"tradier:option-history:{symbol}:{observed.date().isoformat()}",
        ))
    return tuple(bars)


class RedundantOptionsProvider:
    """Alpaca indicative -> Tradier -> Massive governed option router."""

    redundant_options_provider = True

    def __init__(self, *, primary: AlpacaIndicativeOptionsProvider | None = None, secondary: TradierMarketDataProvider | None = None, fallback: MassiveOptionsProvider | None = None) -> None:
        self.primary = primary or AlpacaIndicativeOptionsProvider()
        self.secondary = secondary or TradierMarketDataProvider()
        self.fallback = fallback or SinglePassMassiveOptionsProvider()

    @property
    def configured(self) -> bool:
        return bool(self.primary.configured or self.secondary.configured or self.fallback.configured)

    @property
    def primary_configured(self) -> bool:
        return bool(self.primary.configured)

    @property
    def secondary_configured(self) -> bool:
        return bool(self.secondary.configured)

    @property
    def fallback_configured(self) -> bool:
        return bool(self.fallback.configured)

    def select_contracts(self, underlying: str, *, underlying_price: float, as_of: datetime, minimum_days_to_expiry: int, maximum_days_to_expiry: int, maximum_expirations: int = _OPPORTUNITY_COMPLETE_MAX_EXPIRATIONS, candidates_per_bucket: int = 8) -> tuple[RedundantOptionSelection, ...]:
        timestamp = _aware(as_of, field_name="as_of")
        if maximum_expirations < 1:
            raise ValueError("maximum_expirations must be positive")
        ledger, primary_key, secondary_key, fallback_key = _option_audit_keys("option_contract_selection")
        _declare(ledger, primary_key, configured=self.primary.configured)
        _declare(ledger, secondary_key, configured=self.secondary.configured)
        _declare(ledger, fallback_key, configured=self.fallback.configured)
        primary_error: BaseException | None = None
        secondary_error: BaseException | None = None
        fallback_error: BaseException | None = None
        if self.primary.configured:
            if ledger is not None:
                ledger.attempted(primary_key)
            try:
                selections = self.primary.select_contracts(
                    underlying,
                    underlying_price=underlying_price,
                    as_of=timestamp,
                    minimum_days_to_expiry=minimum_days_to_expiry,
                    maximum_days_to_expiry=maximum_days_to_expiry,
                    maximum_expirations=maximum_expirations,
                    candidates_per_bucket=candidates_per_bucket,
                )
                adapted = tuple(_adapt_alpaca_selection(item) for item in selections)
                if adapted:
                    if ledger is not None:
                        ledger.used(primary_key, source_identifiers=_selection_sources(adapted), failed_over=False)
                    return adapted
                if ledger is not None:
                    ledger.failed(primary_key, "insufficient_evidence")
            except AlpacaIndicativeOptionsError as error:
                primary_error = error
                if ledger is not None:
                    ledger.failed(primary_key, _failure_class(error))
        if self.secondary.configured:
            if ledger is not None:
                ledger.attempted(secondary_key)
            try:
                selections = self.secondary.select_contracts(
                    underlying,
                    underlying_price=underlying_price,
                    as_of=timestamp,
                    minimum_days_to_expiry=minimum_days_to_expiry,
                    maximum_days_to_expiry=maximum_days_to_expiry,
                    maximum_expirations=maximum_expirations,
                    candidates_per_bucket=candidates_per_bucket,
                )
                adapted = tuple(_adapt_tradier_selection(item) for item in selections)
                if adapted:
                    if ledger is not None:
                        ledger.used(
                            secondary_key,
                            source_identifiers=_selection_sources(adapted),
                            failed_over=bool(self.primary.configured),
                        )
                    return adapted
                secondary_error = RedundantOptionsError(
                    "Tradier returned no complete eligible-expiration option evidence"
                )
                if ledger is not None:
                    ledger.failed(secondary_key, "insufficient_evidence")
            except TradierMarketDataError as error:
                secondary_error = error
                if ledger is not None:
                    ledger.failed(secondary_key, _failure_class(error))
        if self.fallback.configured:
            if maximum_expirations > _MASSIVE_BASIC_SAFE_MAX_EXPIRATIONS:
                fallback_error = RedundantOptionsError("Massive fallback cannot certify complete expiration opportunity coverage within the governed request budget")
                if ledger is not None:
                    ledger.failed(fallback_key, "incomplete_opportunity_coverage")
            else:
                if ledger is not None:
                    ledger.attempted(fallback_key)
                try:
                    selections = self.fallback.select_contracts(
                        underlying,
                        underlying_price=underlying_price,
                        as_of=timestamp,
                        minimum_days_to_expiry=minimum_days_to_expiry,
                        maximum_days_to_expiry=maximum_days_to_expiry,
                        maximum_expirations=maximum_expirations,
                        candidates_per_bucket=1,
                    )
                    adapted = tuple(_adapt_massive_selection(item) for item in selections)
                    if adapted:
                        if ledger is not None:
                            ledger.used(
                                fallback_key,
                                source_identifiers=_selection_sources(adapted),
                                failed_over=bool(
                                    self.primary.configured or self.secondary.configured
                                ),
                            )
                        return adapted
                    if ledger is not None:
                        ledger.failed(fallback_key, "insufficient_evidence")
                except MassiveOptionsError as error:
                    fallback_error = error
                    if ledger is not None:
                        ledger.failed(fallback_key, _failure_class(error))
        active_error = fallback_error or secondary_error or primary_error
        if active_error is not None:
            raise RedundantOptionsError(
                "Certified option providers cannot supply opportunity-complete evidence; "
                f"primary={_failure_class(primary_error)}; "
                f"secondary={_failure_class(secondary_error)}; "
                f"fallback={_failure_class(fallback_error)}; "
                f"primary_detail={_failure_detail(primary_error)}; "
                f"secondary_detail={_failure_detail(secondary_error)}; "
                f"fallback_detail={_failure_detail(fallback_error)}",
                status_code=getattr(active_error, "status_code", None),
                retryable=bool(getattr(active_error, "retryable", False)),
            ) from active_error
        return ()

    def latest_daily_bars(self, instruments: Sequence[tuple[int | None, str]], *, as_of: datetime, history_days: int = 45) -> tuple[date, Mapping[str, tuple[RedundantOptionBar, ...]]]:
        timestamp = _aware(as_of, field_name="as_of")
        ledger, primary_key, secondary_key, fallback_key = _option_audit_keys("option_daily_history")
        _declare(ledger, primary_key, configured=self.primary.configured)
        _declare(ledger, secondary_key, configured=self.secondary.configured)
        _declare(ledger, fallback_key, configured=self.fallback.configured)
        normalized = tuple((instrument_id, str(raw_symbol).strip().upper()) for instrument_id, raw_symbol in instruments if str(raw_symbol).strip())
        if not normalized:
            return timestamp.date(), {}
        result: dict[str, tuple[RedundantOptionBar, ...]] = {}
        primary_error: BaseException | None = None
        secondary_error: BaseException | None = None
        fallback_error: BaseException | None = None
        if self.primary.configured:
            aliases = {_alpaca_ticker(raw_symbol): raw_symbol for _, raw_symbol in normalized}
            if ledger is not None:
                ledger.attempted(primary_key)
            try:
                _session, primary_bars = self.primary.latest_daily_bars(tuple((None, symbol) for symbol in aliases), as_of=timestamp, history_days=history_days)
                sources: list[str] = []
                for alpaca_symbol, bars in primary_bars.items():
                    normalized_alpaca = _alpaca_ticker(str(alpaca_symbol))
                    original = aliases.get(normalized_alpaca, normalized_alpaca)
                    adapted = tuple(_adapt_alpaca_bar(item, raw_symbol=original) for item in bars)
                    if adapted:
                        result[original] = adapted
                        sources.extend(item.source_identifier for item in adapted)
                if sources and ledger is not None:
                    ledger.used(primary_key, source_identifiers=tuple(dict.fromkeys(sources)), failed_over=False)
            except AlpacaIndicativeOptionsError as error:
                primary_error = error
                if ledger is not None:
                    ledger.failed(primary_key, _failure_class(error))
        missing = tuple(raw_symbol for _, raw_symbol in normalized if raw_symbol not in result)
        if missing and self.secondary.configured:
            if ledger is not None:
                ledger.attempted(secondary_key)
            sources: list[str] = []
            try:
                for raw_symbol in missing:
                    bars = _tradier_bars(self.secondary, raw_symbol, as_of=timestamp, history_days=history_days)
                    if bars:
                        result[raw_symbol] = bars
                        sources.extend(item.source_identifier for item in bars)
                if sources and ledger is not None:
                    ledger.used(secondary_key, source_identifiers=tuple(dict.fromkeys(sources)), failed_over=bool(self.primary.configured))
            except TradierMarketDataError as error:
                secondary_error = error
                if ledger is not None:
                    ledger.failed(secondary_key, _failure_class(error))
        missing = tuple(raw_symbol for _, raw_symbol in normalized if raw_symbol not in result)
        if missing and self.fallback.configured:
            aliases = {_massive_ticker(raw_symbol): raw_symbol for raw_symbol in missing}
            if ledger is not None:
                ledger.attempted(fallback_key)
            try:
                _session, fallback_bars = self.fallback.latest_daily_bars(tuple((None, ticker) for ticker in aliases), as_of=timestamp, history_days=history_days)
                sources: list[str] = []
                for massive_symbol, bars in fallback_bars.items():
                    normalized_massive = _massive_ticker(str(massive_symbol))
                    original = aliases.get(normalized_massive, normalized_massive)
                    adapted = tuple(_adapt_massive_bar(item, raw_symbol=original) for item in bars)
                    if adapted:
                        result[original] = adapted
                        sources.extend(item.source_identifier for item in adapted)
                if sources and ledger is not None:
                    ledger.used(fallback_key, source_identifiers=tuple(dict.fromkeys(sources)), failed_over=True)
            except MassiveOptionsError as error:
                fallback_error = error
                if ledger is not None:
                    ledger.failed(fallback_key, _failure_class(error))
        if not result and any(error is not None for error in (primary_error, secondary_error, fallback_error)):
            active_error = fallback_error or secondary_error or primary_error
            raise RedundantOptionsError(
                "Certified option daily bars are unavailable; "
                f"primary={_failure_class(primary_error)}; secondary={_failure_class(secondary_error)}; fallback={_failure_class(fallback_error)}; "
                f"primary_detail={_failure_detail(primary_error)}; secondary_detail={_failure_detail(secondary_error)}; fallback_detail={_failure_detail(fallback_error)}",
                status_code=getattr(active_error, "status_code", None),
                retryable=bool(getattr(active_error, "retryable", False)),
            ) from active_error
        session_date = max((bars[-1].observed_at.date() for bars in result.values() if bars), default=timestamp.date())
        return session_date, result


def build_redundant_options_provider(*, primary=None, secondary=None, fallback: MassiveOptionsProvider | None = None) -> RedundantOptionsProvider:
    """Build the active router while safely ignoring legacy Databento injection."""
    if isinstance(primary, RedundantOptionsProvider) or bool(getattr(primary, "redundant_options_provider", False)):
        return primary  # type: ignore[return-value]
    alpaca = primary if isinstance(primary, AlpacaIndicativeOptionsProvider) else None
    tradier = secondary if isinstance(secondary, TradierMarketDataProvider) else None
    if alpaca is None and isinstance(secondary, AlpacaIndicativeOptionsProvider):
        alpaca = secondary
    return RedundantOptionsProvider(primary=alpaca, secondary=tradier, fallback=fallback)


__all__ = [
    "RedundantOptionBar",
    "RedundantOptionDefinition",
    "RedundantOptionSelection",
    "RedundantOptionsError",
    "RedundantOptionsProvider",
    "build_redundant_options_provider",
]
