from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from providers.alpaca_indicative_options import (
    AlpacaIndicativeOptionBar,
    AlpacaIndicativeOptionDefinition,
    AlpacaIndicativeOptionSelection,
    AlpacaIndicativeOptionsError,
)
from providers.massive_options import (
    MassiveOptionBar,
    MassiveOptionDefinition,
    MassiveOptionSelection,
)
from providers.redundancy_audit import begin_redundancy_cycle
from providers.redundant_options import RedundantOptionsError, RedundantOptionsProvider
from providers.tradier_market_data import (
    TradierMarketDataError,
    TradierOptionBar,
    TradierOptionDefinition,
    TradierOptionSelection,
)


AS_OF = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)
EXPIRATION = AS_OF + timedelta(days=60)
RAW = "SPY261010C00650000"


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
        symbol=RAW,
        raw_symbol=f"O:{RAW}",
        underlying="SPY",
        option_right="call",
        expiration_at=EXPIRATION,
        strike=650.0,
        contract_multiplier=100.0,
        session_date=date(2026, 8, 11),
        source_identifier=f"massive-opra-definition:2026-08-11:O:{RAW}",
    )
    return MassiveOptionSelection(
        definition=definition,
        bar=MassiveOptionBar(
            raw_symbol=definition.raw_symbol,
            observed_at=datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc),
            close=12.7,
            volume=120.0,
            source_identifier=f"massive-opra-bar:O:{RAW}:2026-08-10T20:00:00+00:00",
        ),
    )


def _tradier_selection(days: int, right: str) -> TradierOptionSelection:
    expiration = AS_OF + timedelta(days=days)
    right_code = "C" if right == "call" else "P"
    symbol = f"SPY{expiration.strftime('%y%m%d')}{right_code}00650000"
    definition = TradierOptionDefinition(
        symbol=symbol,
        raw_symbol=symbol,
        underlying="SPY",
        option_right=right,
        expiration_at=expiration,
        strike=650.0,
        contract_multiplier=100.0,
        session_date=date(2026, 8, 10),
        source_identifier=f"tradier:active-option-chain:{symbol}",
    )
    return TradierOptionSelection(
        definition=definition,
        bar=TradierOptionBar(
            raw_symbol=symbol,
            observed_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            close=12.8,
            volume=130.0,
            source_identifier=f"tradier:option-history:{symbol}:2026-08-10",
        ),
    )


class _HealthyAlpaca:
    configured = True

    def __init__(self) -> None:
        self.select_calls = 0
        self.maximum_expirations = None

    def select_contracts(self, *_args, **kwargs):
        self.select_calls += 1
        self.maximum_expirations = kwargs["maximum_expirations"]
        return tuple(_alpaca_selection(days) for days in (45, 75, 105))

    def latest_daily_bars(self, instruments, *_args, **_kwargs):
        requested = tuple(symbol for _instrument_id, symbol in instruments)
        selection = _alpaca_selection()
        return date(2026, 8, 10), {
            symbol: (selection.bar,) for symbol in requested
        }


class _BrokenAlpaca:
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


class _NoAlpaca:
    configured = False


class _HealthyTradier:
    configured = True

    def __init__(self) -> None:
        self.symbols: list[str] = []
        self.select_calls = 0
        self.maximum_expirations = None

    def select_contracts(self, *_args, **kwargs):
        self.select_calls += 1
        self.maximum_expirations = kwargs["maximum_expirations"]
        return tuple(
            _tradier_selection(days, right)
            for days in (45, 75)
            for right in ("call", "put")
        )

    def daily_history(self, symbol, *, as_of, history_days):
        assert as_of == AS_OF
        assert history_days == 45
        self.symbols.append(symbol)
        return (
            {
                "t": datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc),
                "c": 12.8,
                "v": 130.0,
            },
        )


class _BrokenTradier:
    configured = True

    def select_contracts(self, *_args, **_kwargs):
        raise TradierMarketDataError("Tradier HTTP 503", status_code=503, retryable=True)

    def daily_history(self, *_args, **_kwargs):
        raise TradierMarketDataError("Tradier HTTP 503", status_code=503, retryable=True)


class _NoTradier:
    configured = False


class _HealthyMassive:
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


class _NoMassive:
    configured = False


