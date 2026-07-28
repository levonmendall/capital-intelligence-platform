from __future__ import annotations

from typing import Any

from providers.alpaca_paper import AlpacaPaperSettings
from providers.alpaca_paper_broker import AlpacaPaperBrokerClient


class _Response:
    def __init__(self, payload: object, *, status_code: int) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def json(self) -> object:
        return self._payload


def test_crypto_position_retries_legacy_symbol_after_canonical_404() -> None:
    requested_urls: list[str] = []

    def request(method: str, url: str, **_: Any) -> _Response:
        requested_urls.append(url)
        if url.endswith("/v2/positions/BTC%2FUSD"):
            return _Response({"message": "position does not exist"}, status_code=404)
        if url.endswith("/v2/positions/BTCUSD"):
            return _Response(
                {
                    "symbol": "BTC/USD",
                    "qty": "0.000452917",
                    "qty_available": None,
                },
                status_code=200,
            )
        raise AssertionError(f"unexpected URL {url}")

    client = AlpacaPaperBrokerClient(
        AlpacaPaperSettings(api_key_id="paper-key", secret_key="paper-secret"),
        http_request=request,
    )

    position = client.position("BTC/USD")

    assert position is not None
    assert position["qty"] == "0.000452917"
    assert requested_urls == [
        "https://paper-api.alpaca.markets/v2/positions/BTC%2FUSD",
        "https://paper-api.alpaca.markets/v2/positions/BTCUSD",
    ]


def test_equity_position_uses_only_canonical_symbol() -> None:
    requested_urls: list[str] = []

    def request(method: str, url: str, **_: Any) -> _Response:
        requested_urls.append(url)
        return _Response({"symbol": "SPY", "qty": "1"}, status_code=200)

    client = AlpacaPaperBrokerClient(
        AlpacaPaperSettings(api_key_id="paper-key", secret_key="paper-secret"),
        http_request=request,
    )

    position = client.position("SPY")

    assert position is not None
    assert position["symbol"] == "SPY"
    assert requested_urls == ["https://paper-api.alpaca.markets/v2/positions/SPY"]
