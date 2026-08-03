"""Regression coverage for complete-scope Alpaca historical-bar collection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import production_paper_evidence as paper_evidence
from providers.alpaca_paper import AlpacaPaperProviderError, AlpacaPaperSettings
from providers.alpaca_paper_resilient import (
    CompleteHistoricalAlpacaPaperClient,
    create_complete_alpaca_paper_client,
)


START = datetime(2025, 1, 1, tzinfo=timezone.utc)
END = START + timedelta(days=1)


class _FakeResponse:
    status_code = 200

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def json(self) -> object:
        return self._payload


def _settings() -> AlpacaPaperSettings:
    return AlpacaPaperSettings(
        api_key_id="paper-key",
        secret_key="paper-secret",
    )


def _bar(symbol: str, page: int = 0) -> dict[str, object]:
    return {
        "t": (START + timedelta(minutes=page)).isoformat(),
        "symbol": symbol,
    }


def test_broad_history_is_partitioned_without_dropping_symbols() -> None:
    calls: list[tuple[str, ...]] = []

    def http_get(_url: str, **kwargs: Any) -> _FakeResponse:
        params = kwargs["params"]
        symbols = tuple(str(params["symbols"]).split(","))
        calls.append(symbols)
        return _FakeResponse(
            {
                "bars": {symbol: [_bar(symbol)] for symbol in symbols},
                "next_page_token": None,
            }
        )

    client = CompleteHistoricalAlpacaPaperClient(
        _settings(),
        http_get=http_get,
    )
    symbols = tuple(f"S{index:04d}" for index in range(401))

    result = client.historical_bars(symbols, start=START, end=END)

    assert tuple(result) == symbols
    assert [len(batch) for batch in calls] == [200, 200, 1]
    assert all(len(result[symbol]) == 1 for symbol in symbols)


def test_valid_history_can_progress_beyond_the_old_hundred_page_limit() -> None:
    page = 0

    def http_get(_url: str, **_kwargs: Any) -> _FakeResponse:
        nonlocal page
        page += 1
        return _FakeResponse(
            {
                "bars": {"AAPL": [_bar("AAPL", page)]},
                "next_page_token": f"page-{page}" if page <= 101 else None,
            }
        )

    client = CompleteHistoricalAlpacaPaperClient(
        _settings(),
        http_get=http_get,
    )

    result = client.historical_bars(
        ("AAPL",),
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2025, 1, 1, tzinfo=timezone.utc),
        limit=1,
    )

    assert page == 102
    assert len(result["AAPL"]) == 102


def test_repeated_pagination_token_remains_fail_closed() -> None:
    page = 0

    def http_get(_url: str, **_kwargs: Any) -> _FakeResponse:
        nonlocal page
        page += 1
        return _FakeResponse(
            {
                "bars": {"AAPL": [_bar("AAPL", page)]},
                "next_page_token": "repeated-token",
            }
        )

    client = CompleteHistoricalAlpacaPaperClient(
        _settings(),
        http_get=http_get,
    )

    with pytest.raises(
        AlpacaPaperProviderError,
        match="pagination token repeated",
    ):
        client.historical_bars(("AAPL",), start=START, end=END)


def test_token_without_bar_progress_remains_fail_closed() -> None:
    client = CompleteHistoricalAlpacaPaperClient(
        _settings(),
        http_get=lambda _url, **_kwargs: _FakeResponse(
            {
                "bars": {"AAPL": []},
                "next_page_token": "non-progress-token",
            }
        ),
    )

    with pytest.raises(
        AlpacaPaperProviderError,
        match="token without data",
    ):
        client.historical_bars(("AAPL",), start=START, end=END)


def test_production_evidence_uses_complete_history_factory() -> None:
    paper_evidence._synchronize_runtime_bindings()

    assert paper_evidence.create_alpaca_paper_client is create_complete_alpaca_paper_client
    assert (
        paper_evidence._implementation.create_alpaca_paper_client
        is create_complete_alpaca_paper_client
    )
