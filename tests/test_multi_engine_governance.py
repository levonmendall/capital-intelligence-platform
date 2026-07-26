"""Unit tests for missing-data, conflict, confidence, and veto governance."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from intelligence.analytical_engine import EngineDataStatus, EngineDirection
from intelligence.governance import (
    DEFAULT_MULTI_ENGINE_GOVERNANCE_POLICY,
    GovernanceStatus,
    MultiEngineGovernor,
    PositiveConclusionCeiling,
    VetoType,
)
from intelligence.governance_store import SQLiteGovernanceStore
from intelligence.normalization import (
    EXPECTED_ENGINE_ORDER,
    MultiEngineNormalizationBundle,
    NormalizedEngineAssessment,
)
from intelligence.synthesis_weights import MultiEngineSynthesizer, SynthesisStatus

AS_OF = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)


def _assessment(
    engine: str,
    opportunity: int = 70,
    *,
    direction: EngineDirection = EngineDirection.EXPANDING,
    status: EngineDataStatus = EngineDataStatus.CURRENT,
    confidence: int = 80,
    quality: int = 90,
    materiality: int = 60,
) -> NormalizedEngineAssessment:
    available = status is not EngineDataStatus.UNAVAILABLE
    return NormalizedEngineAssessment(
        identifier=f"normalized:{engine}:1",
        engine=engine,
        role=engine,
        normalization_policy_version="multi-engine-normalization.v1",
        source_result_identifier=f"source:{engine}" if available else None,
        source_policy_version="engine.v1" if available else None,
        as_of=AS_OF,
        generated_at=AS_OF,
        source_direction=direction if available else EngineDirection.UNAVAILABLE,
        source_score=opportunity if available else None,
        source_confidence=confidence if available else 0,
        opportunity_score=opportunity if available else None,
        risk_score=100 - opportunity if available else None,
        confidence_score=confidence if available else 0,
        data_quality_score=quality if available else 0,
        coverage=1.0 if available else 0.0,
        freshness_days=1 if available else None,
        materiality_score=materiality if available else 0,
        data_status=status,
        supporting_evidence_identifiers=(
            (f"evidence:{engine}",) if available else ()
        ),
        contradictory_evidence_identifiers=(),
        explanation="test assessment",
    )


def _bundle(
    overrides: dict[str, NormalizedEngineAssessment] | None = None,
) -> MultiEngineNormalizationBundle:
    resolved = {engine: _assessment(engine) for engine in EXPECTED_ENGINE_ORDER}
    resolved.update(overrides or {})
    return MultiEngineNormalizationBundle(
        identifier="normalization:governance:1",
        policy_version="multi-engine-normalization.v1",
        as_of=AS_OF,
        generated_at=AS_OF,
        expected_engines=EXPECTED_ENGINE_ORDER,
        assessments=tuple(resolved[engine] for engine in EXPECTED_ENGINE_ORDER),
    )


def _synthesis(bundle: MultiEngineNormalizationBundle):
    return MultiEngineSynthesizer().synthesize(bundle)


def test_default_policy_is_versioned_and_non_transactional() -> None:
    policy = DEFAULT_MULTI_ENGINE_GOVERNANCE_POLICY
    assert policy.version == "multi-engine-governance.v1"
    assert policy.critical_engines == ("credit_cycle", "risk")
    assert policy.hard_minimum_confidence_score < policy.minimum_confidence_score
    assert policy.hard_minimum_data_quality_score < policy.minimum_data_quality_score


def test_cleared_governance_preserves_scores_and_has_no_authority() -> None:
    bundle = _bundle()
    synthesis = _synthesis(bundle)
    result = MultiEngineGovernor().evaluate(bundle, synthesis)
    payload = result.to_dict()
    assert result.status is GovernanceStatus.CLEARED
    assert result.aggregate_opportunity_score == synthesis.aggregate_opportunity_score
    assert result.aggregate_risk_score == synthesis.aggregate_risk_score
    assert result.governed_confidence_score == synthesis.aggregate_confidence_score
    assert result.positive_conclusion_ceiling is PositiveConclusionCeiling.UNRESTRICTED
    assert payload["source_scores_unchanged"] is True
    assert payload["committee_submitted"] is False
    assert payload["market_stance"] is None
    assert payload["unapproved_action_default"] == "no_action"
    assert payload["transaction_authority"] is False


def test_partial_noncritical_evidence_caps_confidence() -> None:
    bundle = _bundle(
        {"valuation": _assessment("valuation", status=EngineDataStatus.UNAVAILABLE)}
    )
    synthesis = _synthesis(bundle)
    result = MultiEngineGovernor().evaluate(bundle, synthesis)
    assert synthesis.status is SynthesisStatus.PARTIAL
    assert result.status is GovernanceStatus.INCOMPLETE
    assert result.confidence_ceiling == 65
    assert result.governed_confidence_score <= 65
    assert result.positive_conclusion_ceiling is PositiveConclusionCeiling.LIMITED


def test_missing_critical_engine_blocks_high_conviction_positive() -> None:
    bundle = _bundle(
        {"risk": _assessment("risk", status=EngineDataStatus.UNAVAILABLE)}
    )
    result = MultiEngineGovernor().evaluate(bundle, _synthesis(bundle))
    assert result.status is GovernanceStatus.INCOMPLETE
    assert result.confidence_ceiling == 45
    assert (
        result.positive_conclusion_ceiling
        is PositiveConclusionCeiling.NO_HIGH_CONVICTION_POSITIVE
    )
    assert any(issue.code == "critical_engine_unavailable" for issue in result.issues)


def test_aggregate_and_engine_disagreement_is_conflicted() -> None:
    overrides = {
        "global_liquidity": _assessment("global_liquidity", 80),
        "business_cycle": _assessment("business_cycle", 80),
        "credit_cycle": _assessment(
            "credit_cycle", 20, direction=EngineDirection.NEUTRAL
        ),
        "risk": _assessment("risk", 20, direction=EngineDirection.NEUTRAL),
    }
    bundle = _bundle(overrides)
    synthesis = replace(
        _synthesis(bundle),
        aggregate_opportunity_score=70,
        aggregate_risk_score=70,
    )
    result = MultiEngineGovernor().evaluate(bundle, synthesis)
    assert result.status is GovernanceStatus.CONFLICTED
    assert result.confidence_ceiling == 55
    assert len(result.supportive_engines) >= 2
    assert len(result.adverse_engines) >= 2
    assert result.requires_human_review is True


def test_credit_veto_blocks_conviction_but_does_not_direct_a_sale() -> None:
    bundle = _bundle(
        {
            "credit_cycle": _assessment(
                "credit_cycle",
                15,
                direction=EngineDirection.STRESSED,
            )
        }
    )
    synthesis = _synthesis(bundle)
    result = MultiEngineGovernor().evaluate(bundle, synthesis)
    assert result.status is GovernanceStatus.VETOED
    assert result.active_vetoes[0].veto_type is VetoType.CREDIT_STRESS
    assert result.aggregate_opportunity_score == synthesis.aggregate_opportunity_score
    assert result.confidence_ceiling == 50
    assert "does not instruct a sale" in result.active_vetoes[0].reason
    assert result.to_dict()["personal_cio_action_affected"] is False


def test_risk_veto_requires_confident_current_evidence() -> None:
    weak = _bundle(
        {
            "risk": _assessment(
                "risk",
                15,
                direction=EngineDirection.STRESSED,
                confidence=40,
            )
        }
    )
    weak_result = MultiEngineGovernor().evaluate(weak, _synthesis(weak))
    assert not weak_result.active_vetoes

    confirmed = _bundle(
        {
            "risk": _assessment(
                "risk",
                15,
                direction=EngineDirection.STRESSED,
                confidence=80,
            )
        }
    )
    confirmed_result = MultiEngineGovernor().evaluate(
        confirmed, _synthesis(confirmed)
    )
    assert confirmed_result.status is GovernanceStatus.VETOED
    assert confirmed_result.active_vetoes[0].veto_type is VetoType.RISK_STRESS


def test_stale_critical_engine_applies_stricter_confidence_ceiling() -> None:
    bundle = _bundle(
        {"risk": _assessment("risk", status=EngineDataStatus.STALE)}
    )
    result = MultiEngineGovernor().evaluate(bundle, _synthesis(bundle))
    assert result.status is GovernanceStatus.STALE
    assert result.stale_engines == ("risk",)
    assert result.confidence_ceiling == 45
    assert (
        result.positive_conclusion_ceiling
        is PositiveConclusionCeiling.NO_HIGH_CONVICTION_POSITIVE
    )


def test_insufficient_synthesis_makes_decision_unavailable() -> None:
    unavailable = {
        engine: _assessment(engine, status=EngineDataStatus.UNAVAILABLE)
        for engine in ("market_breadth", "valuation", "technical_momentum")
    }
    bundle = _bundle(unavailable)
    synthesis = _synthesis(bundle)
    assert synthesis.status is SynthesisStatus.INSUFFICIENT_EVIDENCE
    result = MultiEngineGovernor().evaluate(bundle, synthesis)
    assert result.status is GovernanceStatus.DECISION_UNAVAILABLE
    assert result.decision_available is False
    assert result.committee_submission_eligible is False
    assert result.governed_confidence_score is None


def test_policy_rejects_hard_minimum_above_warning_minimum() -> None:
    policy = DEFAULT_MULTI_ENGINE_GOVERNANCE_POLICY
    with pytest.raises(ValueError, match="hard confidence"):
        replace(
            policy,
            version="invalid.v1",
            hard_minimum_confidence_score=60,
        )


def test_store_is_append_only_and_retry_idempotent(tmp_path) -> None:
    store = SQLiteGovernanceStore(tmp_path / "analytical_engines.db")
    governor = MultiEngineGovernor()
    bundle = _bundle()
    result = governor.evaluate(bundle, _synthesis(bundle))
    store.append_policy(governor.policy)
    store.append_policy(governor.policy)
    store.append(result)
    store.append(result)
    assert store.latest_policy() == governor.policy
    assert store.latest() == result
    assert store.history(limit=10) == (result,)
