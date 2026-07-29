from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from historical_replay.canonical import (
    HistoricalCanonicalContextBuilder,
    ReplayPortfolioState,
)
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

    assert report["schema_version"] == "canonical-historical-replay.v3"
    assert report["canonical_cio_available"] is True
    assert report["canonical_cio_invoked_count"] == 1
    assert report["blocked_cutoff_count"] == 0
    assert report["runtime_version"] == "single-pass-availability-cursor.v3"
    assert (
        report["learning_context_schema_version"]
        == "governed-historical-learning.v1"
    )
    assert report["archive_scan_count"] == 1
    assert report["price_record_count"] == 123
    assert report["realized_outcome_count"] == 0
    assert report["research_only"] is True
    assert report["execution_authorized"] is False
    assert report["paper_execution_authorized"] is False
    assert report["real_money_authorized"] is False
    assert report["policy_promotion_authorized"] is False
    assert report["performance_claims_authorized"] is False

    cutoff = report["decisions"][0]
    assert cutoff["canonical_cio_invoked"] is True
    assert cutoff["macro_regime"] == "risk_on"
    assert cutoff["prices"]["BTC-USD"] > 0.0
    assert isinstance(cutoff["decisions"], list)
    assert (
        tmp_path / "manifests" / "latest-canonical-replay.json"
    ).exists()


def test_v2_decision_payload_carries_learning_dimensions(tmp_path):
    store = HistoricalStore(tmp_path)
    start = date(2019, 10, 1)
    records = tuple(
        _price_record(start + timedelta(days=index), index)
        for index in range(123)
    )
    store.append(records)
    cutoff = datetime(2020, 1, 31, 23, 59, 59, tzinfo=UTC)
    builder = HistoricalCanonicalContextBuilder(
        minimum_observations=21,
        maximum_candidates=5,
    )
    candidates, contexts, _, _, _ = builder.build(
        records=records,
        cutoff=cutoff,
        state=ReplayPortfolioState(),
        strict_only=True,
    )
    candidate = candidates[0]
    context = contexts[0]
    decision = SimpleNamespace(
        identifier="decision:fixture",
        candidate_identifier=candidate.identifier,
        action=SimpleNamespace(value="watch"),
        final_confidence=0.60,
        expected_return=0.05,
        decision_horizon_days=365,
        recommended_position_weight=None,
        funding_source=None,
        evidence_vetoes=(),
        implementation_blocks=(),
        explanation="Fixture decision",
    )

    payload = EfficientCanonicalHistoricalReplayEngine._decision_payload(
        decision,
        candidate=candidate,
        context=context,
    )

    assert payload["symbol"] == "BTC-USD"
    assert payload["asset_class"] == "crypto"
    assert payload["decision_horizon_days"] == 365
    assert payload["macro_regime"] == "risk_on"
    assert payload["market_regime"] == "positive_trend"
    assert payload["model_versions"] == ["historical-canonical-context.v1"]


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
    assert research["schema_version"] == "canonical-historical-replay.v3"
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
    assert report["runtime_version"] == "single-pass-availability-cursor.v3"
    assert report["decision_cutoff_count"] == 2
    assert report["canonical_cio_invoked_count"] == 2
    visible_counts = [
        item["visible_record_count"] for item in report["decisions"]
    ]
    assert visible_counts == sorted(visible_counts)


def test_realized_outcomes_are_attached_to_prior_cutoff_decisions():
    cutoffs = [
        {
            "cutoff": "2020-01-31T23:59:59+00:00",
            "state": "completed",
            "prices": {"BTC-USD": 100.0},
            "decisions": [{"symbol": "BTC-USD"}],
        },
        {
            "cutoff": "2020-02-29T23:59:59+00:00",
            "state": "completed",
            "prices": {"BTC-USD": 110.0},
            "decisions": [{"symbol": "BTC-USD"}],
        },
    ]

    EfficientCanonicalHistoricalReplayEngine._attach_realized_outcomes(cutoffs)

    first = cutoffs[0]["decisions"][0]
    assert first["realized_horizon_days"] == 29
    assert first["realized_return_to_next_cutoff"] == 0.10
    assert "realized_return_to_next_cutoff" not in cutoffs[1]["decisions"][0]
