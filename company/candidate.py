"""Translate normalized company analysis into the common CIO candidate schema."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
)
from company.models import CompanyAnalysis, CompanyFactor


def _clip(value: float, minimum: float, maximum: float) -> float:
    return round(max(minimum, min(maximum, value)), 8)


@dataclass(frozen=True, slots=True)
class CompanyExpectedReturnPolicy:
    """Versioned expected-return hypothesis requiring later calibration."""

    version: str = "company-expected-return.v1"
    base_probability: float = 0.55
    bull_probability: float = 0.25
    bear_probability: float = 0.20
    minimum_bull_spread: float = 0.10
    minimum_bear_spread: float = 0.12
    maximum_base_return: float = 0.40
    minimum_base_return: float = -0.25
    full_liquidity_score_dollar_volume: float = 50_000_000.0

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        probability = (
            self.base_probability
            + self.bull_probability
            + self.bear_probability
        )
        if abs(probability - 1.0) > 0.000001:
            raise ValueError("scenario probabilities must sum to 1.0")
        if any(
            not 0.0 <= value <= 1.0
            for value in (
                self.base_probability,
                self.bull_probability,
                self.bear_probability,
            )
        ):
            raise ValueError("scenario probabilities must be between 0 and 1")
        if self.minimum_bull_spread <= 0.0 or self.minimum_bear_spread <= 0.0:
            raise ValueError("scenario spreads must be positive")
        if self.minimum_base_return >= self.maximum_base_return:
            raise ValueError("minimum_base_return must be below maximum")
        if self.full_liquidity_score_dollar_volume <= 0.0:
            raise ValueError(
                "full_liquidity_score_dollar_volume must be positive"
            )


class CompanyCandidateBuilder:
    """Produce a comparable expected-return candidate from company evidence."""

    def __init__(
        self,
        policy: CompanyExpectedReturnPolicy | None = None,
    ) -> None:
        self.policy = policy or CompanyExpectedReturnPolicy()

    def build(
        self,
        analysis: CompanyAnalysis,
        *,
        instrument_id: str,
        venue: str,
        opportunity_cost_return: float,
        maximum_position_weight: float,
        current_portfolio_weight: float = 0.0,
        transaction_cost_bps: float = 5.0,
        slippage_bps: float = 5.0,
        review_days: int = 30,
    ) -> CandidateDecisionRecord:
        if not isinstance(analysis, CompanyAnalysis):
            raise TypeError("analysis must be a CompanyAnalysis")
        if isinstance(review_days, bool) or not isinstance(review_days, int):
            raise TypeError("review_days must be an integer")
        if review_days < 1:
            raise ValueError("review_days must be positive")
        market = analysis.market
        valuation = analysis.factor(CompanyFactor.VALUATION)
        quality = analysis.factor(CompanyFactor.QUALITY)
        growth = analysis.factor(CompanyFactor.GROWTH)
        momentum = analysis.factor(CompanyFactor.MOMENTUM)
        regime = analysis.factor(CompanyFactor.REGIME_FIT)
        risk = analysis.factor(CompanyFactor.COMPANY_RISK)

        metrics = dict(valuation.metrics)
        fcf_yield = metrics.get("free_cash_flow_yield")
        earnings_yield = metrics.get("earnings_yield")
        shareholder_yield = metrics.get("dividend_yield", 0.0)
        cash_yield = max(
            value
            for value in (fcf_yield, earnings_yield, 0.0)
            if value is not None
        )
        revenue_growth = analysis.history.cagr("revenue") or 0.0
        sustainable_growth = _clip(revenue_growth, -0.10, 0.20)
        factor_adjustment = (
            quality.score * 0.025
            + growth.score * 0.025
            + valuation.score * 0.030
            + momentum.score * 0.015
            + regime.score * 0.015
            + risk.score * 0.015
        )
        base_return = _clip(
            cash_yield
            + shareholder_yield
            + sustainable_growth
            + factor_adjustment,
            self.policy.minimum_base_return,
            self.policy.maximum_base_return,
        )
        bull_spread = max(
            self.policy.minimum_bull_spread,
            market.annualized_volatility * 0.75,
        )
        bear_spread = max(
            self.policy.minimum_bear_spread,
            market.annualized_volatility * 1.25,
            abs(market.maximum_drawdown) * 0.75,
        )
        bull_return = _clip(base_return + bull_spread, -0.20, 1.50)
        bear_return = _clip(base_return - bear_spread, -0.95, 0.20)
        probability_of_success = _clip(
            0.50
            + analysis.overall_score * 0.22
            + analysis.confidence * 0.12
            - max(0.0, -risk.score) * 0.10,
            0.05,
            0.95,
        )
        base_fair_value = market.current_price * (1.0 + base_return)
        expected_portfolio_contribution = round(
            base_return * maximum_position_weight,
            8,
        )
        evidence = tuple(
            f"{factor.factor.value}: {factor.evidence[0]}"
            for factor in analysis.factors
        )
        contradictory = tuple(
            f"{factor.factor.value}: {factor.risks[0]}"
            for factor in analysis.factors
            if factor.score < 0.35 or factor.confidence < 0.75
        )
        risks = tuple(
            dict.fromkeys(
                risk_text
                for factor in analysis.factors
                for risk_text in factor.risks
            )
        )
        instrument = CandidateInstrument(
            instrument_id=instrument_id,
            symbol=analysis.symbol,
            name=f"{analysis.symbol} common equity",
            asset_class=CandidateAssetClass.US_EQUITY,
            venue=venue,
            country_code="US",
            average_daily_dollar_volume=market.average_daily_dollar_volume,
            data_age_hours=market.data_age_hours,
            analytical_coverage=analysis.evidence_quality.completeness,
        )
        return CandidateDecisionRecord(
            identifier=(
                f"candidate:{analysis.symbol.lower()}:"
                f"{analysis.as_of.isoformat()}"
            ),
            as_of=analysis.as_of,
            schema_version="candidate-decision.v1",
            instrument=instrument,
            current_price=market.current_price,
            decision_horizon_days=365,
            base_case_return=base_return,
            bull_case_return=bull_return,
            bear_case_return=bear_return,
            base_case_probability=self.policy.base_probability,
            bull_case_probability=self.policy.bull_probability,
            bear_case_probability=self.policy.bear_probability,
            estimated_fair_value=round(base_fair_value, 8),
            expected_upside=bull_return,
            expected_downside=bear_return,
            probability_of_success=probability_of_success,
            primary_catalysts=tuple(
                dict.fromkeys(
                    (
                        "Company quality, growth, valuation, momentum, and regime evidence changed the expected-return estimate",
                        *(
                            f"{factor.factor.value} score={factor.score:.3f}"
                            for factor in analysis.factors
                            if factor.score >= 0.35
                        ),
                    )
                )
            ),
            key_risks=risks or ("Company evidence could deteriorate",),
            critical_assumptions=(
                "Normalized SEC financials remain representative of ongoing economics",
                "The versioned expected-return mapping remains directionally valid",
                "Market liquidity remains above the Version 1 floor",
            ),
            invalidation_conditions=(
                "Expected return falls below the opportunity qualification threshold",
                "Evidence quality or freshness falls below policy",
                "A qualified replacement offers a materially superior opportunity edge",
            ),
            supporting_evidence=evidence,
            contradictory_evidence=contradictory,
            evidence_quality=analysis.evidence_quality,
            liquidity_score=_clip(
                market.average_daily_dollar_volume
                / self.policy.full_liquidity_score_dollar_volume,
                0.0,
                1.0,
            ),
            transaction_cost_bps=transaction_cost_bps,
            slippage_bps=slippage_bps,
            opportunity_cost_return=opportunity_cost_return,
            expected_portfolio_contribution=expected_portfolio_contribution,
            current_portfolio_weight=current_portfolio_weight,
            maximum_position_weight=maximum_position_weight,
            monitoring_indicators=(
                "Revenue and free-cash-flow growth",
                "Estimate revisions and operating margins",
                "Valuation yields and relative momentum",
                "Leverage, volatility, drawdown, and regime fit",
            ),
            review_at=analysis.as_of + timedelta(days=review_days),
            evidence_identifiers=analysis.evidence_identifiers,
            model_versions=(
                analysis.history.normalization_version,
                analysis.analysis_version,
                self.policy.version,
            ),
        )


__all__ = [
    "CompanyCandidateBuilder",
    "CompanyExpectedReturnPolicy",
]