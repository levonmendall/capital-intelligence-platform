from __future__ import annotations

from datetime import datetime, timedelta, timezone

from providers.alpaca_paper import AlpacaPaperClient, AlpacaPaperSettings


class _Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_historical_bars_paginates_authenticated_iex_request() -> None:
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        token = kwargs["params"].get("page_token")
        if token is None:
            return _Response(
                {
                    "bars": {
                        "VTI": [{"t": "2026-07-27T20:00:00Z", "c": 100.0, "v": 5.0}],
                        "GLD": [{"t": "2026-07-27T20:00:00Z", "c": 200.0, "v": 3.0}],
                    },
                    "next_page_token": "next",
                }
            )
        return _Response(
            {
                "bars": {
                    "VTI": [{"t": "2026-07-28T20:00:00Z", "c": 101.0, "v": 6.0}],
                    "GLD": [{"t": "2026-07-28T20:00:00Z", "c": 201.0, "v": 4.0}],
                },
                "next_page_token": None,
            }
        )

    client = AlpacaPaperClient(
        AlpacaPaperSettings(api_key_id="key", secret_key="secret"),
        http_get=get,
    )
    end = datetime(2026, 7, 29, tzinfo=timezone.utc)
    result = client.historical_bars(
        ("VTI", "GLD"),
        start=end - timedelta(days=30),
        end=end,
    )

    assert len(calls) == 2
    assert calls[0][0].endswith("/v2/stocks/bars")
    assert calls[0][1]["params"]["feed"] == "iex"
    assert calls[1][1]["params"]["page_token"] == "next"
    assert len(result["VTI"]) == 2
    assert len(result["GLD"]) == 2
