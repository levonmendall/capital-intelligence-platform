from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from providers.redundant_market_history import (
    ALL_ASSET_REDUNDANCY_POLICY,
    MarketHistoryCandidate,
    ProviderFailureClass,
    RedundantMarketHistoryError,
    RedundantMarketHistoryRouter,
)
from providers.twelve_data_history import TwelveDataHistoryProvider


AS_OF = datetime(2026, 8, 11, 16, 0, tzinfo=timezone.utc)


def _rows(count: int, *, price: float = 100.0):
    return tuple(
        {
            "t": AS_OF - timedelta(days=count - index),
            "c": price + index,
            "v": 1_000_000.0,
        }
        for index in range(count)
    )


class _ProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def test_primary_provider_remains_authoritative_when_complete() -> None:
    router = RedundantMarketHistoryRouter()
    fallback_called = False

    def fallback():
        nonlocal fallback_called
        fallback_called = True
        return _rows(300, price=200.0)

    result = router.fetch(
        (
            MarketHistoryCandidate("alpaca", "SPY", lambda: _rows(300)),
            MarketHistoryCandidate("yahoo", "SPY", fallback),
        ),
        as_of=AS_OF,
        minimum_rows=252,
    )

    assert result.provider == "alpaca"
    assert result.attempted_providers == ("alpaca",)
    assert not fallback_called
    assert result.evidence_identifiers[0].startswith("market-history:alpaca:SPY:")


def test_credit_cap_fails_over_and_blocks_provider_for_cycle() -> None:
    router = RedundantMarketHistoryRouter()
    primary_calls = 0

    def capped():
        nonlocal primary_calls
        primary_calls += 1
        raise _ProviderError("HTTP 402 plan cap", status_code=402)

    first = router.fetch(
        (
            MarketHistoryCandidate("eodhd", "US10Y.GBOND", capped),
            MarketHistoryCandidate("twelve_data", "US10Y", lambda: _rows(300)),
        ),
        as_of=AS_OF,
        minimum_rows=252,
    )
    second = router.fetch(
        (
            MarketHistoryCandidate("eodhd", "US2Y.GBOND", capped),
            MarketHistoryCandidate("twelve_data", "US2Y", lambda: _rows(300)),
        ),
        as_of=AS_OF,
        minimum_rows=252,
    )

    assert first.provider == "twelve_data"
    assert second.provider == "twelve_data"
    assert primary_calls == 1
    assert router.blocked_providers["eodhd"] is ProviderFailureClass.ACCESS_OR_CREDIT_CAP
    assert ("eodhd", "cycle_blocked:access_or_credit_cap") in second.failed_providers


def test_auth_lock_fails_over_without_reducing_history_requirement() -> None:
    router = RedundantMarketHistoryRouter()

    def locked():
        raise _ProviderError("HTTP 403 account locked", status_code=403)

    with pytest.raises(RedundantMarketHistoryError) as captured:
        router.fetch(
            (
                MarketHistoryCandidate("databento", "ESU26", locked),
                MarketHistoryCandidate("yahoo", "ESU26.CME", lambda: _rows(120)),
            ),
            as_of=AS_OF,
            minimum_rows=252,
        )

    detail = str(captured.value)
    assert "databento=authentication_or_entitlement" in detail
    assert "yahoo=insufficient_evidence" in detail


def test_unconfigured_provider_is_skipped_without_failure() -> None:
    router = RedundantMarketHistoryRouter()
    result = router.fetch(
        (
            MarketHistoryCandidate("twelve_data", "EUR/USD", lambda: (), configured=False),
            MarketHistoryCandidate("yahoo", "EURUSD=X", lambda: _rows(300)),
        ),
        as_of=AS_OF,
        minimum_rows=252,
    )
    assert result.provider == "yahoo"
    assert result.attempted_providers == ("yahoo",)
    assert ("twelve_data", "not_configured") in result.failed_providers


def test_every_investable_asset_policy_has_redundancy_for_required_market_evidence() -> None:
    expected = {
        "us_equity",
        "us_etf",
        "international_equity",
        "fx",
        "crypto",
        "future",
        "fixed_income",
        "option",
    }
    assert set(ALL_ASSET_REDUNDANCY_POLICY) == expected
    for asset, roles in ALL_ASSET_REDUNDANCY_POLICY.items():
        assert "history" in roles, asset
        assert len(set(roles["history"])) >= 2, asset


def test_twelve_data_history_is_utc_normalized_and_point_in_time() -> None:
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "meta": {"symbol": "EUR/USD"},
                "values": [
                    {"datetime": "2026-08-09", "close": "1.16", "volume": "10"},
                    {"datetime": "2026-08-10", "close": "1.17", "volume": "11"},
                    {"datetime": "2026-08-12", "close": "9.99", "volume": "99"},
                ],
                "status": "ok",
            }

    provider = TwelveDataHistoryProvider(
        api_key="test",
        max_attempts=1,
        http_get=lambda *_args, **_kwargs: Response(),
    )
    symbol, rows = provider.daily_history(
        ("EUR/USD",),
        as_of=AS_OF,
        history_days=30,
    )

    assert symbol == "EUR/USD"
    assert len(rows) == 2
    assert rows[-1]["c"] == 1.17
    assert rows[-1]["t"].tzinfo is not None


def test_twelve_data_access_cap_is_classifiable() -> None:
    class Response:
        status_code = 402

        @staticmethod
        def json():
            return {}

    provider = TwelveDataHistoryProvider(
        api_key="test",
        max_attempts=1,
        http_get=lambda *_args, **_kwargs: Response(),
    )
    router = RedundantMarketHistoryRouter()
    result = router.fetch(
        (
            MarketHistoryCandidate(
                "twelve_data",
                "BTC/USD",
                lambda: provider.daily_history(
                    ("BTC/USD",), as_of=AS_OF, history_days=760
                )[1],
            ),
            MarketHistoryCandidate("yahoo", "BTC-USD", lambda: _rows(300)),
        ),
        as_of=AS_OF,
        minimum_rows=252,
    )

    assert result.provider == "yahoo"
    assert router.blocked_providers["twelve_data"] is ProviderFailureClass.ACCESS_OR_CREDIT_CAP
