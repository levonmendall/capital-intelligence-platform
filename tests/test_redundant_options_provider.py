from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from providers.alpaca_indicative_options import (
    AlpacaIndicativeOptionBar,
    AlpacaIndicativeOptionDefinition,
    AlpacaIndicativeOptionSelection,
    AlpacaIndicativeOptionsError,
)
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
from providers.redundancy_audit import begin_redundancy_cycle
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


def _alpaca_selection(days: int = 60) -> AlpacaIndicativeOptionSelection:
    expiration = AS_OF + timedelta(days=days)
    symbol = f"SPY{expiration.strftime('%y%m%d')}C00650000"
    definition = AlpacaIndicativeOptionDefinition(
        symbol=symbol,
        raw_symbol=symbol,
        underlying="SPY",
        option_right="call",
        expiration_at=expiration,
        strike=650.0,
        contract_multiplier=100.0,
        session_date=date(2026, 8, 11),
        source_identifier=f"alpaca-option-contract:{symbol}",
    )
    return AlpacaIndicativeOptionSelection(
        definition=definition,
        bar=AlpacaIndicativeOptionBar(
            raw_symbol=symbol,
            observed_at=datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc),
            close=12.6,
            volume=115.0,
            source_identifier=f"alpaca-indicative-option-bar:{symbol}",
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


class _HealthySecondary:
    configured = True

    def __init__(self) -> None:
        self.select_calls = 0
        self.maximum_expirations = None
        self.bar_inputs = ()

    def select_contracts(self, *_args, **kwargs):
        self.select_calls += 1
        self.maximum_expirations = kwargs["maximum_expirations"]
        return tuple(_alpaca_selection(days) for days in (45, 75, 105))

    def latest_daily_bars(self, instruments, *_args, **_kwargs):
        self.bar_inputs = tuple(instruments)
        selection = _alpaca_selection()
        return date(2026, 8, 10), {
            selection.definition.raw_symbol: (selection.bar,)
        }


class _NoSecondary:
    configured = False


class _BrokenSecondary:
    configured = True

    def select_contracts(self, *_args, **_kwargs):
        raise AlpacaIndicativeOptionsError(
            "Alpaca indicative HTTP 429",
            status_code=429,
            retryable=True,
        )

    def latest_daily_bars(self, *_args, **_kwargs):
        raise AlpacaIndicativeOptionsError(
            "Alpaca indicative HTTP 503",
            status_code=503,
            retryable=True,
        )


class _HealthyFallback:
    configured = True

    def __init__(self) -> None:
        self.select_calls = 0
        self.bar_inputs = ()

    def select_contracts(self, *_args, **_kwargs):
        self.select_calls += 1
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
    secondary = _HealthySecondary()
    fallback = _HealthyFallback()
    provider = RedundantOptionsProvider(
        primary=primary,
        secondary=secondary,
        fallback=fallback,
    )

    selections = _select(provider)

    assert primary.calls == 1
    assert secondary.select_calls == 0
    assert fallback.select_calls == 0
    assert selections[0].definition.provider_kind == "databento"
    assert selections[0].definition.provider_instrument_id == 12345


def test_access_cap_fails_over_to_expiration_complete_alpaca_secondary() -> None:
    secondary = _HealthySecondary()
    fallback = _HealthyFallback()
    provider = RedundantOptionsProvider(
        primary=_CappedPrimary(),
        secondary=secondary,
        fallback=fallback,
    )

    selections = _select(provider)

    assert secondary.select_calls == 1
    assert secondary.maximum_expirations == 1_000
    assert fallback.select_calls == 0
    assert len({item.definition.expiration_at.date() for item in selections}) == 3
    assert all(item.definition.provider_kind == "alpaca_indicative" for item in selections)
    assert all(item.definition.provider_instrument_id is None for item in selections)
    assert all(item.definition.provider_stype_in == "raw_symbol" for item in selections)


def test_daily_bar_failover_can_still_use_massive_as_history_tertiary() -> None:
    fallback = _HealthyFallback()
    provider = RedundantOptionsProvider(
        primary=_CappedPrimary(),
        secondary=_NoSecondary(),
        fallback=fallback,
    )
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


def test_incomplete_selection_providers_remain_fail_closed_instead_of_using_massive() -> None:
    fallback = _HealthyFallback()
    provider = RedundantOptionsProvider(
        primary=_CappedPrimary(),
        secondary=_BrokenSecondary(),
        fallback=fallback,
    )

    with pytest.raises(RedundantOptionsError) as captured:
        _select(provider)

    message = str(captured.value)
    assert "primary=access_or_credit_cap" in message
    assert "secondary=rate_limit" in message
    assert "fallback=provider_evidence_unavailable" in message
    assert fallback.select_calls == 0


def test_option_failover_publishes_actual_attempt_sequence() -> None:
    ledger = begin_redundancy_cycle("option-failover", AS_OF)
    secondary = _HealthySecondary()
    fallback = _HealthyFallback()
    provider = RedundantOptionsProvider(
        primary=_CappedPrimary(),
        secondary=secondary,
        fallback=fallback,
    )

    selections = _select(provider)

    assert selections[0].definition.provider_kind == "alpaca_indicative"
    records = {
        (item["provider"], item["capability"]): item
        for item in ledger.to_dict()["records"]
    }
    primary = records[("databento", "option_contract_selection")]
    secondary_record = records[("alpaca_indicative", "option_contract_selection")]
    fallback_record = records[("massive", "option_contract_selection")]
    assert primary["configured"] is True
    assert primary["attempted"] is True
    assert primary["used"] is False
    assert primary["failure_class"] == "access_or_credit_cap"
    assert secondary_record["configured"] is True
    assert secondary_record["attempted"] is True
    assert secondary_record["authenticated"] is True
    assert secondary_record["used"] is True
    assert secondary_record["failed_over"] is True
    assert fallback_record["configured"] is True
    assert fallback_record["attempted"] is False
    assert fallback_record["used"] is False


def test_healthy_option_primary_keeps_secondary_and_fallback_visible_but_unattempted() -> None:
    ledger = begin_redundancy_cycle("option-primary", AS_OF)
    provider = RedundantOptionsProvider(
        primary=_HealthyPrimary(),
        secondary=_HealthySecondary(),
        fallback=_HealthyFallback(),
    )

    _select(provider)

    records = {
        (item["provider"], item["capability"]): item
        for item in ledger.to_dict()["records"]
    }
    primary = records[("databento", "option_contract_selection")]
    secondary = records[("alpaca_indicative", "option_contract_selection")]
    fallback = records[("massive", "option_contract_selection")]
    assert primary["used"] is True
    assert primary["authenticated"] is True
    assert secondary["configured"] is True
    assert secondary["attempted"] is False
    assert fallback["configured"] is True
    assert fallback["attempted"] is False
