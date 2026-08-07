from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Barrier
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
        )

    detail = str(captured.value)
    assert "underlying_quote_unavailable=1" in detail
    assert "provider_errors=0" in detail
    assert "no_eligible_priced_contracts=1" in detail
    assert "provider_failure_sample=" not in detail


def test_option_underlyings_run_concurrently_but_restore_configured_order() -> None:
    rendezvous = Barrier(2)
    completion_order: list[str] = []

    class Provider:
        configured = True

        @staticmethod
        def select_contracts(underlying, **_kwargs):
            rendezvous.wait(timeout=2)
            if underlying == "SPY":
                sleep(0.05)
            completion_order.append(underlying)
            expiration = AS_OF + timedelta(days=60)
            definition = DatabentoOptionDefinition(
                symbol=f"{underlying}261006C00625000",
                raw_symbol=f"{underlying}   261006C00625000",
                instrument_id=1 if underlying == "SPY" else 2,
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

    result = _option_catalog(
        as_of=AS_OF,
        config=_config("SPY", "QQQ"),
        policy=ComprehensiveMarketDiscoveryPolicy(),
        http_get=_yahoo_get,
        databento_options_provider=Provider(),
    )

    assert completion_order == ["QQQ", "SPY"]
    assert [item.underlying_symbol for item in result] == ["SPY", "QQQ"]
