from __future__ import annotations

from datetime import datetime, timezone

from providers.supplemental_quotes import SupplementalQuoteProvider


NOW = datetime(2026, 7, 28, 22, 0, tzinfo=timezone.utc)


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_crosscheck_agrees_without_execution_authority() -> None:
    payloads = [
        {
            "Global Quote": {
                "01. symbol": "AAPL",
                "05. price": "210.00",
                "07. latest trading day": "2026-07-28",
            }
        },
        {"symbol": "AAPL", "close": "210.10", "timestamp": int(NOW.timestamp())},
        {
            "quotes": {
                "quote": {
                    "symbol": "AAPL",
                    "last": 210.05,
                    "trade_date": int(NOW.timestamp() * 1000),
                }
            }
        },
    ]
    calls: list[dict[str, object]] = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return FakeResponse(payloads.pop(0))

    provider = SupplementalQuoteProvider(
        alpha_vantage_key="alpha-secret",
        twelve_data_key="twelve-secret",
        tradier_key="tradier-secret",
        clock=lambda: NOW,
        http_get=fake_get,
    )
    result = provider.cross_check("AAPL", maximum_divergence_bps=10).to_dict()

    assert result["state"] == "agree"
    assert result["divergence_bps"] < 10
    assert [item["provider"] for item in result["quotes"]] == [
        "ALPHA_VANTAGE",
        "TWELVE_DATA",
        "TRADIER",
    ]
    tradier_call = calls[-1]
    assert tradier_call["url"] == "https://api.tradier.com/v1/markets/quotes"
    assert tradier_call["headers"]["Authorization"] == "Bearer tradier-secret"
    assert result["canonical_execution_authority"] is False
    serialized = str(result)
    assert "alpha-secret" not in serialized
    assert "twelve-secret" not in serialized
    assert "tradier-secret" not in serialized
