from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cio import CandidateAssetClass, DecisionPolicyMatrix
from operations.free_paper_pilot import load_free_paper_pilot_universe
from production_paper_evidence import (
    ListedWrapperFeatures,
    _candidate_and_evidence,
    _macro_context,
)

UTC = timezone.utc
AS_OF = datetime(2026, 7, 30, 15, 0, tzinfo=UTC)


def _features(symbol: str) -> ListedWrapperFeatures:
    return ListedWrapperFeatures(
        symbol=symbol,
        as_of=AS_OF,
        current_price=100.0,
        latest_observed_at=AS_OF,
        one_month_return=0.04,
        three_month_return=0.08,
        six_month_return=0.12,
        twelve_month_return=0.18,
        annualized_volatility=0.30,
        maximum_drawdown=-0.24,
        average_daily_dollar_volume=50_000_000.0,
        long_run_annual_return=0.14,
        rolling_annual_median=0.12,
        rolling_success_rate=0.72,
        bar_count=800,
        evidence_identifiers=(f"bars:{symbol}", f"quote:{symbol}"),
    )


def _macro(*, ten_year: float = 4.25, policy_rate: float = 4.25):
    return _macro_context(
        {
            "DGS10": {"date": "2026-07-30", "value": ten_year},
            "T10Y2Y": {"date": "2026-07-30", "value": 0.25},
            "VIXCLS": {"date": "2026-07-30", "value": 22.0},
            "DFF": {"date": "2026-07-30", "value": policy_rate},
        },
        as_of=AS_OF,
    )


def test_publisher_preserves_wrapper_execution_and_underlying_risk_class() -> None:
    universe = load_free_paper_pilot_universe()
    macro, _values, identifiers = _macro()

    ibit, _ = _candidate_and_evidence(
        universe.instrument_for_exposure("crypto"),
        _features("IBIT"),
        universe=universe,
        as_of=AS_OF,
        cash_expected_return=0.04,
        macro=macro,
        macro_identifiers=identifiers,
        current_weight=0.0,
    )
    vixy, _ = _candidate_and_evidence(
        universe.instrument_for_exposure("volatility"),
        _features("VIXY"),
        universe=universe,
        as_of=AS_OF,
        cash_expected_return=0.04,
        macro=macro,
        macro_identifiers=identifiers,
        current_weight=0.0,
    )

    assert ibit.instrument.asset_class is CandidateAssetClass.US_ETF
    assert ibit.instrument.economic_exposure_class is CandidateAssetClass.CRYPTO
    assert vixy.instrument.economic_exposure_class is CandidateAssetClass.VOLATILITY
    assert vixy.instrument.uses_derivatives is True
    assert "speculative-intermediate" in DecisionPolicyMatrix().resolve(ibit).identifier
    assert "nonlinear-derivative-intermediate" in DecisionPolicyMatrix().resolve(vixy).identifier


def test_pilot_inputs_disclose_priors_and_unavailable_market_dimensions() -> None:
    universe = load_free_paper_pilot_universe()
    macro, _values, identifiers = _macro()
    candidate, governed = _candidate_and_evidence(
        universe.instrument_for_exposure("us_equity"),
        _features("VTI"),
        universe=universe,
        as_of=AS_OF,
        cash_expected_return=0.04,
        macro=macro,
        macro_identifiers=identifiers,
        current_weight=0.0,
    )

    probabilities = (
        candidate.base_case_probability,
        candidate.bull_case_probability,
        candidate.bear_case_probability,
    )
    assert sum(probabilities) == pytest.approx(1.0)
    assert probabilities != pytest.approx((0.55, 0.25, 0.20))
    assert candidate.transaction_cost_bps != pytest.approx(5.0)
    assert candidate.slippage_bps != pytest.approx(5.0)
    assert governed.market.breadth == 0.0
    assert governed.market.positioning == 0.0
    assert any("breadth is unavailable" in item.lower() for item in governed.market.evidence)
    assert any("positioning data is unavailable" in item.lower() for item in governed.market.evidence)
    assert governed.forecast is not None
    assert governed.forecast.calibration_score != pytest.approx(0.60)
    assert any("evidence-derived, versioned pilot priors" in item for item in governed.forecast.limitations)


def test_macro_regime_uses_long_yield_and_policy_rate_not_only_curve_and_vix() -> None:
    ordinary, _values, _identifiers = _macro(ten_year=4.25, policy_rate=4.25)
    restrictive, _values, _identifiers = _macro(ten_year=5.10, policy_rate=5.25)

    assert ordinary.regime == "mixed"
    assert restrictive.regime == "restrictive_mixed"
    assert restrictive.expected_return_impact < ordinary.expected_return_impact
    assert "long yields" in restrictive.scenarios[0].lower()
    assert "policy rates" in restrictive.scenarios[0].lower()
