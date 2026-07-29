from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
    HistoricalLearningContext,
    HistoricalLearningResolver,
    HistoricalLearningStatus,
)

UTC = timezone.utc


def _candidate(as_of: datetime) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        identifier="candidate:spy",
        as_of=as_of,
        schema_version="candidate.v1",
        instrument=CandidateInstrument(
            instrument_id="instrument:spy",
            symbol="SPY",
            name="SPDR S&P 500 ETF",
            asset_class=CandidateAssetClass.US_ETF,
            venue="ARCX",
            country_code="US",
            average_daily_dollar_volume=1_000_000_000.0,
            data_age_hours=0.1,
            analytical_coverage=1.0,
            security_master_snapshot_identifier="security-master:now",
            security_master_record_identifiers=("security-master:spy",),
            instrument_type="etf",
        ),
        current_price=500.0,
        decision_horizon_days=365,
        base_case_return=0.10,
        bull_case_return=0.20,
        bear_case_return=-0.15,
        base_case_probability=0.50,
        bull_case_probability=0.25,
        bear_case_probability=0.25,
        estimated_fair_value=550.0,
        expected_upside=0.20,
        expected_downside=-0.15,
        probability_of_success=0.65,
        primary_catalysts=("earnings growth",),
        key_risks=("recession",),
        critical_assumptions=("growth persists",),
        invalidation_conditions=("trend breaks",),
        supporting_evidence=("current evidence",),
        contradictory_evidence=(),
        evidence_quality=EvidenceQuality(0.9, 0.9, 0.9, 0.8, 0.8, 0.9),
        liquidity_score=1.0,
        transaction_cost_bps=1.0,
        slippage_bps=1.0,
        opportunity_cost_return=0.04,
        expected_portfolio_contribution=0.01,
        current_portfolio_weight=0.0,
        maximum_position_weight=0.10,
        monitoring_indicators=("trend",),
        review_at=as_of + timedelta(days=30),
        evidence_identifiers=("evidence:current",),
        model_versions=("model:v1",),
    )


def _manifest(generated_at: datetime) -> dict[str, object]:
    decisions = []
    realized = (0.03, 0.02, -0.01, 0.04, -0.02, 0.01)
    for month, outcome in enumerate(realized, start=1):
        decisions.append(
            {
                "cutoff": f"2026-{month:02d}-28T23:59:59+00:00",
                "state": "completed",
                "canonical_cio_invoked": True,
                "macro_regime": "mixed",
                "decisions": [
                    {
                        "candidate_identifier": f"historical:2026-{month:02d}-28:SPY",
                        "symbol": "SPY",
                        "asset_class": "us_etf",
                        "macro_regime": "mixed",
                        "market_regime": "positive_trend",
                        "decision_horizon_days": 365,
                        "action": "buy" if month < 5 else "watch",
                        "final_confidence": 0.80,
                        "recommended_position_weight": 0.10,
                        "realized_return_to_next_cutoff": outcome,
                    }
                ],
            }
        )
    return {
        "schema_version": "canonical-historical-replay.v2",
        "generated_at": generated_at.isoformat(),
        "strict_only": False,
        "decisions": decisions,
    }


def test_resolver_attaches_restrictive_outcome_and_regime_context(tmp_path) -> None:
    as_of = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)
    manifest = tmp_path / "latest-canonical-replay.json"
    manifest.write_text(
        json.dumps(_manifest(as_of - timedelta(hours=1))),
        encoding="utf-8",
    )
    context = HistoricalLearningResolver(manifest).resolve(
        _candidate(as_of),
        as_of=as_of,
        macro_regime="mixed",
        market_regime="positive_trend",
    )

    assert context.status is HistoricalLearningStatus.AVAILABLE
    assert context.sample_size == 6
    assert context.exact_symbol_sample_size == 6
    assert context.regime_matched_sample_size == 6
    assert context.horizon_matched_sample_size == 6
    assert context.realized_sample_size == 6
    assert context.historical_hit_rate == pytest.approx(4 / 6)
    assert context.median_realized_return > 0.0
    assert context.worst_realized_return == -0.02
    assert 0.0 < context.position_size_multiplier <= 1.0
    assert 0.0 < context.confidence_ceiling <= 1.0
    assert context.subordinate_to_current_evidence is True
    assert context.may_increase_expected_return is False
    assert context.may_increase_confidence is False
    assert context.may_increase_position_size is False
    assert context.execution_authorized is False
    assert context.policy_promotion_authorized is False


def test_future_manifest_is_rejected(tmp_path) -> None:
    as_of = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)
    manifest = tmp_path / "latest-canonical-replay.json"
    manifest.write_text(
        json.dumps(_manifest(as_of + timedelta(seconds=1))),
        encoding="utf-8",
    )
    context = HistoricalLearningResolver(manifest).resolve(
        _candidate(as_of),
        as_of=as_of,
        macro_regime="mixed",
        market_regime="positive_trend",
    )

    assert context.status is HistoricalLearningStatus.UNAVAILABLE
    assert context.position_size_multiplier == 1.0
    assert "after the decision timestamp" in context.summary


def test_historical_learning_cannot_grant_positive_authority() -> None:
    as_of = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="cannot strengthen"):
        HistoricalLearningContext(
            candidate_identifier="candidate:spy",
            as_of=as_of,
            status=HistoricalLearningStatus.AVAILABLE,
            source_manifest_identifier="manifest:1",
            sample_size=12,
            exact_symbol_sample_size=12,
            regime_matched_sample_size=12,
            horizon_matched_sample_size=12,
            realized_sample_size=12,
            strict_replay=True,
            support_rate=1.0,
            abstention_rate=0.0,
            historical_hit_rate=1.0,
            median_historical_confidence=0.9,
            median_historical_position_weight=0.1,
            median_realized_return=0.02,
            worst_realized_return=-0.05,
            position_size_multiplier=1.0,
            confidence_ceiling=1.0,
            summary="invalid authority test",
            limitations=(),
            evidence_identifiers=("manifest:1",),
            may_increase_position_size=True,
        )


def test_live_cycle_committee_and_cio_apply_historical_controls() -> None:
    cycle_source = open("application/cio_cycle.py", encoding="utf-8").read()
    specialist_source = open("committee/specialists.py", encoding="utf-8").read()
    cio_source = open("cio/service.py", encoding="utf-8").read()
    persistence_source = open("cio/persistence.py", encoding="utf-8").read()
    replay_source = open("historical_replay/canonical.py", encoding="utf-8").read()

    assert "historical_learning_resolver.resolve" in cycle_source
    assert "historical_learning=historical_learning" in cycle_source
    assert "self._historically_calibrate" in specialist_source
    assert "learning.confidence_ceiling" in specialist_source
    assert "assessment_cap * historical_learning.position_size_multiplier" in cio_source
    assert "specialists.historical_learning.position_size_multiplier" in cio_source
    assert "historical_learning.confidence_ceiling" in cio_source
    assert '"historical_learning": packet.historical_learning.as_dict()' in persistence_source
    assert "realized_return_to_next_cutoff" in replay_source
    assert '"market_regime": context.market.market_regime' in replay_source
