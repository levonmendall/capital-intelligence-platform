"""Unit tests for versioned multi-engine synthesis weights."""

from datetime import datetime, timezone

import pytest

from intelligence.analytical_engine import EngineDataStatus, EngineDirection
from intelligence.normalization import (
    EXPECTED_ENGINE_ORDER,
    MultiEngineNormalizationBundle,
    NormalizedEngineAssessment,
)
from intelligence.synthesis_store import SQLiteSynthesisStore
from intelligence.synthesis_weights import (
    BASIS_POINTS,
    DEFAULT_SYNTHESIS_WEIGHT_POLICY,
    EngineSynthesisWeight,
    MissingWeightPolicy,
    MultiEngineSynthesizer,
    SynthesisStatus,
    SynthesisWeightPolicy,
)

AS_OF = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)


def _assessment(
    engine: str,
    score: int,
    *,
    available: bool = True,
) -> NormalizedEngineAssessment:
    return NormalizedEngineAssessment(
        identifier=f"normalized:{engine}:1",
        engine=engine,
        role=engine,
        normalization_policy_version="multi-engine-normalization.v1",
        source_result_identifier=f"source:{engine}" if available else None,
        source_policy_version="engine.v1" if available else None,
        as_of=AS_OF,
        generated_at=AS_OF,
        source_direction=(
            EngineDirection.EXPANDING
            if available
            else EngineDirection.UNAVAILABLE
        ),
        source_score=score if available else None,
        source_confidence=80 if available else 0,
        opportunity_score=score if available else None,
        risk_score=100 - score if available else None,
        confidence_score=80 if available else 0,
        data_quality_score=90 if available else 0,
        coverage=1.0 if available else 0.0,
        freshness_days=1 if available else None,
        materiality_score=60 if available else 0,
        data_status=(
            EngineDataStatus.CURRENT
            if available
            else EngineDataStatus.UNAVAILABLE
        ),
        supporting_evidence_identifiers=(
            (f"evidence:{engine}",) if available else ()
        ),
        contradictory_evidence_identifiers=(),
        explanation="test assessment",
    )


def _bundle(
    *,
    unavailable: tuple[str, ...] = (),
) -> MultiEngineNormalizationBundle:
    scores = dict(zip(EXPECTED_ENGINE_ORDER, (80, 70, 60, 50, 40, 30, 20)))
    return MultiEngineNormalizationBundle(
        identifier="normalization:1",
        policy_version="multi-engine-normalization.v1",
        as_of=AS_OF,
        generated_at=AS_OF,
        expected_engines=EXPECTED_ENGINE_ORDER,
        assessments=tuple(
            _assessment(
                engine,
                scores[engine],
                available=engine not in unavailable,
            )
            for engine in EXPECTED_ENGINE_ORDER
        ),
    )


def test_default_policy_has_fixed_complete_weights() -> None:
    policy = DEFAULT_SYNTHESIS_WEIGHT_POLICY
    assert tuple(item.engine for item in policy.weights) == EXPECTED_ENGINE_ORDER
    assert sum(item.opportunity_weight_bps for item in policy.weights) == BASIS_POINTS
    assert sum(item.risk_weight_bps for item in policy.weights) == BASIS_POINTS
    assert sum(item.evidence_weight_bps for item in policy.weights) == BASIS_POINTS
    assert policy.regime_sensitive is False
    assert policy.missing_weight_policy is MissingWeightPolicy.PRESERVE_UNALLOCATED


def test_complete_synthesis_produces_separate_scores_without_authority() -> None:
    result = MultiEngineSynthesizer().synthesize(_bundle())
    payload = result.to_dict()
    assert result.status is SynthesisStatus.COMPLETE
    assert result.aggregate_opportunity_score == 56
    assert result.aggregate_risk_score == 55
    assert result.aggregate_confidence_score == 80
    assert result.aggregate_data_quality_score == 90
    assert payload["weights_applied"] is True
    assert payload["missing_weights_redistributed"] is False
    assert payload["veto_policy_applied"] is False
    assert payload["committee_submitted"] is False
    assert payload["market_stance"] is None
    assert payload["personal_cio_action_affected"] is False
    assert payload["capital_intelligence_score_affected"] is False


def test_partial_synthesis_discloses_unallocated_weight() -> None:
    result = MultiEngineSynthesizer().synthesize(
        _bundle(unavailable=("valuation",))
    )
    payload = result.to_dict()
    assert result.status is SynthesisStatus.PARTIAL
    assert result.available_engine_count == 6
    assert result.missing_engines == ("valuation",)
    assert payload["unallocated_opportunity_weight_bps"] == 1000
    assert payload["unallocated_risk_weight_bps"] == 1000
    assert payload["unallocated_evidence_weight_bps"] == 1000
    assert result.aggregate_confidence_score == 72
    assert result.aggregate_data_quality_score == 81


def test_below_threshold_is_insufficient_and_publishes_no_scores() -> None:
    result = MultiEngineSynthesizer().synthesize(
        _bundle(
            unavailable=(
                "market_breadth",
                "valuation",
                "technical_momentum",
            )
        )
    )
    assert result.status is SynthesisStatus.INSUFFICIENT_EVIDENCE
    assert result.aggregate_opportunity_score is None
    assert result.aggregate_risk_score is None
    assert result.aggregate_confidence_score is None
    assert result.aggregate_data_quality_score is None
    assert result.insufficiency_reasons


def test_policy_rejects_weight_totals_that_do_not_equal_one() -> None:
    weights = list(DEFAULT_SYNTHESIS_WEIGHT_POLICY.weights)
    first = weights[0]
    weights[0] = EngineSynthesisWeight(
        engine=first.engine,
        opportunity_weight_bps=first.opportunity_weight_bps - 1,
        risk_weight_bps=first.risk_weight_bps,
        evidence_weight_bps=first.evidence_weight_bps,
        rationale=first.rationale,
    )
    with pytest.raises(ValueError, match="must sum"):
        SynthesisWeightPolicy(
            version="invalid.v1",
            published_at=AS_OF,
            weights=tuple(weights),
            minimum_opportunity_coverage_bps=7000,
            minimum_risk_coverage_bps=7000,
            minimum_evidence_coverage_bps=7000,
            minimum_available_engines=5,
            missing_weight_policy=MissingWeightPolicy.PRESERVE_UNALLOCATED,
            regime_sensitive=False,
            change_rationale="invalid fixture",
        )


def test_store_is_append_only_and_retry_idempotent(tmp_path) -> None:
    store = SQLiteSynthesisStore(tmp_path / "analytical_engines.db")
    synthesizer = MultiEngineSynthesizer()
    result = synthesizer.synthesize(_bundle())
    store.append_policy(synthesizer.policy)
    store.append_policy(synthesizer.policy)
    store.append(result)
    store.append(result)
    assert store.latest() == result
    assert store.latest_policy() == synthesizer.policy
    assert store.history(limit=10) == (result,)
