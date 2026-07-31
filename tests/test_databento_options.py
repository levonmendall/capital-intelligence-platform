from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from providers.databento_options import (
    DatabentoOptionsError,
    DatabentoOptionsProvider,
)

AS_OF = datetime(2026, 7, 31, 18, 0, tzinfo=timezone.utc)


class _Response:
    def __init__(self, *, status_code: int = 200, records=(), detail: str | None = None):
        self.status_code = status_code
        values = list(records)
        if detail is not None:
            values.append({"detail": detail})
        self.text = "\n".join(json.dumps(item) for item in values)


class _Post:
    def __init__(self):
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        data = kwargs["data"]
        if data["schema"] == "definition":
            return _Response(
                records=(
                    {
                        "symbol": "SPY   260918C00620000",
                        "raw_symbol": "SPY   260918C00620000",
                        "asset": "SPY",
                        "underlying": "SPY",
                        "instrument_class": "C",
                        "expiration": "2026-09-18T00:00:00.000000000Z",
                        "strike_price": "620.000000000",
                        "contract_multiplier": "100",
                    },
                    {
                        "symbol": "SPY   260918P00620000",
                        "raw_symbol": "SPY   260918P00620000",
                        "asset": "SPY",
                        "underlying": "SPY",
                        "instrument_class": "P",
                        "expiration": "2026-09-18T00:00:00.000000000Z",
                        "strike_price": "620.000000000",
                        "contract_multiplier": "100",
                    },
                    {
                        "symbol": "SPY   261218C00625000",
                        "raw_symbol": "SPY   261218C00625000",
                        "asset": "SPY",
                        "underlying": "SPY",
                        "instrument_class": "C",
                        "expiration": "2026-12-18T00:00:00.000000000Z",
                        "strike_price": "625.000000000",
                        "contract_multiplier": "100",
                    },
                    {
                        "symbol": "SPY   261218P00625000",
                        "raw_symbol": "SPY   261218P00625000",
                        "asset": "SPY",
                        "underlying": "SPY",
                        "instrument_class": "P",
                        "expiration": "2026-12-18T00:00:00.000000000Z",
                        "strike_price": "625.000000000",
                        "contract_multiplier": "100",
                    },
                )
            )
        if data["schema"] == "ohlcv-1d":
            records = []
            for symbol in data["symbols"].split(","):
                records.append(
                    {
                        "symbol": "".join(symbol.split()),
                        "pretty_ts_event": "2026-07-30T13:30:00.000000000Z",
                        "pretty_close": "12.500000000",
                        "volume": "25",
                    }
                )
            return _Response(records=records)
        raise AssertionError(data)


def test_selects_priced_call_and_put_from_completed_session():
    post = _Post()
    provider = DatabentoOptionsProvider(api_key="secret", http_post=post)

    assert provider.configured is True
    selected = provider.select_contracts(
        "SPY",
        underlying_price=620.0,
        as_of=AS_OF,
        minimum_days_to_expiry=30,
        maximum_days_to_expiry=365,
    )

    assert {item.definition.option_right for item in selected} == {"call", "put"}
    assert len(selected) == 4
    assert all(item.bar.close == 12.5 for item in selected)
    assert all(item.definition.session_date.isoformat() == "2026-07-30" for item in selected)
    assert selected[0].definition.symbol.startswith("SPY260918")
    assert {call[1]["data"]["schema"] for call in post.calls} == {
        "definition",
        "ohlcv-1d",
    }
    assert all(call[1]["auth"] == ("secret", "") for call in post.calls)
    assert all(
        call[1]["data"]["stype_in"] == "raw_symbol"
        and call[1]["data"]["map_symbols"] == "true"
        and "stype_out" not in call[1]["data"]
        for call in post.calls
        if call[1]["data"]["schema"] == "ohlcv-1d"
    )


def test_daily_bars_limit_each_provider_request_to_twenty_contracts():
    post = _Post()
    provider = DatabentoOptionsProvider(api_key="secret", http_post=post)
    symbols = tuple(
        f"SPY   260918C{600000 + index:08d}"
        for index in range(45)
    )

    bars = provider.daily_bars(
        symbols,
        as_of=AS_OF,
        session_date=AS_OF.date(),
    )

    requests = [
        call[1]["data"]["symbols"].split(",")
        for call in post.calls
        if call[1]["data"]["schema"] == "ohlcv-1d"
    ]
    assert [len(batch) for batch in requests] == [20, 20, 5]
    assert sum(len(batch) for batch in requests) == len(symbols)
    assert set(bars) == set(symbols)


def test_validation_returns_only_credential_safe_counts():
    provider = DatabentoOptionsProvider(api_key="secret", http_post=_Post())

    result = provider.validate_access(
        as_of=AS_OF,
        underlying_price=620.0,
    )

    assert result["dataset"] == "OPRA.PILLAR"
    assert result["definition_count"] == 4
    assert result["eligible_definition_count"] == 4
    assert result["priced_sample_count"] == 4
    assert result["session_date"] == "2026-07-30"
    assert set(result["sample_symbols"]) == {
        "SPY260918C00620000",
        "SPY260918P00620000",
        "SPY261218C00625000",
        "SPY261218P00625000",
    }
    assert "secret" not in json.dumps(result)


def test_missing_key_fails_closed():
    provider = DatabentoOptionsProvider(api_key="", http_post=_Post())

    assert provider.configured is False
    with pytest.raises(DatabentoOptionsError, match="API key"):
        provider.definitions("SPY", as_of=AS_OF)


def test_provider_retries_prior_weekday_when_latest_session_is_empty():
    calls = []

    def post(url, **kwargs):
        calls.append(kwargs["data"])
        if kwargs["data"]["start"] == "2026-07-30":
            return _Response(records=())
        return _Post()(url, **kwargs)

    provider = DatabentoOptionsProvider(api_key="secret", http_post=post)
    definitions = provider.definitions("SPY", as_of=AS_OF)

    assert definitions
    assert definitions[0].session_date.isoformat() == "2026-07-29"
    assert calls[0]["start"] == "2026-07-30"
    assert calls[1]["start"] == "2026-07-29"


def test_http_entitlement_error_is_credential_safe():
    def post(_url, **_kwargs):
        return _Response(status_code=402, detail="live license required")

    provider = DatabentoOptionsProvider(api_key="secret", http_post=post)
    with pytest.raises(DatabentoOptionsError, match="HTTP 402") as error:
        provider.definitions("SPY", as_of=AS_OF)

    assert "secret" not in str(error.value)
