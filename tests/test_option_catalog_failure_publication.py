from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock
from time import sleep

import pytest

from operations.comprehensive_market_discovery_legacy import (
    ComprehensiveMarketDiscoveryConfig,
    ComprehensiveMarketDiscoveryError,
    ComprehensiveMarketDiscoveryPolicy,
    _option_catalog,
)
from providers.databento_options import (
    DatabentoOptionBar,
    DatabentoOptionDefinition,
    DatabentoOptionSelection,
    DatabentoOptionsError,
)


AS_OF = datetime(2026, 8, 7, 16, 0, tzinfo=timezone.utc)


class _YahooResponse:
    status_code = 200

    @staticmethod
    def json() -> dict[str, object]:
        return {
            "chart": {
                "result": [
                    {
                        "timestamp": [int(AS_OF.timestamp()) - 86_400],
                        "indicators": {
                            "quote": [{"close": [625.0], "volume": [1_000_000]}]
                        },
                    }
                ]
            }
        }


def _config(*underlyings: str) -> ComprehensiveMarketDiscoveryConfig:
    return ComprehensiveMarketDiscoveryConfig(
        eodhd_exchange_codes=(),
        futures_roots=(),
        option_underlyings=tuple(underlyings),
        yahoo_exchange_suffixes=(),
    )


def _yahoo_get(*_args, **_kwargs) -> _YahooResponse:
    return _YahooResponse()


class _UnavailableAlpacaClient:
    @staticmethod
    def historical_bars(*_args, **_kwargs):
        raise ValueError("Alpaca unavailable in this failure-path test")


def test_empty_option_catalog_preserves_credential_safe_provider_cause() -> None:
    class Provider:
        configured = True

        @staticmethod
        def select_contracts(*_args, **_kwargs):
            raise DatabentoOptionsError("Databento OPRA HTTP 502: upstream unavailable")

    with pytest.raises(ComprehensiveMarketDiscoveryError) as captured:
        _option_catalog(
            as_of=AS_OF,
            config=_config("SPY", "QQQ"),
            policy=ComprehensiveMarketDiscoveryPolicy(),
            http_get=_yahoo_get,
            databento_options_provider=Provider(),
            alpaca_client=_UnavailableAlpacaClient(),
        )

    detail = str(captured.value)
    assert "provider_errors=2" in detail
    assert "SPY=Databento OPRA HTTP 502: upstream unavailable" in detail
    assert "QQQ=Databento OPRA HTTP 502: upstream unavailable" in detail
    assert "no_eligible_priced_contracts=0" in detail


def test_empty_option_catalog_distinguishes_quotes_from_contract_selection() -> None:
    class Provider:
        configured = True

        @staticmethod
        def select_contracts(*_args, **_kwargs):
            return ()

    yahoo_calls = 0

    def yahoo_get(*_args, **_kwargs):
        nonlocal yahoo_calls
        yahoo_calls += 1
        if yahoo_calls == 1:
            return _YahooResponse()

        class EmptyResponse:
            status_code = 503

        return EmptyResponse()

    with pytest.raises(ComprehensiveMarketDiscoveryError) as captured:
        _option_catalog(
            as_of=AS_OF,
            config=_config("SPY", "QQQ"),
            policy=ComprehensiveMarketDiscoveryPolicy(),
            http_get=yahoo_get,
            databento_options_provider=Provider(),
            alpaca_client=_UnavailableAlpacaClient(),
        )

    detail = str(captured.value)
    assert "underlying_quote_unavailable=1" in detail
    assert "provider_errors=0" in detail
    assert "no_eligible_priced_contracts=1" in detail
    assert "provider_failure_sample=" not in detail


