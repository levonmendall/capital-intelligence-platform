"""Tests for multi-asset return attribution and living-thesis evidence."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from cio import CandidateAssetClass
from evaluation import (
    AlternativeRealizedReturn,
    EvaluationProcessVerdict,
    MultiAssetEvaluationEventType,
    MultiAssetPointInTimeEvaluator,
    MultiAssetReturnAttribution,
    MultiAssetReturnObservation,
    SQLiteMultiAssetEvaluationStore,
)
from tests.test_point_in_time_evaluation import AS_OF, _cycle
from thesis.multi_asset import MultiAssetThesisEvidenceAdapter


def _global_observation(snapshot) -> MultiAssetReturnObservation:
    return MultiAssetReturnObservation(
        identifier="multi-asset-observation:shel:1y",
        snapshot_identifier=snapshot.identifier,
        decision_identifier=snapshot.decision_identifier,
        thesis_identifier=snapshot.thesis_identifier,
        instrument_identifier="GLOBAL:EQUITY:LSE:SHEL",
        symbol="SHEL",
        asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
        approval_identifier="approval:international-equity:paper-v1",
        evaluation_model_version="international-equity-evaluation.v1",
        base_currency="USD",
        price_currency="GBP",
        decision_at=snapshot.decision_as_of,
        implemented_at=snapshot.decision_as_of + timedelta(days=1),
        horizon_ended_at=snapshot.decision_as_of + timedelta(days=365),
        observed_at=snapshot.decision_as_of + timedelta(days=366),
        knowledge_cutoff=snapshot.decision_as_of + timedelta(days=366, minutes=1),
        decision_local_price=100.0,
        implementation_local_price=102.0,
        horizon_local_price=110.0,
        decision_fx_to_base=1.20,
        implementation_fx_to_base=1.25,
        horizon_fx_to_base=1.30,
        implementation_cost_return=0.002,
        source_identifiers=("outcome:shel:1y",),
        evidence_identifiers=("evidence:shel:prices", "evidence:gbpusd"),
        quote_source_identifiers=(
            "quote:shel:decision",
            "quote:shel:implementation",
            "quote:shel:horizon",
        ),
        fx_source_identifiers=(
            "fx:gbpusd:decision",
            "fx:gbpusd:implementation",
            "fx:gbpusd:horizon",
        ),
    )


def _alternative_returns(snapshot):
    return tuple(
        AlternativeRealizedReturn(
            alternative_identifier=item.identifier,
            realized_return=(0.04 if item.kind.value == "cash" else 0.08),
            source_identifier=f"outcome:{item.identifier}",
        )
        for item in snapshot.alternatives
    )


def test_global_return_decomposes_local_currency_interaction_and_cost(tmp_path) -> None:
    _, _, cycle = _cycle(tmp_path)
    snapshot = replace(cycle.evaluation_snapshots[0], symbol="SHEL")
    observation = _global_observation(snapshot)

    assert observation.implementation_local_return == pytest.approx(
        (110.0 / 102.0) - 1.0
    )
    assert observation.implementation_currency_return == pytest.approx(0.04)
    assert observation.implementation_interaction_return == pytest.approx(
        observation.implementation_local_return * 0.04
    )
    assert observation.implementation_gross_base_return == pytest.approx(
        (110.0 * 1.30) / (102.0 * 1.25) - 1.0
    )
    assert observation.implementation_net_base_return == pytest.approx(
        observation.implementation_gross_base_return - 0.002
    )

    attribution = MultiAssetReturnAttribution.from_observation(
        observation,
        implemented_weight=snapshot.implemented_position_weight,
    )
    assert attribution.gross_base_return == pytest.approx(
        attribution.local_asset_return
        + attribution.currency_return
        + attribution.interaction_return
    )
    assert attribution.net_portfolio_contribution == pytest.approx(
        attribution.local_asset_contribution
        + attribution.currency_contribution
        + attribution.interaction_contribution
        + attribution.implementation_cost_contribution
    )


def test_base_currency_crypto_has_no_currency_or_interaction_return(tmp_path) -> None:
    _, _, cycle = _cycle(tmp_path)
    snapshot = replace(cycle.evaluation_snapshots[0], symbol="BTC-USD")
    observation = replace(
        _global_observation(snapshot),
        identifier="multi-asset-observation:btc:1y",
        instrument_identifier="CRYPTO:COINBASE:BTC-USD:SPOT",
        asset_class=CandidateAssetClass.CRYPTO,
        approval_identifier="approval:crypto:paper-v1",
        evaluation_model_version="crypto-evaluation.v1",
        price_currency="USD",
        decision_local_price=50_000,
        implementation_local_price=50_100,
        horizon_local_price=60_000,
        decision_fx_to_base=1.0,
        implementation_fx_to_base=1.0,
        horizon_fx_to_base=1.0,
        fx_source_identifiers=("fx:usdusd",),
    )

    assert observation.implementation_currency_return == 0.0
    assert observation.implementation_interaction_return == 0.0
    assert observation.implementation_gross_base_return == pytest.approx(
        observation.implementation_local_return
    )


def test_non_base_observation_requires_complete_fx_lineage_and_no_hindsight(
    tmp_path,
) -> None:
    _, _, cycle = _cycle(tmp_path)
    snapshot = replace(cycle.evaluation_snapshots[0], symbol="SHEL")
    observation = _global_observation(snapshot)

    with pytest.raises(ValueError, match="decision, implementation, and horizon FX"):
        replace(observation, fx_source_identifiers=("fx:gbpusd",))
    with pytest.raises(ValueError, match="knowledge_cutoff cannot predate observed_at"):
        replace(
            observation,
            knowledge_cutoff=observation.observed_at - timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="base-currency observations"):
        replace(
            observation,
            price_currency="USD",
            decision_fx_to_base=1.2,
            implementation_fx_to_base=1.2,
            horizon_fx_to_base=1.2,
        )


def test_multi_asset_evaluator_preserves_core_process_and_alternative_authority(
    tmp_path,
) -> None:
    _, _, cycle = _cycle(tmp_path)
    snapshot = replace(cycle.evaluation_snapshots[0], symbol="SHEL")
    observation = _global_observation(snapshot)

    evaluation = MultiAssetPointInTimeEvaluator().evaluate(
        snapshot,
        observation,
        cash_return=0.04,
        benchmark_return=0.10,
        passive_portfolio_return=0.09,
        alternative_returns=_alternative_returns(snapshot),
    )

    assert evaluation.core_evaluation.process_verdict is (
        EvaluationProcessVerdict.DISCIPLINED
    )
    assert evaluation.core_evaluation.snapshot_fingerprint == snapshot.fingerprint
    assert evaluation.attribution.snapshot_identifier == snapshot.identifier
    assert evaluation.attribution.net_portfolio_contribution == pytest.approx(
        snapshot.implemented_position_weight
        * observation.implementation_net_base_return
    )
    assert evaluation.core_evaluation.attribution.implementation_cost == pytest.approx(
        -snapshot.implemented_position_weight
        * observation.implementation_cost_return
    )

    with pytest.raises(ValueError, match="exactly match"):
        MultiAssetPointInTimeEvaluator().evaluate(
            snapshot,
            observation,
            cash_return=0.04,
            benchmark_return=0.10,
            passive_portfolio_return=0.09,
            alternative_returns=_alternative_returns(snapshot)[:-1],
        )


def test_multi_asset_performance_feeds_existing_living_thesis_monitor(tmp_path) -> None:
    _, _, cycle = _cycle(tmp_path)
    snapshot = replace(cycle.evaluation_snapshots[0], symbol="SHEL")
    observation = _global_observation(snapshot)
    thesis = replace(cycle.theses[0], asset="SHEL")

    assessment, update = MultiAssetThesisEvidenceAdapter(
        currency_materiality_threshold=0.02
    ).build(
        thesis,
        observation,
        expected_return=0.09,
        expected_downside=-0.12,
        confidence=0.72,
        strengthened_indicators=("local earnings strengthened",),
        weakened_indicators=("GBP contribution may reverse",),
        triggered_invalidation_conditions=(),
        data_current=True,
        best_replacement_expected_return=0.07,
        next_review_at=observation.observed_at + timedelta(days=30),
        additional_evidence_identifiers=("replacement-screen:1",),
    )

    assert assessment.currency_material is True
    assert assessment.net_base_return == observation.implementation_net_base_return
    assert update.thesis_identifier == thesis.identifier
    assert update.performance_since_approval == observation.implementation_net_base_return
    assert "replacement-screen:1" in update.evidence_identifiers
    assert assessment.observation_identifier == observation.identifier


def test_currency_driven_loss_remains_visible_when_local_asset_is_positive(
    tmp_path,
) -> None:
    _, _, cycle = _cycle(tmp_path)
    snapshot = replace(cycle.evaluation_snapshots[0], symbol="SHEL")
    observation = replace(
        _global_observation(snapshot),
        horizon_local_price=112.0,
        horizon_fx_to_base=1.00,
    )

    assert observation.implementation_local_return > 0.0
    assert observation.implementation_currency_return < 0.0
    assert observation.implementation_net_base_return < 0.0


def test_multi_asset_evaluation_history_is_idempotent_append_only_and_tamper_evident(
    tmp_path: Path,
) -> None:
    _, _, cycle = _cycle(tmp_path)
    snapshot = replace(cycle.evaluation_snapshots[0], symbol="SHEL")
    observation = _global_observation(snapshot)
    attribution = MultiAssetReturnAttribution.from_observation(
        observation,
        implemented_weight=snapshot.implemented_position_weight,
    )
    store = SQLiteMultiAssetEvaluationStore(tmp_path / "multi-asset-evaluation.db")

    assert store.append(
        event_identifier=f"event:{observation.identifier}",
        aggregate_identifier=snapshot.identifier,
        event_type=MultiAssetEvaluationEventType.OBSERVATION,
        occurred_at=observation.observed_at,
        payload=observation.to_dict(),
    ) == 1
    assert store.append(
        event_identifier=f"event:{observation.identifier}",
        aggregate_identifier=snapshot.identifier,
        event_type=MultiAssetEvaluationEventType.OBSERVATION,
        occurred_at=observation.observed_at,
        payload=observation.to_dict(),
    ) == 1
    assert store.append(
        event_identifier=f"event:attribution:{observation.identifier}",
        aggregate_identifier=snapshot.identifier,
        event_type=MultiAssetEvaluationEventType.ATTRIBUTION,
        occurred_at=observation.observed_at,
        payload=attribution.to_dict(),
    ) == 2
    assert len(store.events(snapshot.identifier)) == 2
    assert store.verify_integrity()

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE multi_asset_evaluation_events "
                "SET payload_json='{}' WHERE sequence=1"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM multi_asset_evaluation_events")
