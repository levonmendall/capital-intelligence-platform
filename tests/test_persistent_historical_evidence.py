from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from types import MethodType

import pytest

from operations.persistent_historical_evidence import (
    PersistentHistoricalEvidenceError,
    PersistentHistoricalEvidenceStore,
    install_persistent_historical_evidence,
)
from operations.resumable_options_discovery import ResumableOptionsProvider
from providers.redundant_market_history import (
    MarketHistoryCandidate,
    RedundantMarketHistoryRouter,
)
from providers.redundant_options import RedundantOptionBar


def _market_rows(as_of: datetime, count: int = 4):
    return tuple(
        {
            "t": as_of - timedelta(days=count - index - 1),
            "c": 100.0 + index,
            "v": 1_000.0 + index,
        }
        for index in range(count)
    )


def test_store_rejects_future_evidence(tmp_path) -> None:
    as_of = datetime(2026, 8, 14, 12, tzinfo=timezone.utc)
    store = PersistentHistoricalEvidenceStore(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    )

    with pytest.raises(PersistentHistoricalEvidenceError):
        store.merge(
            asset_class="crypto",
            instrument_identity="btc-usd",
            provider_scope="coinbase:crypto_history:exchange-candles",
            rows=(
                {
                    "t": as_of + timedelta(seconds=1),
                    "c": 100.0,
                    "v": 1.0,
                },
            ),
            requested_as_of=as_of,
            requested_history_days=365,
        )


def test_store_preserves_t1_snapshot_after_t2_refresh(tmp_path) -> None:
    t1 = datetime(2026, 8, 14, 12, tzinfo=timezone.utc)
    t2 = t1 + timedelta(days=1)
    observed = t1 - timedelta(days=1)
    store = PersistentHistoricalEvidenceStore(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    )

    first = store.merge(
        asset_class="crypto",
        instrument_identity="btc-usd",
        provider_scope="coinbase:crypto_history:exchange-candles",
        rows=({"t": observed, "c": 100.0, "v": 1.0},),
        requested_as_of=t1,
        requested_history_days=365,
    )
    second = store.merge(
        asset_class="crypto",
        instrument_identity="btc-usd",
        provider_scope="coinbase:crypto_history:exchange-candles",
        rows=(
            {"t": observed, "c": 200.0, "v": 2.0},
            {"t": t2, "c": 300.0, "v": 3.0},
        ),
        requested_as_of=t2,
        requested_history_days=365,
    )
    replay = store.load(
        asset_class="crypto",
        instrument_identity="btc-usd",
        provider_scope="coinbase:crypto_history:exchange-candles",
        as_of=t1,
    )

    assert first.requested_as_of == t1
    assert second.requested_as_of == t2
    assert second.rows[0]["c"] == 200.0
    assert len(second.rows) == 2
    assert replay.requested_as_of == t1
    assert len(replay.rows) == 1
    assert replay.rows[0]["c"] == 100.0
    assert replay.rows[0]["v"] == 1.0


def test_store_rejects_backdated_refresh_after_newer_snapshot(tmp_path) -> None:
    t1 = datetime(2026, 8, 14, 12, tzinfo=timezone.utc)
    t2 = t1 + timedelta(days=1)
    store = PersistentHistoricalEvidenceStore(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    )
    store.merge(
        asset_class="crypto",
        instrument_identity="btc-usd",
        provider_scope="coinbase:crypto_history:exchange-candles",
        rows=({"t": t1, "c": 100.0, "v": 1.0},),
        requested_as_of=t2,
        requested_history_days=365,
    )

    with pytest.raises(PersistentHistoricalEvidenceError, match="cannot backdate"):
        store.merge(
            asset_class="crypto",
            instrument_identity="btc-usd",
            provider_scope="coinbase:crypto_history:exchange-candles",
            rows=({"t": t1, "c": 99.0, "v": 1.0},),
            requested_as_of=t1,
            requested_history_days=365,
        )


