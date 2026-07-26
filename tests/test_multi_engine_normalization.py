"""Contract tests for multi-engine normalization."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from intelligence.analytical_engine import (
    AnalyticalEngineResult,
    EngineDataStatus,
    EngineDirection,
    EngineEvidence,
)
from intelligence.normalization import (
    ENGINE_NORMALIZATION_POLICIES,
    EXPECTED_ENGINE_ORDER,
    EngineNormalizationPolicy,
    MultiEngineNormalizer,
    ScoreOrientation,
)
from intelligence.normalization_store import SQLiteNormalizationStore


AS_OF = datetime(2026, 1, 31, 21, tzinfo=timezone.utc)


def _evidence(
    identifier: str,
    signal: float,
    *,
    quality: str = "live",
    released_days_ago: int = 1,
) -> EngineEvidence:
    released_at = AS_OF - timedelta(days=released_days_ago)
    return EngineEvidence(
        identifier=identifier,
        component="fixture",
        indicator="Fixture indicator",
        provider="FIXTURE",
        series_identifier=f"fixture:{identifier}",
        observation_date=released_at.date(),
        released_at=released_at,
        retrieved_at=released_at,
        quality_state=quality,
        signal_score=signal,
        weighted_contribution=max(-1.0, min(1.0, signal / 2)),
        explanation="Fixture evidence.",
    )


def _result(
    engine: str,
    *,
    score: int = 75,
    direction: EngineDirection = EngineDirection.EXPANDING,
    confidence: int = 80,
    coverage: float = 1.0,
    status: EngineDataStatus = EngineDataStatus.CURRENT,
    evidence: tuple[EngineEvidence, ...] | None = None,
    as_of: datetime = AS_OF,
) -> AnalyticalEngineResult:
    if evidence is None:
        evidence = (
            _evidence(f"{engine}:support", 0.7),
            _evidence(f"{engine}:dissent", -0.25),
        )
    return AnalyticalEngineResult(
        identifier=f"{engine}:{as_of.isoformat()}",
        engine=engine,
        scope=f"{engine} fixture",
        policy_version=f"{engine}-policy.v1",
        as_of=as_of,
        generated_at=as_of,
        direction=direction,
        score=score,
        confidence=confidence,
        coverage=coverage,
        data_status=status,
        summary=f"{engine} summary",
        explanation=f"{engine} explanation",
        risks=("Fixture risk.",),
        transmission_channels=("Fixture transmission.",),
        review_conditions=("Fixture review condition.",),
        evidence=evidence,
    )


def _all_results() -> tuple[AnalyticalEngineResult, ...]:
    return tuple(_result(engine) for engine in EXPECTED_ENGINE_ORDER)


def test_normalization_produces_seven_assessments_without_aggregation() -> None:
    bundle = MultiEngineNormalizer().normalize(_all_results(), as_of=AS_OF)
    payload = bundle.to_dict()

    assert tuple(item.engine for item in bundle.assessments) == EXPECTED_ENGINE_ORDER
    assert bundle.available_engine_count == 7
    assert bundle.unavailable_engines == ()
    assert all(item.opportunity_score is not None for item in bundle.assessments)
    assert all(item.risk_score is not None for item in bundle.assessments)
    assert all(
        item.opportunity_score + item.risk_score == 100
        for item in bundle.assessments
    )
    assert payload["aggregation_status"] == "not_performed"
    assert payload["weights_applied"] is False
    assert payload["veto_policy_applied"] is False
    assert payload["committee_submitted"] is False
    assert payload["market_stance"] is None
    assert payload["aggregate_opportunity_score"] is None
    assert payload["aggregate_risk_score"] is None


def test_every_engine_has_an_explicit_semantic_policy() -> None:
    assert tuple(ENGINE_NORMALIZATION_POLICIES) == EXPECTED_ENGINE_ORDER
    assert all(
        policy.score_orientation is ScoreOrientation.HIGHER_IS_SUPPORTIVE
        for policy in ENGINE_NORMALIZATION_POLICIES.values()
    )
    assert len({policy.role for policy in ENGINE_NORMALIZATION_POLICIES.values()}) == 7


def test_source_score_is_not_blindly_copied() -> None:
    result = _result(
        "credit_cycle",
        score=70,
        direction=EngineDirection.CONTRACTING,
    )
    assessment = MultiEngineNormalizer().normalize(
        (result,),
        as_of=AS_OF,
    ).assessments[2]

    assert assessment.source_score == 70
    assert assessment.opportunity_score != result.score
    assert assessment.risk_score == 100 - assessment.opportunity_score
    assert assessment.source_direction is EngineDirection.CONTRACTING


def test_custom_lower_is_supportive_policy_is_inverted_explicitly() -> None:
    policy = EngineNormalizationPolicy(
        engine="custom",
        role="custom_role",
        score_orientation=ScoreOrientation.LOWER_IS_SUPPORTIVE,
        opportunity_interpretation="Lower native values are more supportive.",
        risk_interpretation="Higher native values indicate greater pressure.",
    )
    result = _result("custom", score=20)
    assessment = MultiEngineNormalizer((policy,)).normalize(
        (result,),
        as_of=AS_OF,
    ).assessments[0]

    assert assessment.opportunity_score is not None
    assert assessment.opportunity_score > 70
    assert assessment.risk_score is not None
    assert assessment.risk_score < 30


def test_missing_engine_is_explicitly_unavailable_without_imputation() -> None:
    bundle = MultiEngineNormalizer().normalize(
        (_result("global_liquidity"),),
        as_of=AS_OF,
    )
    missing = next(
        item for item in bundle.assessments if item.engine == "business_cycle"
    )

    assert bundle.available_engine_count == 1
    assert missing.data_status is EngineDataStatus.UNAVAILABLE
    assert missing.source_result_identifier is None
    assert missing.opportunity_score is None
    assert missing.risk_score is None
    assert missing.confidence_score == 0
    assert missing.data_quality_score == 0
    assert missing.materiality_score == 0


def test_explicit_unavailable_result_remains_unscored() -> None:
    result = _result(
        "risk",
        score=0,
        direction=EngineDirection.UNAVAILABLE,
        confidence=0,
        coverage=0.0,
        status=EngineDataStatus.UNAVAILABLE,
        evidence=(),
    )
    assessment = MultiEngineNormalizer().normalize(
        (result,),
        as_of=AS_OF,
    ).assessments[-1]

    assert assessment.source_result_identifier == result.identifier
    assert assessment.opportunity_score is None
    assert assessment.risk_score is None
    assert assessment.data_status is EngineDataStatus.UNAVAILABLE


def test_data_quality_and_confidence_penalize_stale_fallback_evidence() -> None:
    current = MultiEngineNormalizer().normalize(
        (_result("risk"),),
        as_of=AS_OF,
    ).assessments[-1]
    stale = MultiEngineNormalizer().normalize(
        (
            _result(
                "risk",
                status=EngineDataStatus.STALE,
                evidence=(
                    _evidence(
                        "risk:stale",
                        0.7,
                        quality="fallback",
                        released_days_ago=30,
                    ),
                ),
            ),
        ),
        as_of=AS_OF,
    ).assessments[-1]

    assert stale.data_quality_score < current.data_quality_score
    assert stale.confidence_score < current.confidence_score
    assert stale.freshness_days == 30


def test_supporting_and_contradictory_evidence_are_retained() -> None:
    result = _result(
        "market_breadth",
        evidence=(
            _evidence("breadth:positive", 0.8),
            _evidence("breadth:negative", -0.6),
            _evidence("breadth:flat", 0.0),
        ),
    )
    assessment = MultiEngineNormalizer().normalize(
        (result,),
        as_of=AS_OF,
    ).assessments[3]

    assert assessment.supporting_evidence_identifiers == ("breadth:positive",)
    assert assessment.contradictory_evidence_identifiers == ("breadth:negative",)


def test_future_engine_result_is_rejected() -> None:
    future = AS_OF + timedelta(days=1)
    with pytest.raises(ValueError, match="future"):
        MultiEngineNormalizer().normalize(
            (_result("risk", as_of=future),),
            as_of=AS_OF,
        )


def test_unknown_and_duplicate_engines_are_rejected() -> None:
    with pytest.raises(ValueError, match="no normalization policy"):
        MultiEngineNormalizer().normalize((_result("unknown"),), as_of=AS_OF)
    duplicate = _result("risk")
    with pytest.raises(ValueError, match="duplicate"):
        MultiEngineNormalizer().normalize(
            (duplicate, duplicate),
            as_of=AS_OF,
        )


def test_normalization_store_is_idempotent_and_append_only(tmp_path) -> None:
    path = tmp_path / "analytical_engines.db"
    store = SQLiteNormalizationStore(path)
    bundle = MultiEngineNormalizer().normalize(_all_results(), as_of=AS_OF)

    store.append(bundle)
    store.append(bundle)

    assert store.latest() == bundle
    assert store.history(limit=10) == (bundle,)
    assert store.readiness()[0] is True

    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE multi_engine_normalization_bundles SET policy_version = 'x'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM multi_engine_normalization_bundles")


def test_store_rejects_different_content_for_same_timestamp(tmp_path) -> None:
    store = SQLiteNormalizationStore(tmp_path / "analytical_engines.db")
    first = MultiEngineNormalizer().normalize(_all_results(), as_of=AS_OF)
    changed_results = list(_all_results())
    changed_results[0] = _result("global_liquidity", score=20)
    second = MultiEngineNormalizer().normalize(changed_results, as_of=AS_OF)

    store.append(first)
    with pytest.raises(ValueError, match="different content"):
        store.append(second)


def test_read_only_store_handles_pre_normalization_database(tmp_path) -> None:
    path = tmp_path / "analytical_engines.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (identifier TEXT)")

    store = SQLiteNormalizationStore(path, read_only=True)

    assert store.latest() is None
    assert store.history() == ()
    ready, detail = store.readiness()
    assert ready is True
    assert "not been created" in detail
