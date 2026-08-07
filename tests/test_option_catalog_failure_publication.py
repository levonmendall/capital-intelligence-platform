from __future__ import annotations

from datetime import datetime, timezone

import pytest

from operations.comprehensive_market_discovery_legacy import (
    ComprehensiveMarketDiscoveryConfig,
    ComprehensiveMarketDiscoveryError,
    ComprehensiveMarketDiscoveryPolicy,
    _option_catalog,
)
from providers.databento_options import DatabentoOptionsError


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
