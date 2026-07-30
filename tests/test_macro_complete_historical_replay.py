from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from historical_replay.canonical import HistoricalCanonicalContextBuilder
from historical_replay.canonical_runtime_v5 import (
    MacroCompleteCanonicalHistoricalReplayEngine,
    REQUIRED_MACRO_DATASETS,
)
from historical_replay.models import HistoricalRecord
from historical_replay.sources_market import FredSource
from historical_replay.store import HistoricalStore

UTC = timezone.utc


class JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class PartialFredClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def get(self, _url, *, params):
        self.calls.append(dict(params))
        if params["series_id"] == "GDP":
            raise RuntimeError("one series is temporarily unavailable")
        return JsonResponse(
            {
                "observations": [
                    {
                        "date": "2020-01-01",
                        "value": "1.50",
                        "realtime_start": "2020-01-02",
                        "realtime_end": "9999-12-31",
                    }
                ]
            }
        )


def _price_record(day: date, index: int) -> HistoricalRecord:
    observed = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return HistoricalRecord(
        source="fixture",
        dataset="daily_ohlcv.btc-usd",
        observed_at=observed,
        available_at=observed + timedelta(hours=1),
        retrieved_at="2026-07-30T00:00:00Z",
        strict_replay_eligible=True,
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


def _macro_record(dataset: str, available: str, value: float) -> HistoricalRecord:
    series = dataset.removeprefix("series.").upper()
    return HistoricalRecord(
        source="fred",
        dataset=dataset,
        observed_at="2019-12-01",
        available_at=available,
        retrieved_at="2026-07-30T00:00:00Z",
        strict_replay_eligible=True,
        payload={
            "series_id": series,
            "value": value,
            "realtime_start": available,
            "fred_output_type": 4,
        },
        limitations=("release_time_normalized_to_date",),
    )


def _engine(store: HistoricalStore) -> MacroCompleteCanonicalHistoricalReplayEngine:
    return MacroCompleteCanonicalHistoricalReplayEngine(
        store,
        builder=HistoricalCanonicalContextBuilder(
            minimum_observations=21,
            maximum_candidates=5,
        ),
    )


def test_fred_initial_release_collection_isolates_series_failure() -> None:
    client = PartialFredClient()
    result = FredSource(
        client,
        ("GDP", "FEDFUNDS"),
        api_key="a" * 32,
    ).collect(
        date(2020, 1, 1),
        date(2020, 1, 31),
        max_records=100,
    )

    assert result.state == "degraded"
    assert len(result.records) == 1
    assert result.records[0].dataset == "series.fedfunds"
    assert result.records[0].strict_replay_eligible is True
    assert result.records[0].available_at == "2020-01-02"
    assert "series_failed_count:1" in result.warnings
    assert all(call["output_type"] == 4 for call in client.calls)
    assert all("realtime_start" not in call for call in client.calls)
    assert all("realtime_end" not in call for call in client.calls)


def test_price_only_replay_cannot_certify(tmp_path) -> None:
    store = HistoricalStore(tmp_path)
    start = date(2019, 9, 1)
    store.append(
        _price_record(start + timedelta(days=index), index)
        for index in range(183)
    )

    report = _engine(store).run(
        start=date(2020, 1, 1),
        end=date(2020, 2, 29),
        strict_only=True,
    )

    assert report["schema_version"] == "canonical-historical-replay.v5"
    assert report["runtime_version"] == "single-pass-availability-cursor.v5"
    assert report["certification_ready"] is False
    assert report["macro_coverage_satisfied"] is False
    assert report["present_macro_dataset_count"] == 0
    assert report["missing_macro_datasets"] == list(REQUIRED_MACRO_DATASETS)
    assert report["macro_incomplete_cutoff_count"] == 2
    sidecar = json.loads(
        (tmp_path / "manifests" / "latest-canonical-learning.json").read_text(
            encoding="utf-8"
        )
    )
    assert sidecar["certification_ready"] is False
    assert sidecar["learning_observation_count"] == 0


def test_replay_certifies_only_with_all_required_point_in_time_macro_series(
    tmp_path,
) -> None:
    store = HistoricalStore(tmp_path)
    start = date(2019, 9, 1)
    store.append(
        _price_record(start + timedelta(days=index), index)
        for index in range(183)
    )
    store.append(
        (
            _macro_record("series.fedfunds", "2019-12-02", 1.50),
            _macro_record("series.t10y2y", "2019-12-02", 0.25),
            _macro_record("series.vixcls", "2019-12-02", 16.0),
        )
    )

    report = _engine(store).run(
        start=date(2020, 1, 1),
        end=date(2020, 2, 29),
        strict_only=True,
    )

    assert report["certification_ready"] is True
    assert report["macro_coverage_satisfied"] is True
    assert report["present_macro_datasets"] == list(REQUIRED_MACRO_DATASETS)
    assert report["missing_macro_datasets"] == []
    assert report["macro_incomplete_cutoff_count"] == 0
    assert report["macro_record_count"] == 3
    assert all(
        item.get("macro_coverage_complete") is True
        for item in report["decisions"]
    )
    sidecar = json.loads(
        (tmp_path / "manifests" / "latest-canonical-learning.json").read_text(
            encoding="utf-8"
        )
    )
    assert sidecar["source_replay_schema_version"] == "canonical-historical-replay.v5"
    assert sidecar["source_runtime_version"] == "single-pass-availability-cursor.v5"
    assert sidecar["macro_coverage_satisfied"] is True
    assert sidecar["certification_ready"] is True
