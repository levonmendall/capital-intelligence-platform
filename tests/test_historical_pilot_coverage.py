from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from historical_replay.canonical import HistoricalCanonicalContextBuilder, ReplayPortfolioState
from historical_replay.models import HistoricalRecord
from operations.free_paper_pilot import DEFAULT_UNIVERSE_PATH

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def _records(symbol: str, count: int = 80) -> tuple[HistoricalRecord, ...]:
    start = date(2025, 1, 1)
    values = []
    for index in range(count):
        observed = datetime.combine(
            start + timedelta(days=index), datetime.min.time(), tzinfo=UTC
        )
        values.append(
            HistoricalRecord(
                source="fixture",
                dataset=f"daily_ohlcv.{symbol.lower()}.us",
                observed_at=observed,
                available_at=observed + timedelta(hours=1),
                retrieved_at="2026-07-31T00:00:00Z",
                strict_replay_eligible=True,
                payload={
                    "symbol": f"{symbol}.US",
                    "open": 100.0 + index,
                    "high": 101.0 + index,
                    "low": 99.0 + index,
                    "close": 100.5 + index,
                    "volume": 2_000_000.0,
                },
            )
        )
    return tuple(values)


def test_historical_source_configuration_matches_canonical_pilot_symbols() -> None:
    config = json.loads(
        (ROOT / "config/historical_replay_free_sources.json").read_text(
            encoding="utf-8"
        )
    )
    configured = {
        item.removesuffix(".us").upper()
        for item in config["sources"]["stooq"]["symbols"]
    }
    pilot = json.loads(
        (ROOT / "config/free_paper_pilot_universe.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {item["symbol"] for item in pilot["instruments"]}
    assert configured == expected


def test_builder_preserves_canonical_identity_and_explicitly_accounts_for_missing_symbols() -> None:
    builder = HistoricalCanonicalContextBuilder(
        minimum_observations=21,
        universe_path=DEFAULT_UNIVERSE_PATH,
    )
    cutoff = datetime(2025, 5, 1, 23, 59, 59, tzinfo=UTC)
    candidates, _, _, _, _ = builder.build(
        records=_records("GOVT"),
        cutoff=cutoff,
        state=ReplayPortfolioState(),
        strict_only=True,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.instrument.instrument_id == "instrument:us-etf:govt"
    assert candidate.instrument.symbol == "GOVT"
    assert candidate.instrument.venue == "CBOE"
    assert candidate.instrument.asset_class.value == "us_etf"
    assert candidate.instrument.economic_exposure_class.value == "fixed_income"
    assert len(builder.last_exclusions) == 14
    assert {item["symbol"] for item in builder.last_exclusions} == (
        set(builder.universe.symbol_map) - {"GOVT"}
    )