def _select(provider: RedundantOptionsProvider, *, maximum_expirations: int = 1_000):
    return provider.select_contracts(
        "SPY",
        underlying_price=640.0,
        as_of=AS_OF,
        minimum_days_to_expiry=30,
        maximum_days_to_expiry=365,
        maximum_expirations=maximum_expirations,
    )


def test_alpaca_is_opportunity_complete_primary() -> None:
    alpaca = _HealthyAlpaca()
    massive = _HealthyMassive()
    provider = RedundantOptionsProvider(
        primary=alpaca,
        secondary=_HealthyTradier(),
        fallback=massive,
    )

    selections = _select(provider)

    assert alpaca.select_calls == 1
    assert alpaca.maximum_expirations == 1_000
    assert massive.select_calls == 0
    assert len({item.definition.expiration_at.date() for item in selections}) == 3
    assert all(item.definition.provider_kind == "alpaca_indicative" for item in selections)


def test_tradier_supplies_complete_multi_expiration_selection_after_alpaca_failure() -> None:
    massive = _HealthyMassive()
    tradier = _HealthyTradier()
    provider = RedundantOptionsProvider(
        primary=_BrokenAlpaca(),
        secondary=tradier,
        fallback=massive,
    )

    selections = _select(provider)

    assert tradier.select_calls == 1
    assert tradier.maximum_expirations == 1_000
    assert len({item.definition.expiration_at.date() for item in selections}) == 2
    assert {item.definition.option_right for item in selections} == {"call", "put"}
    assert all(item.definition.provider_kind == "tradier" for item in selections)
    assert massive.select_calls == 0


def test_multi_expiration_discovery_still_fails_when_tradier_is_incomplete() -> None:
    massive = _HealthyMassive()
    provider = RedundantOptionsProvider(
        primary=_BrokenAlpaca(),
        secondary=_BrokenTradier(),
        fallback=massive,
    )

    with pytest.raises(RedundantOptionsError) as captured:
        _select(provider)

    assert "primary=rate_limit" in str(captured.value)
    assert "secondary=provider_5xx" in str(captured.value)
    assert "opportunity-complete" in str(captured.value)
    assert massive.select_calls == 0


def test_daily_history_uses_tradier_before_massive() -> None:
    tradier = _HealthyTradier()
    massive = _HealthyMassive()
    provider = RedundantOptionsProvider(
        primary=_BrokenAlpaca(),
        secondary=tradier,
        fallback=massive,
    )

    session, bars = provider.latest_daily_bars(
        ((None, RAW),),
        as_of=AS_OF,
        history_days=45,
    )

    assert session == date(2026, 8, 10)
    assert tradier.symbols == [RAW]
    assert bars[RAW][0].provider_kind == "tradier"
    assert massive.bar_inputs == ()


def test_daily_history_falls_through_to_massive_when_tradier_fails() -> None:
    massive = _HealthyMassive()
    provider = RedundantOptionsProvider(
        primary=_BrokenAlpaca(),
        secondary=_BrokenTradier(),
        fallback=massive,
    )

    session, bars = provider.latest_daily_bars(
        ((None, RAW),),
        as_of=AS_OF,
        history_days=45,
    )

    assert session == date(2026, 8, 10)
    assert massive.bar_inputs == ((None, f"O:{RAW}"),)
    assert bars[RAW][0].provider_kind == "massive"


def test_massive_remains_available_for_explicit_single_expiration_probe() -> None:
    massive = _HealthyMassive()
    provider = RedundantOptionsProvider(
        primary=_NoAlpaca(),
        secondary=_NoTradier(),
        fallback=massive,
    )

    selections = _select(provider, maximum_expirations=1)

    assert massive.select_calls == 1
    assert selections[0].definition.provider_kind == "massive"


def test_audit_records_alpaca_primary_and_unattempted_massive() -> None:
    ledger = begin_redundancy_cycle("option-primary", AS_OF)
    provider = RedundantOptionsProvider(
        primary=_HealthyAlpaca(),
        secondary=_HealthyTradier(),
        fallback=_HealthyMassive(),
    )

    _select(provider)

    records = {
        (item["provider"], item["capability"]): item
        for item in ledger.to_dict()["records"]
    }
    primary = records[("alpaca_indicative", "option_contract_selection")]
    tradier = records[("tradier", "option_contract_selection")]
    massive = records[("massive", "option_contract_selection")]
    assert primary["attempted"] is True
    assert primary["used"] is True
    assert tradier["attempted"] is False
    assert massive["attempted"] is False
