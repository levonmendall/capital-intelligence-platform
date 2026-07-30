from __future__ import annotations

from datetime import date, datetime, timezone

from historical_replay.canonical import HistoricalCanonicalContextBuilder
from historical_replay.canonical_runtime_v5 import (
    MacroCompleteCanonicalHistoricalReplayEngine,
)
from historical_replay.models import HistoricalRecord
from historical_replay.sources import build_sources
from historical_replay.sources_cboe import CBOE_VIX_HISTORY_URL, CboeVixSource
from historical_replay.store import HistoricalStore

UTC = timezone.utc


class CsvResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")


class CsvClient:
    def __init__(self, body: str) -> None:
        self.body = body
        self.urls: list[str] = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        return CsvResponse(self.body)


def _macro_record(
    source: str,
    dataset: str,
    available_at: str,
    value: float,
) -> HistoricalRecord:
    return HistoricalRecord(
        source=source,
        dataset=dataset,
        observed_at="2016-07-29",
        available_at=available_at,
        retrieved_at="2026-07-30T00:00:00Z",
        strict_replay_eligible=True,
        payload={"series_id": dataset.removeprefix("series.").upper(), "value": value},
    )


def test_cboe_vix_history_publishes_strict_conservative_records() -> None:
    client = CsvClient(
        "DATE,OPEN,HIGH,LOW,CLOSE\n"
        "06/28/2016,18.00,19.00,17.50,18.75\n"
        "07/29/2016,12.00,13.00,11.50,12.05\n"
        "07/30/2026,20.00,21.00,19.50,20.25\n"
    )

    result = CboeVixSource(client).collect(
        date(2016, 7, 30),
        date(2026, 7, 29),
        max_records=100,
    )

    assert result.state == "available"
    assert client.urls == [CBOE_VIX_HISTORY_URL]
    assert len(result.records) == 1
    record = result.records[0]
    assert record.source == "cboe"
    assert record.dataset == "series.vixcls"
    assert record.observed_at == "2016-07-29T00:00:00Z"
    assert record.available_at == "2016-07-30T00:00:00Z"
    assert record.strict_replay_eligible is True
    assert record.payload["value"] == 12.05
    assert record.payload["availability_policy"] == "conservative_next_calendar_day"


def test_macro_gate_accepts_required_evidence_across_governed_sources(tmp_path) -> None:
    store = HistoricalStore(tmp_path)
    store.append(
        (
            _macro_record("fred", "series.fedfunds", "2016-07-30", 0.40),
            _macro_record("fred", "series.t10y2y", "2016-07-30", 0.85),
            _macro_record("cboe", "series.vixcls", "2016-07-30", 12.05),
        )
    )
    engine = MacroCompleteCanonicalHistoricalReplayEngine(
        store,
        builder=HistoricalCanonicalContextBuilder(
            minimum_observations=21,
            maximum_candidates=5,
        ),
    )

    coverage = engine._macro_availability()
    missing = engine._missing_at_cutoff(
        coverage,
        datetime(2016, 7, 31, 23, 59, 59, tzinfo=UTC),
    )

    assert missing == ()
    assert coverage["series.vixcls"] == (
        datetime(2016, 7, 30, tzinfo=UTC),
    )


def test_source_factory_requires_explicit_cboe_vix_enablement() -> None:
    disabled = build_sources(
        {
            "sources": {
                "fred": {"enabled": False},
                "cboe_vix": {"enabled": False},
                "coinbase": {"enabled": False},
                "stooq": {"enabled": False},
                "world_bank": {"enabled": False},
                "federal_register": {"enabled": False},
                "sec_edgar": {"enabled": False},
                "cftc": {"enabled": False},
                "treasury_fiscal_data": {"enabled": False},
                "gdelt": {"enabled": False},
            }
        },
        user_agent="test",
    )
    enabled = build_sources(
        {
            "sources": {
                "fred": {"enabled": False},
                "cboe_vix": {"enabled": True},
                "coinbase": {"enabled": False},
                "stooq": {"enabled": False},
                "world_bank": {"enabled": False},
                "federal_register": {"enabled": False},
                "sec_edgar": {"enabled": False},
                "cftc": {"enabled": False},
                "treasury_fiscal_data": {"enabled": False},
                "gdelt": {"enabled": False},
            }
        },
        user_agent="test",
    )

    assert disabled == ()
    assert len(enabled) == 1
    assert isinstance(enabled[0], CboeVixSource)
