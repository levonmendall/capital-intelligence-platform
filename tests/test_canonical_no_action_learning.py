from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
    HistoricalLearningResolver,
    HistoricalLearningStatus,
)
from historical_replay.canonical import HistoricalCanonicalContextBuilder
from historical_replay.canonical_runtime import (
    EfficientCanonicalHistoricalReplayEngine,
)
from historical_replay.models import HistoricalRecord
from historical_replay.store import HistoricalStore

UTC = timezone.utc


def _price_record(day: date, index: int) -> HistoricalRecord:
    observed = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return HistoricalRecord(
        source="fixture",
        dataset="daily_ohlcv.btc-usd",
        observed_at=observed,
        available_at=observed + timedelta(hours=1),
        retrieved_at="2026-07-29T00:00:00Z",
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


def _live_candidate(as_of: datetime) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        identifier="candidate:btc-usd:live",
        as_of=as_of,
        schema_version="candidate.v1",
        instrument=CandidateInstrument(
            instrument_id="instrument:btc-usd",
            symbol="BTC-USD",
            name="Bitcoin",
            asset_class=CandidateAssetClass.CRYPTO,
            venue="COINBASE",
            country_code="XX",
            average_daily_dollar_volume=1_000_000_000.0,
            data_age_hours=0.1,
            analytical_coverage=1.0,
            security_master_snapshot_identifier="security-master:now",
            security_master_record_identifiers=("security-master:btc-usd",),
            instrument_type="spot_crypto",
        ),
        current_price=100.0,
        decision_horizon_days=365,
        base_case_return=0.10,
        bull_case_return=0.25,
        bear_case_return=-0.20,
        base_case_probability=0.50,
        bull_case_probability=0.25,
        bear_case_probability=0.25,
        estimated_fair_value=110.0,
        expected_upside=0.25,
        expected_downside=-0.20,
        probability_of_success=0.60,
        primary_catalysts=("adoption",),
        key_risks=("drawdown",),
        critical_assumptions=("liquidity persists",),
        invalidation_conditions=("trend breaks",),
        supporting_evidence=("current evidence",),
        contradictory_evidence=(),
        evidence_quality=EvidenceQuality(0.9, 0.9, 0.9, 0.8, 0.8, 0.9),
        liquidity_score=1.0,
        transaction_cost_bps=5.0,
        slippage_bps=5.0,
        opportunity_cost_return=0.04,
        expected_portfolio_contribution=0.01,
        current_portfolio_weight=0.0,
        maximum_position_weight=0.10,
        monitoring_indicators=("trend",),
        review_at=as_of + timedelta(days=30),
        evidence_identifiers=("evidence:current",),
        model_versions=("model:v1",),
    )


def test_pre_cio_rejections_become_governed_learning_observations(tmp_path) -> None:
    store = HistoricalStore(tmp_path)
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

    assert report["schema_version"] == "canonical-historical-replay.v3"
    assert report["runtime_version"] == "single-pass-availability-cursor.v3"
    assert report["learning_observation_count"] >= 2
    assert report["qualification_observation_count"] >= 2
    assert report["realized_outcome_count"] >= 1
    assert report["cio_decision_observation_count"] == 0

    first = report["decisions"][0]
    assert first["decision_count"] == 0
    assert first["qualification_rejection_count"] >= 1
    observation = first["qualification_observations"][0]
    assert observation["decision_stage"] == "pre_cio_qualification"
    assert observation["canonical_cio_decision"] is False
    assert observation["action"] in {
        "insufficient_evidence",
        "no_superior_opportunity",
    }
    assert observation["qualification_reasons"]
    assert observation["realized_outcome"] == "missed_opportunity"
    assert observation["underlying_return_to_next_cutoff"] > 0.0
    assert observation["realized_return_to_next_cutoff"] < 0.0


def test_realized_outcomes_value_abstention_and_support_correctly() -> None:
    cutoffs = [
        {
            "cutoff": "2020-01-31T23:59:59+00:00",
            "state": "completed",
            "prices": {"BTC-USD": 100.0, "ETH-USD": 100.0},
            "decisions": [
                {"symbol": "BTC-USD", "action": "no_superior_opportunity"},
                {"symbol": "ETH-USD", "action": "buy"},
            ],
        },
        {
            "cutoff": "2020-02-29T23:59:59+00:00",
            "state": "completed",
            "prices": {"BTC-USD": 110.0, "ETH-USD": 110.0},
            "decisions": [],
        },
    ]

    EfficientCanonicalHistoricalReplayEngine._attach_realized_outcomes(cutoffs)

    abstention, support = cutoffs[0]["decisions"]
    assert abstention["underlying_return_to_next_cutoff"] == pytest.approx(0.10)
    assert abstention["realized_return_to_next_cutoff"] == pytest.approx(-0.10)
    assert abstention["realized_outcome"] == "missed_opportunity"
    assert support["underlying_return_to_next_cutoff"] == pytest.approx(0.10)
    assert support["realized_return_to_next_cutoff"] == pytest.approx(0.10)
    assert support["realized_outcome"] == "supported_gain"


def test_live_resolver_consumes_pre_cio_no_action_history(tmp_path) -> None:
    store = HistoricalStore(tmp_path)
    start = date(2019, 9, 1)
    store.append(
        _price_record(start + timedelta(days=index), index)
        for index in range(183)
    )
    report = EfficientCanonicalHistoricalReplayEngine(
        store,
        builder=HistoricalCanonicalContextBuilder(minimum_observations=21),
    ).run(
        start=date(2020, 1, 1),
        end=date(2020, 2, 29),
        strict_only=True,
    )
    generated_at = datetime.fromisoformat(
        report["generated_at"].replace("Z", "+00:00")
    )
    as_of = generated_at + timedelta(seconds=1)

    context = HistoricalLearningResolver(
        tmp_path / "manifests" / "latest-canonical-replay.json",
        minimum_sample_size=1,
    ).resolve(
        _live_candidate(as_of),
        as_of=as_of,
        macro_regime="risk_on",
        market_regime="positive_trend",
    )

    assert context.status in {
        HistoricalLearningStatus.AVAILABLE,
        HistoricalLearningStatus.LIMITED,
    }
    assert context.sample_size >= 1
    assert context.abstention_rate == 1.0
    assert context.realized_sample_size >= 1
    assert context.historical_hit_rate == 0.0
    assert context.position_size_multiplier <= 1.0
    assert context.confidence_ceiling <= 1.0
    assert context.may_increase_position_size is False
    assert context.execution_authorized is False