def test_legacy_projection_is_not_backdated_during_snapshot_upgrade(tmp_path) -> None:
    t1 = datetime(2026, 8, 14, 12, tzinfo=timezone.utc)
    t2 = t1 + timedelta(days=1)
    store = PersistentHistoricalEvidenceStore(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    )
    store.merge(
        asset_class="crypto",
        instrument_identity="btc-usd",
        provider_scope="coinbase:crypto_history:exchange-candles",
        rows=({"t": t1, "c": 100.0, "v": 1.0},),
        requested_as_of=t2,
        requested_history_days=365,
    )
    assert store.path is not None
    connection = sqlite3.connect(str(store.path))
    try:
        with connection:
            connection.execute("DELETE FROM historical_evidence_row_versions")
            connection.execute("DELETE FROM historical_evidence_snapshots")
    finally:
        connection.close()

    with pytest.raises(PersistentHistoricalEvidenceError) as failure:
        store.load(
            asset_class="crypto",
            instrument_identity="btc-usd",
            provider_scope="coinbase:crypto_history:exchange-candles",
            as_of=t1,
        )

    message = str(failure.value)
    assert "refreshed after the decision epoch" in message
    assert "instrument_identity=btc-usd" in message
    assert f"decision_epoch={t1.isoformat()}" in message
    assert f"earliest_available_requested_as_of={t2.isoformat()}" in message


def test_market_router_reuses_recent_exact_instrument_history(tmp_path, monkeypatch) -> None:
    install_persistent_historical_evidence()
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    as_of = datetime(2026, 8, 14, 12, tzinfo=timezone.utc)
    calls = {"count": 0}

    def loader():
        calls["count"] += 1
        return _market_rows(as_of)

    candidate = MarketHistoryCandidate(
        provider="coinbase",
        capability="crypto_history",
        dataset="exchange-candles",
        provider_symbol="BTC-USD",
        instrument_identity="crypto:btc-usd",
        loader=loader,
        authenticated=True,
    )

    first = RedundantMarketHistoryRouter().fetch(
        (candidate,),
        as_of=as_of,
        minimum_rows=3,
    )
    second = RedundantMarketHistoryRouter().fetch(
        (candidate,),
        as_of=as_of + timedelta(hours=1),
        minimum_rows=3,
    )

    assert calls["count"] == 1
    assert first.rows == second.rows
    assert second.instrument_identity == "crypto:btc-usd"


def test_option_deep_history_becomes_small_decision_time_delta(tmp_path) -> None:
    install_persistent_historical_evidence()
    base = datetime(2026, 8, 14, 12, tzinfo=timezone.utc)
    calls: list[int] = []

    class Delegate:
        pass

    provider = ResumableOptionsProvider(
        delegate=Delegate(),
        environ={
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
            "CAPITAL_INTELLIGENCE_RELEASE": "test-release",
            "CAPITAL_INTELLIGENCE_HISTORICAL_BASE_MAX_AGE_HOURS": "18",
        },
    )

    def primary_history(self, raw_symbols, *, as_of, history_days):
        calls.append(history_days)
        rows = tuple(
            RedundantOptionBar(
                raw_symbol="OPT1",
                observed_at=as_of - timedelta(days=history_days - index - 1),
                close=5.0 + index / 100.0,
                volume=100.0 + index,
                provider_kind="alpaca_indicative",
                source_identifier=f"alpaca:OPT1:{index}",
            )
            for index in range(history_days)
        )
        return {"OPT1": rows}

    provider._primary_history = MethodType(primary_history, provider)

    first = provider._resilient_history(
        ("OPT1",),
        as_of=base,
        history_days=365,
    )
    same_epoch_family = provider._resilient_history(
        ("OPT1",),
        as_of=base + timedelta(hours=1),
        history_days=365,
    )
    next_epoch = provider._resilient_history(
        ("OPT1",),
        as_of=base + timedelta(days=2),
        history_days=365,
    )

    assert len(first["OPT1"]) >= 365
    assert len(same_epoch_family["OPT1"]) >= 365
    assert len(next_epoch["OPT1"]) >= 365
    assert calls[0] == 365
    assert len(calls) == 2
    assert calls[1] < 365
    assert calls[1] >= 7
