"""Governed primary/fallback router for U.S. option evidence.

Databento remains the preferred OPRA provider. Massive is an independent fallback when
Databento is unavailable, capped, rate-limited, unentitled, or otherwise unable to
supply the required evidence. Provider switching never synthesizes evidence and never
weakens the existing option qualification, CIO, construction, or paper-only controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Mapping, Sequence

from providers.databento_options import (
    DATABENTO_OPRA_DATASET,
    DatabentoOptionBar,
    DatabentoOptionSelection,
    DatabentoOptionsError,
    DatabentoOptionsProvider,
)
from providers.massive_options import (
    MASSIVE_OPRA_DATASET,
    MassiveOptionBar,
    MassiveOptionSelection,
    MassiveOptionsError,
    MassiveOptionsProvider,
)


class RedundantOptionsError(DatabentoOptionsError):
    """Raised when no configured certified option provider can satisfy the request."""


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


def _massive_ticker(raw_symbol: str) -> str:
    compact = "".join(str(raw_symbol).strip().upper().split())
    return compact if compact.startswith("O:") else f"O:{compact}"


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


def _adapt_databento_selection(
    selection: DatabentoOptionSelection,
) -> RedundantOptionSelection:
    definition = selection.definition
    bar = selection.bar
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
            provider_kind="databento",
            provider_dataset=DATABENTO_OPRA_DATASET,
            provider_stype_in="instrument_id",
            provider_instrument_id=definition.instrument_id,
            source_identifier=(
                "databento-opra-definition:"
                f"{definition.session_date.isoformat()}:{definition.symbol}"
            ),
        ),
        bar=_adapt_databento_bar(bar),
    )


def _adapt_databento_bar(bar: DatabentoOptionBar) -> RedundantOptionBar:
    return RedundantOptionBar(
        raw_symbol=bar.raw_symbol,
        observed_at=bar.observed_at,
        close=bar.close,
        volume=bar.volume,
        provider_kind="databento",
        source_identifier=(
            f"databento-opra-bar:{bar.raw_symbol}:{bar.observed_at.isoformat()}"
        ),
    )


def _adapt_massive_selection(selection: MassiveOptionSelection) -> RedundantOptionSelection:
    definition = selection.definition
    bar = selection.bar
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
        bar=_adapt_massive_bar(bar),
    )


def _adapt_massive_bar(
    bar: MassiveOptionBar,
    *,
    raw_symbol: str | None = None,
) -> RedundantOptionBar:
    return RedundantOptionBar(
        raw_symbol=raw_symbol or bar.raw_symbol,
        observed_at=bar.observed_at,
        close=bar.close,
        volume=bar.volume,
        provider_kind="massive",
        source_identifier=bar.source_identifier,
    )


class RedundantOptionsProvider:
    """Databento-primary, Massive-fallback option evidence router."""

    redundant_options_provider = True

    def __init__(
        self,
        *,
        primary: DatabentoOptionsProvider | None = None,
        fallback: MassiveOptionsProvider | None = None,
    ) -> None:
        self.primary = primary or DatabentoOptionsProvider()
        self.fallback = fallback or MassiveOptionsProvider()

    @property
    def configured(self) -> bool:
        return bool(self.primary.configured or self.fallback.configured)

    @property
    def primary_configured(self) -> bool:
        return bool(self.primary.configured)

    @property
    def fallback_configured(self) -> bool:
        return bool(self.fallback.configured)

    def select_contracts(
        self,
        underlying: str,
        *,
        underlying_price: float,
        as_of: datetime,
        minimum_days_to_expiry: int,
        maximum_days_to_expiry: int,
        maximum_expirations: int = 2,
        candidates_per_bucket: int = 8,
    ) -> tuple[RedundantOptionSelection, ...]:
        timestamp = _aware(as_of, field_name="as_of")
        primary_error: BaseException | None = None
        if self.primary.configured:
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
                if selections:
                    return tuple(_adapt_databento_selection(item) for item in selections)
            except DatabentoOptionsError as error:
                primary_error = error

        if self.fallback.configured:
            try:
                # Massive's basic REST path is request-limited. Keep the same
                # expiration/right policy but inspect the nearest priced contract in
                # each bucket so failover is bounded and does not lower any evidence,
                # price, expiry, or portfolio threshold.
                selections = self.fallback.select_contracts(
                    underlying,
                    underlying_price=underlying_price,
                    as_of=timestamp,
                    minimum_days_to_expiry=minimum_days_to_expiry,
                    maximum_days_to_expiry=maximum_days_to_expiry,
                    maximum_expirations=maximum_expirations,
                    candidates_per_bucket=1,
                )
                return tuple(_adapt_massive_selection(item) for item in selections)
            except MassiveOptionsError as fallback_error:
                raise RedundantOptionsError(
                    "Certified option providers are unavailable; "
                    f"primary={_failure_class(primary_error)}; "
                    f"fallback={_failure_class(fallback_error)}",
                    status_code=getattr(fallback_error, "status_code", None),
                    retryable=bool(getattr(fallback_error, "retryable", False)),
                ) from fallback_error

        if primary_error is not None:
            raise RedundantOptionsError(
                f"{primary_error}; no certified fallback is configured; "
                f"primary={_failure_class(primary_error)}",
                status_code=getattr(primary_error, "status_code", None),
                retryable=bool(getattr(primary_error, "retryable", False)),
            ) from primary_error
        return ()

    def latest_daily_bars(
        self,
        instruments: Sequence[tuple[int | None, str]],
        *,
        as_of: datetime,
        history_days: int = 45,
    ) -> tuple[date, Mapping[str, tuple[RedundantOptionBar, ...]]]:
        timestamp = _aware(as_of, field_name="as_of")
        normalized = tuple(
            (instrument_id, str(raw_symbol).strip().upper())
            for instrument_id, raw_symbol in instruments
            if str(raw_symbol).strip()
        )
        if not normalized:
            return timestamp.date(), {}

        result: dict[str, tuple[RedundantOptionBar, ...]] = {}
        primary_error: BaseException | None = None
        primary_instruments = tuple(
            (instrument_id, raw_symbol)
            for instrument_id, raw_symbol in normalized
            if isinstance(instrument_id, int)
            and not isinstance(instrument_id, bool)
            and instrument_id > 0
        )
        if self.primary.configured and primary_instruments:
            try:
                _session, primary_bars = self.primary.latest_daily_bars(
                    primary_instruments,
                    as_of=timestamp,
                    history_days=history_days,
                )
                for raw_symbol, bars in primary_bars.items():
                    result[str(raw_symbol).strip().upper()] = tuple(
                        _adapt_databento_bar(item) for item in bars
                    )
            except DatabentoOptionsError as error:
                primary_error = error

        missing = tuple(
            raw_symbol for _instrument_id, raw_symbol in normalized if raw_symbol not in result
        )
        fallback_error: BaseException | None = None
        if missing and self.fallback.configured:
            aliases = {_massive_ticker(raw_symbol): raw_symbol for raw_symbol in missing}
            try:
                _session, fallback_bars = self.fallback.latest_daily_bars(
                    tuple((None, ticker) for ticker in aliases),
                    as_of=timestamp,
                    history_days=history_days,
                )
                for massive_symbol, bars in fallback_bars.items():
                    normalized_massive = str(massive_symbol).strip().upper()
                    original_symbol = aliases.get(normalized_massive, normalized_massive)
                    result[original_symbol] = tuple(
                        _adapt_massive_bar(item, raw_symbol=original_symbol)
                        for item in bars
                    )
            except MassiveOptionsError as error:
                fallback_error = error

        if not result and (primary_error is not None or fallback_error is not None):
            active_error = fallback_error or primary_error
            raise RedundantOptionsError(
                f"{active_error}; certified option daily bars are unavailable; "
                f"primary={_failure_class(primary_error)}; "
                f"fallback={_failure_class(fallback_error)}",
                status_code=getattr(active_error, "status_code", None),
                retryable=bool(getattr(active_error, "retryable", False)),
            ) from active_error

        session_date = max(
            (
                bars[-1].observed_at.date()
                for bars in result.values()
                if bars
            ),
            default=timestamp.date(),
        )
        return session_date, result


def build_redundant_options_provider(
    *,
    primary: DatabentoOptionsProvider | RedundantOptionsProvider | None = None,
    fallback: MassiveOptionsProvider | None = None,
) -> RedundantOptionsProvider:
    if isinstance(primary, RedundantOptionsProvider) or bool(
        getattr(primary, "redundant_options_provider", False)
    ):
        return primary  # type: ignore[return-value]
    return RedundantOptionsProvider(primary=primary, fallback=fallback)


__all__ = [
    "RedundantOptionBar",
    "RedundantOptionDefinition",
    "RedundantOptionSelection",
    "RedundantOptionsError",
    "RedundantOptionsProvider",
    "build_redundant_options_provider",
]
