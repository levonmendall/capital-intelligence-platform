from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

from providers.alpaca_indicative_options import AlpacaIndicativeOptionsProvider
from providers.alpaca_paper import AlpacaPaperSettings
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
        if url.endswith("/v1beta1/options/snapshots/ZZQ"):
            snapshots = {}
            for days in EXPIRATION_DAYS:
                compact_date = (AS_OF + timedelta(days=days)).strftime("%y%m%d")
                for code in ("C", "P"):
                    symbol = f"ZZQ{compact_date}{code}00100000"
                    snapshots[symbol] = {"latestTrade": None, "latestQuote": None}
            return _Response({"snapshots": snapshots, "next_page_token": None})
        if url.endswith("/v1beta1/options/bars"):
            symbols = tuple(
                item.strip()
                for item in str(params.get("symbols", "")).split(",")
                if item.strip()
            )
            bars = {
                symbol: [{"t": "2026-08-10T20:00:00Z", "c": 4.5, "v": 250}]
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


class _NoTradier:
    configured = False


class _UnexpectedMassive:
    configured = True

    def __init__(self) -> None:
        self.called = False

    def select_contracts(self, *_args, **_kwargs):
        self.called = True
        raise AssertionError("Massive must not run when Alpaca supplies complete coverage")


def test_alpaca_primary_preserves_every_eligible_expiration() -> None:
    http = _AlpacaFixture()
    alpaca = AlpacaIndicativeOptionsProvider(settings=_settings(), http_get=http)
    fallback = _UnexpectedMassive()
    provider = RedundantOptionsProvider(
        primary=alpaca,
        secondary=_NoTradier(),
        fallback=fallback,
    )

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
    assert fallback.called is False

    chain_calls = [
        call for call in http.calls if call[0].endswith("/v1beta1/options/snapshots/ZZQ")
    ]
    bar_calls = [call for call in http.calls if call[0].endswith("/v1beta1/options/bars")]
    assert len(chain_calls) == 1
    assert chain_calls[0][0].startswith("https://data.alpaca.markets/")
    assert chain_calls[0][1]["feed"] == "indicative"
    assert chain_calls[0][1]["expiration_date_gte"] == "2026-09-10"
    assert chain_calls[0][1]["expiration_date_lte"] == "2027-08-12"
    assert not any("paper-api.alpaca.markets" in url for url, _params in http.calls)
    assert len(bar_calls) == 2
    assert len(str(bar_calls[0][1]["symbols"]).split(",")) == 6
    assert len(str(bar_calls[1][1]["symbols"]).split(",")) == 6
    for _url, params in bar_calls:
        end = datetime.fromisoformat(str(params["end"]))
        assert end == AS_OF - timedelta(minutes=16)
        assert end <= AS_OF - timedelta(minutes=15)


def test_router_default_cannot_hide_a_small_expiration_limit() -> None:
    parameter = inspect.signature(
        RedundantOptionsProvider.select_contracts
    ).parameters["maximum_expirations"]
    assert parameter.default == 1_000
