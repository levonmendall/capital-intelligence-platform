from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from providers.databento_options import (
    DatabentoOptionBar,
    DatabentoOptionDefinition,
    DatabentoOptionSelection,
    DatabentoOptionsError,
)
from providers.massive_options import (
    MassiveOptionBar,
    MassiveOptionDefinition,
    MassiveOptionSelection,
    MassiveOptionsError,
)
from providers.redundant_options import RedundantOptionsError, RedundantOptionsProvider


AS_OF = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)
EXPIRATION = AS_OF + timedelta(days=60)


def _databento_selection() -> DatabentoOptionSelection:
    definition = DatabentoOptionDefinition(
        symbol="SPY261010C00650000",
        raw_symbol="SPY   261010C00650000",
        instrument_id=12345,
        underlying="SPY",
        option_right="call",
        expiration_at=EXPIRATION,
        strike=650.0,
        contract_multiplier=100.0,
        session_date=date(2026, 8, 10),
    )
    return DatabentoOptionSelection(
        definition=definition,
        bar=DatabentoOptionBar(
            raw_symbol=definition.raw_symbol,
            observed_at=datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc),
            close=12.5,
            volume=100.0,
        ),
    )


def _massive_selection() -> MassiveOptionSelection:
    definition = MassiveOptionDefinition(
        symbol="SPY261010C00650000",
        raw_symbol="O:SPY261010C00650000",
        underlying="SPY",
        option_right="call",
        expiration_at=EXPIRATION,
        strike=650.0,
        contract_multiplier=100.0,
        session_date=date(2026, 8, 11),
        source_identifier="massive-opra-definition:2026-08-11:O:SPY261010C00650000",
    )
    return MassiveOptionSelection(
        definition=definition,
        bar=MassiveOptionBar(
            raw_symbol=definition.raw_symbol,
            observed_at=datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc),
            close=12.7,
            volume=120.0,
            source_identifier=(
                "massive-opra-bar:O:SPY261010C00650000:"
                "2026-08-10T20:00:00+00:00"
            ),
        ),
    )


class _HealthyPrimary:
    configured = True

    def __init__(self) -> None:
        self.calls = 0

    def select_contracts(self, *_args, **_kwargs):
        self.calls += 1
        return (_databento_selection(),)

    def latest_daily_bars(self, *_args, **_kwargs):
        selection = _databento_selection()
        return selection.definition.session_date, {
            selection.definition.raw_symbol: (selection.bar,)
        }


class _CappedPrimary:
    configured = True

    def select_contracts(self, *_args, **_kwargs):
        raise DatabentoOptionsError(
            "Databento OPRA HTTP 402",
            status_code=402,
            retryable=False,
        )

    def latest_daily_bars(self, *_args, **_kwargs):
        raise DatabentoOptionsError(
            "Databento OPRA HTTP 429",
            status_code=429,
            retryable=True,
        )


class _HealthyFallback:
    configured = True

    def __init__(self) -> None:
        self.select_calls = 0
        self.bar_inputs = ()

    def select_contracts(self, *_args, **kwargs):
        self.select_calls += 1
        assert kwargs["candidates_per_bucket"] == 1
        return (_massive_selection(),)

    def latest_daily_bars(self, instruments, *_args, **_kwargs):
        self.bar_inputs = tuple(instruments)
        selection = _massive_selection()
        return date(2026, 8, 10), {
            selection.definition.raw_symbol: (selection.bar,)
        }


class _BrokenFallback:
    configured = True

    def select_contracts(self, *_args, **_kwargs):
        raise MassiveOptionsError(
            "Massive OPRA HTTP 429",
            status_code=429,
            retryable=True,
        )

    def latest_daily_bars(self, *_args, **_kwargs):
        raise MassiveOptionsError(
            "Massive OPRA HTTP 503",
            status_code=503,
            retryable=True,
        )


def _select(provider: RedundantOptionsProvider):
    return provider.select_contracts(
        "SPY",
        underlying_price=640.0,
        as_of=AS_OF,
        minimum_days_to_expiry=30,
        maximum_days_to_expiry=365,
    )


def test_primary_provider_remains_authoritative_when_healthy() -> None:
    primary = _HealthyPrimary()
    fallback = _HealthyFallback()
    provider = RedundantOptionsProvider(primary=primary, fallback=fallback)

    selections = _select(provider)

    assert primary.calls == 1
    assert fallback.select_calls == 0
    assert selections[0].definition.provider_kind == "databento"
    assert selections[0].definition.provider_instrument_id == 12345
    assert selections[0].definition.source_identifier.startswith(
        "databento-opra-definition:"
    )


def test_access_cap_fails_over_to_massive_with_truthful_provenance() -> None:
    fallback = _HealthyFallback()
    provider = RedundantOptionsProvider(primary=_CappedPrimary(), fallback=fallback)

    selections = _select(provider)

    assert fallback.select_calls == 1
    assert selections[0].definition.provider_kind == "massive"
    assert selections[0].definition.provider_instrument_id is None
    assert selections[0].definition.provider_stype_in == "raw_symbol"
    assert selections[0].definition.source_identifier.startswith(
        "massive-opra-definition:"
    )
    assert selections[0].bar.source_identifier.startswith("massive-opra-bar:")


def test_daily_bar_failover_translates_databento_occ_symbol_for_massive() -> None:
    fallback = _HealthyFallback()
    provider = RedundantOptionsProvider(primary=_CappedPrimary(), fallback=fallback)
    databento_raw = "SPY   261010C00650000"

    session, bars = provider.latest_daily_bars(
        ((12345, databento_raw),),
        as_of=AS_OF,
        history_days=45,
    )

    assert session == date(2026, 8, 10)
    assert fallback.bar_inputs == ((None, "O:SPY261010C00650000"),)
    assert databento_raw in bars
    assert bars[databento_raw][0].provider_kind == "massive"
    assert bars[databento_raw][0].source_identifier.startswith("massive-opra-bar:")


def test_both_providers_unavailable_remains_fail_closed() -> None:
    provider = RedundantOptionsProvider(
        primary=_CappedPrimary(),
        fallback=_BrokenFallback(),
    )

    with pytest.raises(RedundantOptionsError) as captured:
        _select(provider)

    message = str(captured.value)
    assert "primary=access_or_credit_cap" in message
    assert "fallback=rate_limit" in message
