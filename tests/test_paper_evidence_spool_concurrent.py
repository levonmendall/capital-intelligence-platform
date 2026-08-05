"""Regression coverage for bounded concurrent SEC company-fact collection."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from operations.paper_evidence_spool import close_spooled_paper_evidence
from operations.paper_evidence_spool_concurrent import (
    collect_spooled_paper_evidence,
)


AS_OF = datetime(2026, 8, 5, 1, 30, tzinfo=timezone.utc)
_US_EQUITY = object()


class CandidateAssetClass:
    US_EQUITY = _US_EQUITY


class Query:
    def __init__(self, **values) -> None:
        self.__dict__.update(values)


class AlpacaClient:
    def historical_bars(self, symbols, **_kwargs):
        return {symbol: [] for symbol in symbols}

    def latest_quotes(self, symbols):
        return {
            symbol: {"timestamp": AS_OF.isoformat(), "bid_price": 1.0, "ask_price": 1.1}
            for symbol in symbols
        }

    def clock(self):
        return {"timestamp": AS_OF.isoformat(), "is_open": False}


class FredProvider:
    def get_latest_value(self, series):
        return SimpleNamespace(date="2026-08-04", value=4.0, series=series)


class ConcurrencyState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.maximum = 0


class SecProvider:
    def __init__(self, state: ConcurrencyState) -> None:
        self.state = state

    def fetch_company_facts(self, _query):
        with self.state.lock:
            self.state.active += 1
            self.state.maximum = max(self.state.maximum, self.state.active)
        try:
            time.sleep(0.03)
            return ()
        finally:
            with self.state.lock:
                self.state.active -= 1


def instrument(symbol: str, cik: str):
    return SimpleNamespace(
        symbol=symbol,
        issuer_cik=cik,
        uses_direct_market_provider=False,
        execution_asset_class=_US_EQUITY,
        instrument_type="common_stock",
    )


def test_company_facts_overlap_and_emit_progress(capsys, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_EVIDENCE_SPOOL_DIR", str(tmp_path))
    state = ConcurrencyState()
    universe = SimpleNamespace(
        identifier="concurrent-sec-test",
        limitations=(),
        instruments=(
            instrument("AAA", "0000000001"),
            instrument("BBB", "0000000002"),
            instrument("CCC", "0000000003"),
            instrument("DDD", "0000000004"),
        ),
    )

    payload = collect_spooled_paper_evidence(
        universe,
        AS_OF,
        create_alpaca_client=AlpacaClient,
        sec_provider_factory=lambda: SecProvider(state),
        fred_provider_factory=FredProvider,
        direct_market_client_type=object,
        direct_market_universe_type=object,
        filing_query_type=Query,
        candidate_asset_class=CandidateAssetClass,
        instrument_evaluation_scheduled=lambda _instrument, _as_of: True,
        history_days=30,
        listed_batch_size=4,
        sec_workers=4,
        sec_issuer_start_interval_seconds=0.0,
    )
    try:
        assert state.maximum >= 2
        assert set(payload["company_facts"]) == {"AAA", "BBB", "CCC", "DDD"}
        output = capsys.readouterr().out
        assert "paper_evidence_collection_started" in output
        assert "paper_evidence_company_facts_started" in output
        assert "paper_evidence_company_facts_completed" in output
        assert "paper_evidence_collection_completed" in output
    finally:
        close_spooled_paper_evidence(payload)


def test_sec_worker_count_is_bounded(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_EVIDENCE_SPOOL_DIR", str(tmp_path))
    universe = SimpleNamespace(
        identifier="invalid-worker-test",
        limitations=(),
        instruments=(instrument("AAA", "0000000001"),),
    )

    try:
        collect_spooled_paper_evidence(
            universe,
            AS_OF,
            create_alpaca_client=AlpacaClient,
            sec_provider_factory=lambda: SecProvider(ConcurrencyState()),
            fred_provider_factory=FredProvider,
            direct_market_client_type=object,
            direct_market_universe_type=object,
            filing_query_type=Query,
            candidate_asset_class=CandidateAssetClass,
            instrument_evaluation_scheduled=lambda _instrument, _as_of: True,
            history_days=30,
            sec_workers=9,
            sec_issuer_start_interval_seconds=0.0,
        )
    except ValueError as error:
        assert "cannot exceed 8" in str(error)
    else:  # pragma: no cover - regression guard
        raise AssertionError("expected SEC worker bound to reject 9 workers")
