from cio.models import CandidateAssetClass
from intelligence.asset_underwriting import (
    AssetUnderwritingPolicy,
    UnderwritingDimension,
)


def test_fixed_income_requires_curve_credit_and_carry() -> None:
    policy = AssetUnderwritingPolicy()
    required = set(policy.required_dimensions(CandidateAssetClass.FIXED_INCOME))
    assert UnderwritingDimension.CARRY in required
    assert UnderwritingDimension.CURVE in required
    assert UnderwritingDimension.CREDIT in required


def test_crypto_underwriting_reports_missing_onchain_instead_of_treating_it_neutral() -> None:
    policy = AssetUnderwritingPolicy()
    coverage = policy.assess(
        CandidateAssetClass.CRYPTO,
        (
            UnderwritingDimension.IDENTITY,
            UnderwritingDimension.MARKET_DATA,
            UnderwritingDimension.LIQUIDITY,
            UnderwritingDimension.MACRO,
            UnderwritingDimension.VALUATION,
            UnderwritingDimension.HISTORY,
            UnderwritingDimension.POSITIONING,
        ),
    )
    assert UnderwritingDimension.ONCHAIN in coverage.missing
    assert not coverage.decision_complete
    assert coverage.completeness < 1.0
