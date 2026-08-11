from __future__ import annotations

from datetime import datetime, timezone

from providers.single_pass_massive_options import SinglePassMassiveOptionsProvider


AS_OF = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)


class _Response:
    status_code = 200

    def __init__(self, payload) -> None:
        self._payload = payload

    def json(self):
        return self._payload


class _MassiveFixture:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, url, *, params, timeout):
        del timeout
        self.calls.append((url, dict(params)))
        if url.endswith("/v3/reference/options/contracts"):
            return _Response(
                {
                    "results": [
                        {
                            "ticker": "O:ZZQ261010C00100000",
                            "underlying_ticker": "ZZQ",
                            "contract_type": "call",
                            "expiration_date": "2026-10-10",
                            "strike_price": 100.0,
                            "shares_per_contract": 100,
                        },
                        {
                            "ticker": "O:ZZQ261010P00100000",
                            "underlying_ticker": "ZZQ",
                            "contract_type": "put",
                            "expiration_date": "2026-10-10",
                            "strike_price": 100.0,
                            "shares_per_contract": 100,
                        },
                    ]
                }
            )
        return _Response(
            {
                "results": [
                    {
                        "t": 1786392000000,
                        "c": 4.25,
                        "v": 125.0,
                    }
                ]
            }
        )


def test_contract_selection_hydrates_full_reusable_history_without_extra_calls() -> None:
    http = _MassiveFixture()
    provider = SinglePassMassiveOptionsProvider(
        api_key="test-key",
        http_get=http,
        minimum_request_interval_seconds=0.0,
    )

    selections = provider.select_contracts(
        "ZZQ",
        underlying_price=100.0,
        as_of=AS_OF,
        minimum_days_to_expiry=30,
        maximum_days_to_expiry=90,
        maximum_expirations=1,
        candidates_per_bucket=1,
    )

    assert len(selections) == 2
    aggregate_calls = [call for call in http.calls if "/v2/aggs/ticker/" in call[0]]
    assert len(aggregate_calls) == 2
    assert all("/2025-08-11/2026-08-11" in url for url, _params in aggregate_calls)

    calls_after_selection = len(http.calls)
    _session, bars = provider.latest_daily_bars(
        tuple((None, item.definition.raw_symbol) for item in selections),
        as_of=AS_OF,
        history_days=365,
    )

    assert len(bars) == 2
    assert len(http.calls) == calls_after_selection


def test_ordinary_massive_history_request_keeps_its_requested_window() -> None:
    http = _MassiveFixture()
    provider = SinglePassMassiveOptionsProvider(
        api_key="test-key",
        http_get=http,
        minimum_request_interval_seconds=0.0,
    )

    bars = provider.daily_bars(
        ("O:ZZQ261010C00105000",),
        as_of=AS_OF,
        history_days=30,
    )

    assert bars
    aggregate_calls = [call for call in http.calls if "/v2/aggs/ticker/" in call[0]]
    assert len(aggregate_calls) == 1
    assert "/2026-07-12/2026-08-11" in aggregate_calls[0][0]
