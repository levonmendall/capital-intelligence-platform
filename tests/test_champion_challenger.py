from datetime import UTC, datetime

import pytest

from evaluation.model_comparison import ModelComparisonEngine
from governance.champion_challenger import (
    ChampionChallengerAuthority,
    PromotionError,
    SQLiteModelGovernanceStore,
)
from governance.model_experiments import ModelExperiment, ShadowModelObservation


AS_OF = datetime(2026, 8, 3, tzinfo=UTC)


def _observation(index: int) -> ShadowModelObservation:
    return ShadowModelObservation(
        identifier=f"obs:{index}",
        experiment_identifier="experiment:1",
        as_of=AS_OF,
        evidence_package_identifier=f"evidence:{index}",
        evidence_cutoff=AS_OF,
        champion_forecast=0.5,
        challenger_forecast=0.7,
        champion_rank=2,
        challenger_rank=1,
        champion_action="HOLD",
        challenger_action="BUY",
        champion_size=0.0,
        challenger_size=0.05,
        expected_benefit=0.02,
        realized_outcome=1.0,
        champion_calibration_loss=0.25,
        challenger_calibration_loss=0.09,
        champion_turnover=0.0,
        challenger_turnover=0.01,
        champion_drawdown=-0.10,
        challenger_drawdown=-0.08,
        out_of_sample=True,
        survivorship_safe=True,
    )


def test_challenger_requires_evidence_and_explicit_promotion(tmp_path):
    experiment = ModelExperiment(
        identifier="experiment:1",
        champion_model_version="champion.v1",
        challenger_model_version="challenger.v2",
        registered_at=AS_OF,
        evidence_contract_version="evidence.v1",
        hypothesis="Improve forecast calibration after costs.",
        minimum_sample_size=3,
    )
    observations = tuple(_observation(index) for index in range(3))
    report = ModelComparisonEngine().compare(
        experiment, observations, as_of=AS_OF
    )
    assert report.promotion_recommended
    decision = ChampionChallengerAuthority().approve(
        experiment,
        report,
        identifier="promotion:1",
        approved_by="model-risk-committee",
        approved_at=AS_OF,
        rationale="Validated point-in-time shadow improvement.",
    )
    assert decision.rollback_model_version == "champion.v1"
    store = SQLiteModelGovernanceStore(tmp_path / "models.sqlite")
    store.append(experiment.identifier, "experiment", experiment.to_dict())
    store.append(decision.identifier, "promotion", decision.to_dict())


def test_short_term_result_cannot_promote():
    experiment = ModelExperiment(
        identifier="experiment:1",
        champion_model_version="champion.v1",
        challenger_model_version="challenger.v2",
        registered_at=AS_OF,
        evidence_contract_version="evidence.v1",
        hypothesis="Improve forecast calibration.",
        minimum_sample_size=20,
    )
    report = ModelComparisonEngine().compare(
        experiment, (_observation(1),), as_of=AS_OF
    )
    assert not report.promotion_recommended
    with pytest.raises(PromotionError):
        ChampionChallengerAuthority().approve(
            experiment,
            report,
            identifier="promotion:bad",
            approved_by="approver",
            approved_at=AS_OF,
            rationale="Too early.",
        )
