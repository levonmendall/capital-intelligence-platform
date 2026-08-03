"""Disk-backed paper evidence keeps complete scope outside process memory."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cio import CandidateAssetClass
from data import CompanyFact
from operations.paper_evidence_spool import (
    SQLiteEvidenceMapping,
    SQLitePaperEvidenceSpool,
    close_spooled_paper_evidence,
    collect_spooled_paper_evidence,
)


AS_OF = datetime(2026, 8, 3, 19, 0, tzinfo=timezone.utc)


def _fact() -> CompanyFact:
    return CompanyFact(
        cik="0000000001",
        taxonomy="us-gaap",
        tag="RevenueFromContractWithCustomerExcludingAssessedTax",
        unit="USD",
        value=1_000_000.0,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        filed_at=date(2026, 2, 1),
        accepted_at=datetime(2026, 2, 1, 21, 0, tzinfo=timezone.utc),
        retrieved_at=AS_OF,
        accession_number="0000000001-26-000001",
        form="10-K",
        fiscal_year=2025,
        fiscal_period="FY",
    )


def test_spool_round_trips_company_facts_and_is_append_only(
    tmp_path,
) -> None:
    fact = _fact()
    spool = SQLitePaperEvidenceSpool(tmp_path / "evidence.db")
    spool.append("company_facts", "AAA", (fact,), recorded_at=AS_OF)

    facts = spool.mapping("company_facts", tuple_result=True)
    assert isinstance(facts, SQLiteEvidenceMapping)
    assert facts["AAA"] == (fact,)

    spool.append("company_facts", "AAA", (fact,), recorded_at=AS_OF)
    with pytest.raises(ValueError, match="different content"):
        spool.append(
            "company_facts",
            "AAA",
            (replace(fact, value=2_000_000.0),),
            recorded_at=AS_OF,
        )

    path = spool.path
    assert path.exists()
    spool.close(remove=True)
    assert not path.exists()


class _Alpaca:
    def __init__(self) -> None:
        self.history_calls: list[tuple[str, ...]] = []
        self.quote_calls: list[tuple[str, ...]] = []

    def historical_bars(self, symbols, **_kwargs):
        batch = tuple(symbols)
        self.history_calls.append(batch)
        start = AS_OF - timedelta(days=300)
        return {
            symbol: tuple(
                {
                    "t": (start + timedelta(days=index)).isoformat(),
                    "c": 100.0 + index,
                    "v": 1_000_000.0,
                }
                for index in range(260)
            )
            for symbol in batch
        }

    def latest_quotes(self, symbols):
        batch = tuple(symbols)
        self.quote_calls.append(batch)
        return {
            symbol: {
                "t": AS_OF.isoformat(),
                "bp": 100.0,
                "ap": 100.1,
            }
            for symbol in batch
        }

    def clock(self):
        return {"timestamp": AS_OF.isoformat(), "is_open": True}


class _FRED:
    def get_latest_value(self, series):
        return SimpleNamespace(date="2026-08-03", value=4.0, series=series)


class _UnusedDirectClient:
    def __init__(self, _universe):
        raise AssertionError("direct-market client should not be constructed")


class _UnusedDirectUniverse:
    pass


def test_complete_listed_scope_is_collected_in_bounded_batches(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_EVIDENCE_SPOOL_DIR", str(tmp_path))
    symbols = tuple(f"S{index:02d}" for index in range(13))
    instruments = tuple(
        SimpleNamespace(
            symbol=symbol,
            uses_direct_market_provider=False,
            execution_asset_class=CandidateAssetClass.US_EQUITY,
            instrument_type="etf",
            issuer_cik=None,
        )
        for symbol in symbols
    )
    universe = SimpleNamespace(
        identifier="test-complete-universe",
        instruments=instruments,
        limitations=(),
    )
    alpaca = _Alpaca()

    payload = collect_spooled_paper_evidence(
        universe,
        AS_OF,
        create_alpaca_client=lambda: alpaca,
        sec_provider_factory=lambda: None,
        fred_provider_factory=_FRED,
        direct_market_client_type=_UnusedDirectClient,
        direct_market_universe_type=_UnusedDirectUniverse,
        filing_query_type=object,
        candidate_asset_class=CandidateAssetClass,
        instrument_evaluation_scheduled=lambda _instrument, _as_of: True,
        history_days=3650,
        listed_batch_size=4,
    )

    assert isinstance(payload["bars"], SQLiteEvidenceMapping)
    assert isinstance(payload["quotes"], SQLiteEvidenceMapping)
    assert set(payload["bars"]) == set(symbols)
    assert set(payload["quotes"]) == set(symbols)
    assert all(len(batch) <= 4 for batch in alpaca.history_calls)
    assert all(len(batch) <= 4 for batch in alpaca.quote_calls)
    assert len(payload["bars"][symbols[-1]]) == 260

    spool = payload["_evidence_spool"]
    assert isinstance(spool, SQLitePaperEvidenceSpool)
    path = spool.path
    assert path.exists()
    close_spooled_paper_evidence(payload)
    assert not path.exists()
