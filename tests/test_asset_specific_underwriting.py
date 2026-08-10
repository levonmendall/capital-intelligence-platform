from datetime import datetime, timezone

from cio.models import CandidateAssetClass
from intelligence.asset_specific_underwriting import (
    AssetSpecificUnderwritingEngine,
    UnderwritingDriverObservation,
)


def test_incomplete_fixed_income_underwriting_remains_shadow() -> None:
    now = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    result = AssetSpecificUnderwritingEngine().assess(
        asset_class=CandidateAssetClass.FIXED_INCOME,
        as_of=now,
        observations=(
            UnderwritingDriverObservation("yield", now, 0.04, 0.9, ("yield:1",)),
            UnderwritingDriverObservation("carry", now, 0.01, 0.9, ("carry:1",)),
        ),
        decision_certified=True,
    )
    assert result.research_expected_return == 0.05
    assert result.decision_expected_return_impact == 0.0
    assert result.missing_drivers
    assert not result.decision_certified


def test_complete_certified_cash_underwriting_can_expose_decision_impact() -> None:
    now = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    observations = tuple(
        UnderwritingDriverObservation(name, now, value, 0.95, (f"{name}:1",))
        for name, value in (("carry", 0.04), ("liquidity", 0.0), ("credit_quality", 0.0))
    )
    result = AssetSpecificUnderwritingEngine().assess(
        asset_class=CandidateAssetClass.CASH_EQUIVALENT,
        as_of=now,
        observations=observations,
        decision_certified=True,
    )
    assert result.decision_certified
    assert result.decision_expected_return_impact == 0.04
