from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from time import sleep
from types import SimpleNamespace

from cio import CandidateAssetClass
from operations import redundant_market_probe as probe
from operations.comprehensive_market_discovery_legacy import DiscoveryCatalogRecord
from providers.redundant_market_history import MarketHistoryCandidate


def _record(index: int) -> DiscoveryCatalogRecord:
    return DiscoveryCatalogRecord(
        symbol=f"FX{index:03d}",
        provider_symbol=f"FX{index:03d}=X",
        name=f"FX {index}",
        asset_class=CandidateAssetClass.FX,
        economic_exposure="fx",
        venue="FOREX",
        country_code="US",
        currency="USD",
        settlement_currency="USD",
        instrument_type="spot_fx",
        provider_kind="yahoo",
        source_identifier=f"symbol_directory:FOREX:test:FX{index:03d}",
    )


def _rows(as_of: datetime):
    return tuple(
        {
            "t": as_of - timedelta(days=2 - offset),
            "c": 1.0 + offset * 0.01,
            "v": 1_000_000.0,
        }
        for offset in range(3)
    )


def test_missing_market_evidence_is_bounded_concurrent_and_complete(monkeypatch):
    timestamp = datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc)
    records = tuple(_record(index) for index in range(25))
    policy = SimpleNamespace(minimum_history_bars=1, history_days=10)
    state = {"active": 0, "peak": 0, "calls": 0}
    lock = Lock()

    def candidate_set(record, **_kwargs):
        def loader():
            with lock:
                state["active"] += 1
                state["calls"] += 1
                state["peak"] = max(state["peak"], state["active"])
            try:
                sleep(0.015)
                return _rows(timestamp)
            finally:
                with lock:
                    state["active"] -= 1

        return (
            MarketHistoryCandidate(
                provider="fixture",
                capability="fx_history",
                dataset="fixture-history",
                provider_symbol=record.provider_symbol,
                instrument_identity=f"fx:{record.symbol}",
                loader=loader,
                configured=True,
                authenticated=True,
            ),
        )

    monkeypatch.setattr(probe._core, "_candidate_set", candidate_set)
    progress = []
    result = probe._fetch_missing_concurrently(
        records,
        timestamp=timestamp,
        policy=policy,
        http_get=lambda *_args, **_kwargs: None,
        eodhd=object(),
        tradier=object(),
        massive=object(),
        twelve=object(),
        coinbase=object(),
        kraken=object(),
        alpaca_crypto_rows={},
        already_processed=0,
        already_evidence_complete=0,
        decision_eligible_records=len(records),
        maximum_workers=4,
        progress_callback=lambda stage, *, metrics: progress.append((stage, metrics)),
    )

    assert tuple(result) == tuple(record.symbol for record in records)
    assert state["calls"] == len(records)
    assert 1 < state["peak"] <= 4
    assert progress[-1][0] == "deep_market_evidence:fx"
    assert progress[-1][1] == {
        "decision_eligible_records": 25,
        "processed_records": 25,
        "total_records": 25,
        "evidence_complete_records": 25,
    }


def test_worker_configuration_is_capped(monkeypatch):
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DEEP_MARKET_IO_WORKERS", "999")
    assert probe._resolved_worker_count(753) == probe._MAX_DEEP_MARKET_IO_WORKERS
    assert probe._resolved_worker_count(3) == 3
