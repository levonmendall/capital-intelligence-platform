from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from historical_replay.canonical import HistoricalCanonicalContextBuilder
from historical_replay.canonical_runtime import (
    EfficientCanonicalHistoricalReplayEngine,
)
from historical_replay.models import HistoricalRecord
from historical_replay.store import HistoricalStore

UTC = timezone.utc


def _price_record(
    day: date,
    index: int,
    *,
    strict: bool = True,
) -> HistoricalRecord:
    observed = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return HistoricalRecord(
        source="fixture",
        dataset="daily_ohlcv.btc-usd",
        observed_at=observed,
        available_at=observed + timedelta(hours=1),
        retrieved_at="2026-07-29T00:00:00Z",
        strict_replay_eligible=strict,
        payload={
            "symbol": "BTC-USD",
            "open": 100.0 + index,
            "high": 101.0 + index,
            "low": 99.0 + index,
            "close": 100.5 + index,
            "volume": 1_000_000.0,
            "currency": "USD",
        },
    )


class CountingStore(HistoricalStore):
    def __init__(self, root):
        super().__init__(root)
        self.iteration_count = 0

    def iter_records(self, *args, **kwargs):
        self.iteration_count += 1
        yield from super().iter_records(*args, **kwargs)


def test_canonical_replay_invokes_real_cio_without_execution_authority(
    tmp_path,
):
    store = HistoricalStore(tmp_path)
    start = date(2019, 10, 1)
    store.append(
        _price_record(start + timedelta(days=index), index)
        for index in range(123)
    )

    report = EfficientCanonicalHistoricalReplayEngine(
        store,
        builder=HistoricalCanonicalContextBuilder(
            minimum_observations=21,
            maximum_candidates=5,
        ),
    ).run(
        start=date(2020, 1, 1),
        end=date(2020, 1, 31),
        cadence="monthly",
        strict_only=True,
    )

    assert report["canonical_cio_available"] is True
    assert report["canonical_cio_invoked_count"] == 1
    assert report["blocked_cutoff_count"] == 0
    assert report["runtime_version"] == "single-pass-availability-cursor.v1"
    assert report["archive_scan_count"] == 1
    assert report["price_record_count"] == 123
    assert report["research_only"] is True
    assert report["execution_authorized"] is False
    assert report["paper_execution_authorized"] is False
    assert report["real_money_authorized"] is False
    assert report["policy_promotion_authorized"] is False
    assert report["performance_claims_authorized"] is False
    assert report["decisions"][0]["canonical_cio_invoked"] is True
    assert (
        tmp_path / "manifests" / "latest-canonical-replay.json"
    ).exists()


def test_non_strict_bridge_is_visible_as_research_only(tmp_path):
    store = HistoricalStore(tmp_path)
    start = date(2019, 10, 1)
    store.append(
        _price_record(
            start + timedelta(days=index),
            index,
            strict=False,
        )
        for index in range(123)
    )
    engine = EfficientCanonicalHistoricalReplayEngine(
        store,
        builder=HistoricalCanonicalContextBuilder(
            minimum_observations=21,
        ),
    )

    research = engine.run(
        start=date(2020, 1, 1),
        end=date(2020, 1, 31),
        strict_only=False,
    )
    strict = engine.run(
        start=date(2020, 1, 1),
        end=date(2020, 1, 31),
        strict_only=True,
    )

    assert research["strict_replay"] is False
    assert research["canonical_cio_invoked_count"] == 1
    assert strict["canonical_cio_invoked_count"] == 0
    assert strict["blocked_cutoff_count"] == 1


def test_multi_cutoff_replay_scans_archive_once(tmp_path):
    store = CountingStore(tmp_path)
    start = date(2019, 9, 1)
    store.append(
        _price_record(start + timedelta(days=index), index)
        for index in range(183)
    )

    report = EfficientCanonicalHistoricalReplayEngine(
        store,
        builder=HistoricalCanonicalContextBuilder(
            minimum_observations=21,
            maximum_candidates=5,
        ),
    ).run(
        start=date(2020, 1, 1),
        end=date(2020, 2, 29),
        cadence="monthly",
        strict_only=True,
    )

    assert store.iteration_count == 1
    assert report["archive_scan_count"] == 1
    assert report["decision_cutoff_count"] == 2
    assert report["canonical_cio_invoked_count"] == 2
    visible_counts = [
        item["visible_record_count"] for item in report["decisions"]
    ]
    assert visible_counts == sorted(visible_counts)
