from datetime import UTC, datetime

from intelligence.structural_breaks import (
    NoveltyDimension,
    NoveltyObservation,
    StructuralBreakDetector,
    StructuralBreakState,
)


AS_OF = datetime(2026, 8, 3, tzinfo=UTC)


def _observation(
    dimension: NoveltyDimension,
    distance: float,
    *,
    health: float = 1.0,
) -> NoveltyObservation:
    return NoveltyObservation(
        dimension=dimension,
        standardized_distance=distance,
        reliability=0.9,
        independent_source_count=2,
        provider_health=health,
        evidence_identifiers=(f"evidence:{dimension.value}",),
        detail=f"{dimension.value} is outside the validated range.",
    )


def test_single_extreme_feature_does_not_define_break():
    result = StructuralBreakDetector().assess(
        (_observation(NoveltyDimension.VALUATION, 5.0),),
        identifier="break:single",
        as_of=AS_OF,
    )
    assert result.state is StructuralBreakState.NORMAL
    assert not result.controls.force_cash
    assert not result.controls.force_liquidation


def test_multidimensional_break_caps_confidence_without_forcing_cash():
    result = StructuralBreakDetector().assess(
        (
            _observation(NoveltyDimension.CORRELATION, 4.0),
            _observation(NoveltyDimension.VOLATILITY_LIQUIDITY, 4.5),
            _observation(NoveltyDimension.TRAINING_RANGE, 4.0),
        ),
        identifier="break:multi",
        as_of=AS_OF,
    )
    assert result.state is StructuralBreakState.CONFIRMED_BREAK
    assert result.controls.confidence_ceiling == 0.60
    assert not result.controls.force_cash


def test_provider_problem_is_not_mislabeled_as_market_break():
    result = StructuralBreakDetector().assess(
        (
            NoveltyObservation(
                dimension=NoveltyDimension.PROVIDER_DISAGREEMENT,
                standardized_distance=5.0,
                reliability=1.0,
                independent_source_count=1,
                provider_health=0.1,
                evidence_identifiers=("provider:outage",),
                detail="One provider is returning inconsistent observations.",
            ),
        ),
        identifier="break:provider",
        as_of=AS_OF,
    )
    assert result.state is StructuralBreakState.PROVIDER_DEGRADATION