def test_option_quotes_are_serial_and_databento_is_bounded_parallel() -> None:
    underlyings = ("SPY", "QQQ", "IWM", "DIA", "TLT")
    rendezvous = Barrier(4)
    lock = Lock()
    completion_order: list[str] = []
    yahoo_active = 0
    yahoo_peak = 0
    databento_active = 0
    databento_peak = 0

    def yahoo_get(*_args, **_kwargs):
        nonlocal yahoo_active, yahoo_peak
        yahoo_active += 1
        yahoo_peak = max(yahoo_peak, yahoo_active)
        try:
            sleep(0.01)
            return _YahooResponse()
        finally:
            yahoo_active -= 1

    class Provider:
        configured = True

        @staticmethod
        def select_contracts(underlying, **_kwargs):
            nonlocal databento_active, databento_peak
            with lock:
                databento_active += 1
                databento_peak = max(databento_peak, databento_active)
            try:
                if underlying != underlyings[-1]:
                    rendezvous.wait(timeout=2)
                if underlying == "SPY":
                    sleep(0.05)
                completion_order.append(underlying)
                expiration = AS_OF + timedelta(days=60)
                definition = DatabentoOptionDefinition(
                    symbol=f"{underlying}261006C00625000",
                    raw_symbol=f"{underlying}   261006C00625000",
                    instrument_id=underlyings.index(underlying) + 1,
                    underlying=underlying,
                    option_right="call",
                    expiration_at=expiration,
                    strike=625.0,
                    contract_multiplier=100.0,
                    session_date=(AS_OF - timedelta(days=1)).date(),
                )
                bar = DatabentoOptionBar(
                    raw_symbol=definition.raw_symbol,
                    observed_at=AS_OF - timedelta(days=1),
                    close=12.5,
                    volume=100.0,
                )
                return (DatabentoOptionSelection(definition=definition, bar=bar),)
            finally:
                with lock:
                    databento_active -= 1

    result = _option_catalog(
        as_of=AS_OF,
        config=_config(*underlyings),
        policy=ComprehensiveMarketDiscoveryPolicy(),
        http_get=yahoo_get,
        databento_options_provider=Provider(),
        alpaca_client=_UnavailableAlpacaClient(),
    )

    assert yahoo_peak == 1
    assert databento_peak == 4
    assert completion_order.index("QQQ") < completion_order.index("SPY")
    assert [item.underlying_symbol for item in result] == list(underlyings)


def test_option_catalog_uses_authenticated_alpaca_when_yahoo_is_unavailable() -> None:
    underlyings = ("SPY", "QQQ")
    received_prices: dict[str, float] = {}

    class AlpacaClient:
        @staticmethod
        def historical_bars(symbols, **_kwargs):
            return {
                symbol: (
                    {
                        "t": (AS_OF - timedelta(days=1)).isoformat(),
                        "c": 500.0 + index,
                        "v": 1_000_000.0,
                    },
                )
                for index, symbol in enumerate(symbols)
            }

    class Provider:
        configured = True

        @staticmethod
        def select_contracts(underlying, *, underlying_price, **_kwargs):
            received_prices[underlying] = underlying_price
            expiration = AS_OF + timedelta(days=60)
            definition = DatabentoOptionDefinition(
                symbol=f"{underlying}261006C00500000",
                raw_symbol=f"{underlying}   261006C00500000",
                instrument_id=underlyings.index(underlying) + 1,
                underlying=underlying,
                option_right="call",
                expiration_at=expiration,
                strike=500.0,
                contract_multiplier=100.0,
                session_date=(AS_OF - timedelta(days=1)).date(),
            )
            bar = DatabentoOptionBar(
                raw_symbol=definition.raw_symbol,
                observed_at=AS_OF - timedelta(days=1),
                close=10.0,
                volume=100.0,
            )
            return (DatabentoOptionSelection(definition=definition, bar=bar),)

    def yahoo_must_not_run(*_args, **_kwargs):
        raise AssertionError("Yahoo should be fallback-only when Alpaca has valid bars")

    result = _option_catalog(
        as_of=AS_OF,
        config=_config(*underlyings),
        policy=ComprehensiveMarketDiscoveryPolicy(),
        http_get=yahoo_must_not_run,
        databento_options_provider=Provider(),
        alpaca_client=AlpacaClient(),
    )

    assert received_prices == {"SPY": 500.0, "QQQ": 501.0}
    assert [item.underlying_symbol for item in result] == list(underlyings)
    assert all("underlying:alpaca-iex-daily:" in item.source_identifier for item in result)
