from __future__ import annotations

import json
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
from historical_replay.canonical_runtime_v4 import (
    HorizonAlignedCanonicalHistoricalReplayEngine,
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


def test_pre_cio_rejections_remain_distinct_and_calibration_scoped(tmp_path) -> None:
    store = HistoricalStore(tmp_path)
    start = date(2019, 9, 1)
    store.append(
        _price_record(start + timedelta(days=index), index)
        for index in range(183)
    )

    report = HorizonAlignedCanonicalHistoricalReplayEngine(
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

    assert report["schema_version"] == "canonical-historical-replay.v4"
    assert report["runtime_version"] == "single-pass-availability-cursor.v4"
    assert report["learning_observation_count"] >= 2
    assert report["qualification_observation_count"] >= 2
    assert report["next_cutoff_outcome_count"] >= 1
    assert report["realized_outcome_count"] == 0
    assert report["cio_decision_observation_count"] == 0
    assert report["outcome_alignment"] == "decision_horizon"

    observation = report["decisions"][0]["qualification_observations"][0]
    assert observation["decision_stage"] == "pre_cio_qualification"
    assert observation["canonical_cio_decision"] is False
    assert observation["learning_scope"] in {
        "governance_only",
        "decision_calibration",
    }
    assert isinstance(observation["calibration_eligible"], bool)
    assert observation["qualification_reasons"]
    assert observation["next_cutoff_outcome"] == "missed_opportunity"
    assert observation["underlying_return_to_next_cutoff"] > 0.0
    assert observation["realized_return_to_next_cutoff"] < 0.0
    assert "realized_return_at_decision_horizon" not in observation
    assert (tmp_path / "manifests" / "latest-canonical-learning.json").exists()


def test_outcomes_are_measured_at_stated_decision_horizon() -> None:
    start = datetime(2020, 1, 31, 23, 59, 59, tzinfo=UTC)
    cutoffs = []
    for month in range(14):
        cutoff_at = start + timedelta(days=31 * month)
        cutoffs.append(
            {
                "cutoff": cutoff_at.isoformat(),
                "state": "completed",
                "prices": {"BTC-USD": 100.0 + 10.0 * month},
                "decisions": (
                    [
                        {
                            "symbol": "BTC-USD",
                            "action": "no_superior_opportunity",
                            "decision_horizon_days": 365,
                        }
                    ]
                    if month == 0
                    else []
                ),
            }
        )

    HorizonAlignedCanonicalHistoricalReplayEngine._attach_realized_outcomes(cutoffs)

    observation = cutoffs[0]["decisions"][0]
    assert observation["next_cutoff_horizon_days"] == 31
    assert observation["underlying_return_to_next_cutoff"] == pytest.approx(0.10)
    assert observation["realized_return_to_next_cutoff"] == pytest.approx(-0.10)
    assert observation["next_cutoff_outcome"] == "missed_opportunity"
    assert observation["realized_horizon_target_days"] == 365
    assert observation["realized_horizon_days"] >= 365
    assert observation["underlying_return_at_decision_horizon"] > 1.0
    assert observation["realized_return_at_decision_horizon"] < -1.0
    assert observation["realized_outcome"] == "missed_opportunity"


def test_learning_input_excludes_policy_only_and_remaps_horizon_value() -> None:
    report = {
        "schema_version": "canonical-historical-replay.v4",
        "runtime_version": "single-pass-availability-cursor.v4",
        "generated_at": "2026-07-29T00:00:00Z",
        "strict_only": True,
        "governance_only_observation_count": 1,
        "decisions": [
            {
                "state": "completed",
                "decisions": [
                    {
                        "candidate_identifier": "governance-only",
                        "calibration_eligible": False,
                        "realized_return_to_next_cutoff": 0.25,
                    },
                    {
                        "candidate_identifier": "eligible",
                        "calibration_eligible": True,
                        "realized_return_to_next_cutoff": 0.10,
                        "realized_decision_value_at_horizon": -0.20,
                    },
                ],
            }
        ],
    }

    learning = HorizonAlignedCanonicalHistoricalReplayEngine._learning_input_report(
        report
    )

    assert learning["schema_version"] == "canonical-historical-learning-input.v1"
    assert learning["outcome_alignment"] == "decision_horizon"
    assert learning["learning_observation_count"] == 1
    assert learning["governance_only_observation_count"] == 1
    observations = learning["decisions"][0]["decisions"]
    assert [item["candidate_identifier"] for item in observations] == ["eligible"]
    assert observations[0]["realized_return_to_next_cutoff"] == pytest.approx(-0.20)


def test_live_resolver_uses_safe_sidecar_and_reports_governance_exclusions(
    tmp_path,
) -> None:
    generated_at = datetime(2026, 7, 29, 12, tzinfo=UTC)
    payload = {
        "schema_version": "canonical-historical-learning-input.v1",
        "generated_at": generated_at.isoformat(),
        "strict_only": True,
        "outcome_alignment": "decision_horizon",
        "macro_coverage_satisfied": True,
        "certification_ready": True,
        "required_macro_datasets": [
            "series.fedfunds",
            "series.t10y2y",
            "series.vixcls",
        ],
        "macro_excluded_observation_count": 0,
        "governance_only_observation_count": 4,
        "decisions": [
            {
                "state": "completed",
                "macro_regime": "risk_on",
                "decisions": [
                    {
                        "candidate_identifier": "historical:btc",
                        "symbol": "BTC-USD",
                        "asset_class": "crypto",
                        "decision_horizon_days": 365,
                        "macro_regime": "risk_on",
                        "market_regime": "positive_trend",
                        "action": "no_superior_opportunity",
                        "final_confidence": 0.60,
                        "recommended_position_weight": None,
                        "realized_return_to_next_cutoff": -0.20,
                    }
                ],
            }
        ],
    }
    path = tmp_path / "latest-canonical-learning.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    as_of = generated_at + timedelta(seconds=1)

    context = HistoricalLearningResolver(
        path,
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
    assert context.sample_size == 1
    assert context.abstention_rate == 1.0
    assert context.realized_sample_size == 1
    assert context.historical_hit_rate == 0.0
    assert "4 capability-policy-only" in context.summary
    assert context.position_size_multiplier <= 1.0
    assert context.confidence_ceiling <= 1.0
    assert context.may_increase_position_size is False
    assert context.execution_authorized is False
