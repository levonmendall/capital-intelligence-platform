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
    ]

    provider = SupplementalQuoteProvider(
        alpha_vantage_key="alpha-secret",
        twelve_data_key="twelve-secret",
        clock=lambda: NOW,
        http_get=lambda *_args, **_kwargs: FakeResponse(payloads.pop(0)),
    )
    result = provider.cross_check("AAPL", maximum_divergence_bps=10).to_dict()
    assert result["state"] == "agree"
    assert result["divergence_bps"] < 10
    assert result["canonical_execution_authority"] is False
    assert "alpha-secret" not in str(result)
    assert "twelve-secret" not in str(result)
