from __future__ import annotations

import inspect
from datetime import date, datetime, timedelta, timezone

from providers.alpaca_indicative_options import (
    AlpacaIndicativeOptionBar,
    AlpacaIndicativeOptionDefinition,
    AlpacaIndicativeOptionSelection,
    AlpacaIndicativeOptionsProvider,
)
from providers.alpaca_paper import AlpacaPaperSettings
from providers.databento_options import DatabentoOptionsError
from providers.redundant_options import RedundantOptionsProvider


AS_OF = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)
EXPIRATION_DAYS = (40, 70, 100)


class _Response:
    status_code = 200

    def __init__(self, payload) -> None:
        self._payload = payload

    def json(self):
        return self._payload


class _AlpacaFixture:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, url, *, headers, params, timeout):
        del headers, timeout
        self.calls.append((url, dict(params)))
        if url.endswith("/v2/options/contracts"):
            contracts = []
            for days in EXPIRATION_DAYS:
                expiration = (AS_OF + timedelta(days=days)).date().isoformat()
                compact_date = (AS_OF + timedelta(days=days)).strftime("%y%m%d")
                for right, code in (("call", "C"), ("put", "P")):
                    symbol = f"ZZQ{compact_date}{code}00100000"
                    contracts.append(
                        {
                            "id": f"id-{symbol}",
                            "symbol": symbol,
                            "underlying_symbol": "ZZQ",
                            "type": right,
                            "expiration_date": expiration,
                            "strike_price": "100",
                            "size": "100",
                            "tradable": True,
                        }
                    )
            return _Response(
                {
                    "option_contracts": contracts,
                    "next_page_token": None,
                }
            )
        if url.endswith("/v1beta1/options/bars"):
            symbols = tuple(
                item.strip()
                for item in str(params.get("symbols", "")).split(",")
                if item.strip()
            )
            bars = {
                symbol: [
                    {
                        "t": "2026-08-10T20:00:00Z",
                        "c": 4.5,
                        "v": 250,
                    }
                ]
                for symbol in symbols
            }
            return _Response({"bars": bars, "next_page_token": None})
        raise AssertionError(f"unexpected Alpaca URL: {url}")


def _settings() -> AlpacaPaperSettings:
    return AlpacaPaperSettings(
        api_key_id="test-key",
        secret_key="test-secret",
        paper_base_url="https://paper-api.alpaca.markets",
        data_base_url="https://data.alpaca.markets",
        data_feed="iex",
        timeout_seconds=5,
    )


def test_alpaca_secondary_preserves_every_eligible_expiration() -> None:
    http = _AlpacaFixture()
    provider = AlpacaIndicativeOptionsProvider(settings=_settings(), http_get=http)

    selections = provider.select_contracts(
        "ZZQ",
        underlying_price=100.0,
        as_of=AS_OF,
        minimum_days_to_expiry=30,
        maximum_days_to_expiry=365,
        maximum_expirations=1_000,
        candidates_per_bucket=8,
    )

    assert len(selections) == 6
    assert {item.definition.expiration_at.date() for item in selections} == {
        (AS_OF + timedelta(days=days)).date() for days in EXPIRATION_DAYS
    }
    for expiration in {item.definition.expiration_at for item in selections}:
        assert {
            item.definition.option_right
            for item in selections
            if item.definition.expiration_at == expiration
        } == {"call", "put"}

    contract_calls = [call for call in http.calls if call[0].endswith("/v2/options/contracts")]
    bar_calls = [call for call in http.calls if call[0].endswith("/v1beta1/options/bars")]
    assert len(contract_calls) == 1
    assert len(bar_calls) == 2
    assert len(str(bar_calls[0][1]["symbols"]).split(",")) == 6
    assert len(str(bar_calls[1][1]["symbols"]).split(",")) == 6


class _CappedDatabento:
    configured = True

    def select_contracts(self, *_args, **_kwargs):
        raise DatabentoOptionsError(
            "Databento OPRA HTTP 402",
            status_code=402,
            retryable=False,
        )


class _CompleteSecondary:
    configured = True

    def __init__(self) -> None:
        self.maximum_expirations: int | None = None

    def select_contracts(self, *_args, **kwargs):
        self.maximum_expirations = kwargs["maximum_expirations"]
        result = []
        for days in EXPIRATION_DAYS:
            expiration = AS_OF + timedelta(days=days)
            for right in ("call", "put"):
                code = "C" if right == "call" else "P"
                symbol = f"ZZQ{expiration.strftime('%y%m%d')}{code}00100000"
                definition = AlpacaIndicativeOptionDefinition(
                    symbol=symbol,
                    raw_symbol=symbol,
                    underlying="ZZQ",
                    option_right=right,
                    expiration_at=expiration,
                    strike=100.0,
                    contract_multiplier=100.0,
                    session_date=date(2026, 8, 11),
                    source_identifier=f"alpaca-option-contract:{symbol}",
                )
                bar = AlpacaIndicativeOptionBar(
                    raw_symbol=symbol,
                    observed_at=datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc),
                    close=4.5,
                    volume=250.0,
                    source_identifier=f"alpaca-indicative-option-bar:{symbol}",
                )
                result.append(
                    AlpacaIndicativeOptionSelection(definition=definition, bar=bar)
                )
        return tuple(result)


class _UnexpectedMassive:
    configured = True

    def __init__(self) -> None:
        self.called = False

    def select_contracts(self, *_args, **_kwargs):
        self.called = True
        raise AssertionError("Massive must not truncate an opportunity-complete secondary")


def test_router_uses_complete_secondary_without_touching_massive() -> None:
    secondary = _CompleteSecondary()
    fallback = _UnexpectedMassive()
    provider = RedundantOptionsProvider(
        primary=_CappedDatabento(),
        secondary=secondary,
        fallback=fallback,
    )

    selections = provider.select_contracts(
        "ZZQ",
        underlying_price=100.0,
        as_of=AS_OF,
        minimum_days_to_expiry=30,
        maximum_days_to_expiry=365,
    )

    assert len(selections) == 6
    assert secondary.maximum_expirations == 1_000
    assert fallback.called is False


def test_router_default_cannot_hide_a_small_expiration_limit() -> None:
    parameter = inspect.signature(
        RedundantOptionsProvider.select_contracts
    ).parameters["maximum_expirations"]
    assert parameter.default == 1_000
