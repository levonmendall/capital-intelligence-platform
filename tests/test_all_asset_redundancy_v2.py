from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from providers.redundancy_audit import begin_redundancy_cycle
from providers.redundant_market_history import (
    MarketHistoryCandidate,
    RedundantMarketHistoryError,
    RedundantMarketHistoryRouter,
)


AS_OF = datetime(2026, 8, 11, 20, 0, tzinfo=timezone.utc)


def _rows(count: int = 3):
    return tuple(
        {
            "t": AS_OF - timedelta(days=count - index),
            "c": 100.0 + index,
            "v": 1000.0,
        }
        for index in range(count)
    )


class Http403(RuntimeError):
    status_code = 403


def test_capability_breaker_does_not_disable_other_dataset() -> None:
    ledger = begin_redundancy_cycle("cycle-1", AS_OF)
    router = RedundantMarketHistoryRouter(audit=ledger)
    failed = MarketHistoryCandidate(
        provider="massive",
        capability="option_history",
        dataset="OPRA",
        provider_symbol="O:SPY260918C00600000",
        instrument_identity="option:spy:1",
        loader=lambda: (_ for _ in ()).throw(Http403("HTTP 403")),
    )
    fallback = MarketHistoryCandidate(
        provider="databento",
        capability="option_history",
        dataset="OPRA.PILLAR",
        provider_symbol="SPY   260918C00600000",
        instrument_identity="option:spy:1",
        loader=lambda: _rows(),
    )

    routed = router.fetch((failed, fallback), as_of=AS_OF, minimum_rows=3)

    assert routed.provider == "databento"
    assert routed.failed_over is True
    blocked = router.blocked_capabilities
    assert next(iter(blocked)).capability == "option_history"

    futures = MarketHistoryCandidate(
        provider="massive",
        capability="futures_history",
        dataset="futures-aggs",
        provider_symbol="ESU6",
        instrument_identity="future:ESU26",
        loader=lambda: _rows(),
    )
    routed_future = router.fetch((futures,), as_of=AS_OF, minimum_rows=3)
    assert routed_future.provider == "massive"
    assert routed_future.capability == "futures_history"


def test_router_refuses_cross_instrument_failover() -> None:
    router = RedundantMarketHistoryRouter()
    first = MarketHistoryCandidate(
        provider="alpaca",
        capability="us_equity_history",
        dataset="IEX",
        provider_symbol="AAPL",
        instrument_identity="figi:apple",
        loader=lambda: _rows(),
    )
    wrong = MarketHistoryCandidate(
        provider="twelve_data",
        capability="us_equity_history",
        dataset="time_series",
        provider_symbol="MSFT",
        instrument_identity="figi:microsoft",
        loader=lambda: _rows(),
    )

    with pytest.raises(RedundantMarketHistoryError, match="economic-instrument identities"):
        router.fetch((first, wrong), as_of=AS_OF, minimum_rows=3)


def test_fixed_income_requires_exact_security_identity() -> None:
    with pytest.raises(ValueError, match="exact-security identity"):
        MarketHistoryCandidate(
            provider="finra",
            capability="fixed_income_history",
            dataset="trace-aggregate",
            provider_symbol="TREASURY",
            instrument_identity="aggregate:treasury",
            loader=lambda: _rows(),
            fixed_income=True,
            exact_security_identity=False,
        )


def test_audit_records_all_required_state_transitions() -> None:
    ledger = begin_redundancy_cycle("cycle-audit", AS_OF)
    router = RedundantMarketHistoryRouter(audit=ledger)
    primary = MarketHistoryCandidate(
        provider="tradier",
        capability="us_equity_history",
        dataset="markets/history",
        provider_symbol="SPY",
        instrument_identity="equity:SPY",
        loader=lambda: (),
    )
    fallback = MarketHistoryCandidate(
        provider="massive",
        capability="us_equity_history",
        dataset="stocks-aggs",
        provider_symbol="SPY",
        instrument_identity="equity:SPY",
        loader=lambda: _rows(),
    )

    router.fetch((primary, fallback), as_of=AS_OF, minimum_rows=3)
    payload = ledger.to_dict()
    by_provider = {item["provider"]: item for item in payload["records"]}

    massive = by_provider["massive"]
    for field in (
        "configured",
        "authenticated",
        "routed",
        "certified_for_evidence_role",
        "attempted",
        "used",
        "failed_over",
    ):
        assert massive[field] is True
    assert payload["secret_values_included"] is False
    assert payload["decision_authority_granted"] is False
    assert payload["execution_authority_granted"] is False
