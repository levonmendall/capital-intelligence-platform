from __future__ import annotations

from datetime import date

from historical_replay.backfill import HistoricalBackfillCoordinator
from historical_replay.models import HistoricalRecord, SourceResult
from historical_replay.replay import ShadowReplayEngine, replay_dates
from historical_replay.store import HistoricalStore


def record(day: str, close: float, *, symbol: str = "TEST", available: str | None = None, strict: bool = True):
    return HistoricalRecord(
        source="fixture",
        dataset=f"daily_ohlcv.{symbol.lower()}",
        observed_at=day,
        available_at=available or day,
        retrieved_at="2026-07-29T00:00:00Z",
        strict_replay_eligible=strict,
        payload={"symbol": symbol, "close": close},
    )


def test_record_hash_is_deterministic():
    first = record("2020-01-01", 100)
    second = record("2020-01-01", 100)
    assert first.content_hash == second.content_hash
    assert first.record_id == second.record_id


def test_store_is_append_only_and_deduplicates(tmp_path):
    store = HistoricalStore(tmp_path)
    item = record("2020-01-01", 100)
    assert store.append([item]) == (1, 0)
    assert store.append([item]) == (0, 1)
    assert [entry.record_id for entry in store.iter_records()] == [item.record_id]


def test_availability_cutoff_prevents_lookahead(tmp_path):
    store = HistoricalStore(tmp_path)
    early = record("2020-01-01", 100, available="2020-01-02")
    late = record("2020-01-02", 110, available="2020-02-01")
    store.append([early, late])
    visible = list(store.iter_records(available_before="2020-01-15T00:00:00Z"))
    assert visible == [early]


def test_strict_filter_excludes_research_only_feed(tmp_path):
    store = HistoricalStore(tmp_path)
    store.append([record("2020-01-01", 100, strict=False), record("2020-01-02", 101, symbol="STRICT")])
    assert [item.payload["symbol"] for item in store.iter_records(strict_only=True)] == ["STRICT"]


class FixtureSource:
    name = "fixture"

    def collect(self, start, end, *, max_records):
        return SourceResult(self.name, "available", (record(start.isoformat(), 100),))


def test_coordinator_persists_report_and_checkpoint(tmp_path):
    store = HistoricalStore(tmp_path)
    report = HistoricalBackfillCoordinator(store=store, sources=(FixtureSource(),)).run(
        start=date(2020, 1, 1), end=date(2020, 1, 2)
    )
    assert report.records_written == 1
    assert store.read_checkpoint("fixture")["completed_through"] == "2020-01-02"
    assert (tmp_path / "manifests" / "latest-backfill.json").exists()


def test_monthly_and_weekly_replay_dates_are_bounded():
    monthly = replay_dates(date(2020, 1, 10), date(2020, 3, 31), "monthly")
    weekly = replay_dates(date(2020, 1, 10), date(2020, 1, 31), "weekly")
    assert monthly == (date(2020, 1, 31), date(2020, 2, 29), date(2020, 3, 31))
    assert all(date(2020, 1, 10) <= item <= date(2020, 1, 31) for item in weekly)


def test_shadow_replay_is_research_only_and_never_executes(tmp_path):
    store = HistoricalStore(tmp_path)
    prices = [record(f"2020-01-{day:02d}", 100 + day) for day in range(1, 30)]
    store.append(prices)
    decision = ShadowReplayEngine(store).decision(cutoff=date(2020, 1, 29))
    assert decision.selected_assets == ("TEST",)
    assert decision.weights == {"TEST": 1.0}
    assert decision.research_only is True
    assert decision.canonical_cio_invoked is False
    assert decision.execution_authorized is False
    assert decision.real_money_authorized is False
    assert decision.performance_claims_authorized is False
