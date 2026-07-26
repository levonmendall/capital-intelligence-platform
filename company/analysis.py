"""Deterministic company quality, growth, valuation, momentum, and risk analysis."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from cio import EvidenceQuality
from company.models import (
    CompanyAnalysis,
    CompanyFactor,
    CompanyFactorAssessment,
    CompanyMarketSnapshot,
    CompanyRegimeContext,
    FinancialHistory,
)


def _clip(value: float) -> float:
    return round(max(-1.0, min(1.0, value)), 8)


def _available(values: tuple[float | None, ...]) -> tuple[float, ...]:
    return tuple(float(value) for value in values if value is not None)


def _average_score(values: tuple[float | None, ...]) -> tuple[float, float]:
    resolved = _available(values)
    if not resolved:
        return 0.0, 0.0
    return round(mean(resolved), 8), round(len(resolved) / len(values), 6)


def _metric_tuple(values: dict[str, float | None]) -> tuple[tuple[str, float], ...]:
    return tuple((name, value) for name, value in values.items() if value is not None)


def _evidence(
    factor: CompanyFactor,
    metrics: tuple[tuple[str, float], ...],
) -> tuple[str, ...]:
    if not metrics:
        return (f"{factor.value} evidence is unavailable",)
    return tuple(f"{name}={value:.4f}" for name, value in metrics)


def _risks(
    factor: CompanyFactor,
    score: float,
    confidence: float,
) -> tuple[str, ...]:
    values: list[str] = []
    if confidence < 0.75:
        values.append("analytical coverage is incomplete")
    if score < 0.0:
        values.append(f"{factor.value} evidence is unfavorable")
    elif score < 0.35:
        values.append(f"{factor.value} support is limited")
    if not values:
        values.append(f"{factor.value} evidence could deteriorate after the decision time")
    return tuple(values)


@dataclass(frozen=True, slots=True)
class CompanyAnalysisPolicy:
    """Versioned deterministic factor rules requiring later calibration."""

    version: str = "company-analysis.v1"
    tax_rate: float = 0.21

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        if not 0.0 <= self.tax_rate <= 1.0:
            raise ValueError("tax_rate must be between 0 and 1")


class CompanyAnalysisEngine:
    """Produce eight comparable company-factor assessments."""

    def __init__(self, policy: CompanyAnalysisPolicy | None = None) -> None:
        self.policy = policy or CompanyAnalysisPolicy()

    def analyze(
        self,
        *,
        symbol: str,
        history: FinancialHistory,
        market: CompanyMarketSnapshot,
        regime: CompanyRegimeContext,
    ) -> CompanyAnalysis:
        if not isinstance(history, FinancialHistory):
            raise TypeError("history must be a FinancialHistory")
        if not isinstance(market, CompanyMarketSnapshot):
            raise TypeError("market must be a CompanyMarketSnapshot")
        if not isinstance(regime, CompanyRegimeContext):
            raise TypeError("regime must be a CompanyRegimeContext")
        if history.as_of != market.as_of or history.as_of != regime.as_of:
            raise ValueError("company inputs must share one decision timestamp")
        factors = (
            self._quality(history),
            self._financial_strength(history),
            self._growth(history),
            self._earnings_quality(history),
            self._valuation(history, market),
            self._momentum(market),
            self._regime_fit(regime),
            self._company_risk(history, market),
        )
        factor_coverage = sum(item.confidence for item in factors) / len(factors)
        market_freshness = max(0.0, 1.0 - market.data_age_hours / 72.0)
        evidence_quality = EvidenceQuality(
            reliability=0.95,
            freshness=round(min(1.0, market_freshness), 6),
            relevance=1.0,
            independence=0.80,
            completeness=round(
                min(1.0, (history.coverage + factor_coverage) / 2.0),
                6,
            ),
            point_in_time_integrity=1.0,
        )
        return CompanyAnalysis(
            cik=history.cik,
            symbol=symbol,
            as_of=history.as_of,
            history=history,
            market=market,
            regime=regime,
            factors=factors,
            evidence_quality=evidence_quality,
            analysis_version=self.policy.version,
        )

    def _assessment(
        self,
        factor: CompanyFactor,
        *,
        score: float,
        confidence: float,
        metrics: dict[str, float | None],
    ) -> CompanyFactorAssessment:
        resolved = _metric_tuple(metrics)
        return CompanyFactorAssessment(
            factor=factor,
            score=_clip(score),
            confidence=round(max(0.0, min(1.0, confidence)), 6),
            evidence=_evidence(factor, resolved),
            risks=_risks(factor, score, confidence),
            metrics=resolved,
            methodology_version=self.policy.version,
        )

    def _quality(self, history: FinancialHistory) -> CompanyFactorAssessment:
        latest = history.latest
        roic = latest.return_on_invested_capital(self.policy.tax_rate)
        operating_margin = latest.operating_margin
        fcf_margin = latest.free_cash_flow_margin
        net_margin = latest.net_margin
        score, coverage = _average_score(
            (
                None if roic is None else _clip((roic - 0.08) / 0.12),
                (
                    None
                    if operating_margin is None
                    else _clip((operating_margin - 0.10) / 0.15)
                ),
                (
                    None
                    if fcf_margin is None
                    else _clip((fcf_margin - 0.05) / 0.12)
                ),
                None if net_margin is None else _clip((net_margin - 0.06) / 0.10),
            )
        )
        return self._assessment(
            CompanyFactor.QUALITY,
            score=score,
            confidence=coverage,
            metrics={
                "return_on_invested_capital": roic,
                "operating_margin": operating_margin,
                "free_cash_flow_margin": fcf_margin,
                "net_margin": net_margin,
            },
        )

    def _financial_strength(
        self,
        history: FinancialHistory,
    ) -> CompanyFactorAssessment:
        latest = history.latest
        debt_to_assets = latest.debt_to_assets
        current_ratio = latest.current_ratio
        cash_to_debt = latest.cash_to_debt
        equity_ratio = (
            None
            if latest.equity is None or latest.assets in {None, 0.0}
            else latest.equity / latest.assets
        )
        score, coverage = _average_score(
            (
                (
                    None
                    if debt_to_assets is None
                    else _clip((0.45 - debt_to_assets) / 0.35)
                ),
                (
                    None
                    if current_ratio is None
                    else _clip((current_ratio - 1.0) / 1.0)
                ),
                (
                    None
                    if cash_to_debt is None
                    else _clip((cash_to_debt - 0.25) / 0.75)
                ),
                (
                    None
                    if equity_ratio is None
                    else _clip((equity_ratio - 0.25) / 0.35)
                ),
            )
        )
        return self._assessment(
            CompanyFactor.FINANCIAL_STRENGTH,
            score=score,
            confidence=coverage,
            metrics={
                "debt_to_assets": debt_to_assets,
                "current_ratio": current_ratio,
                "cash_to_debt": cash_to_debt,
                "equity_to_assets": equity_ratio,
            },
        )

    def _growth(self, history: FinancialHistory) -> CompanyFactorAssessment:
        revenue_cagr = history.cagr("revenue")
        operating_income_cagr = history.cagr("operating_income")
        net_income_cagr = history.cagr("net_income")
        fcf_values = tuple(item.free_cash_flow for item in history.periods)
        fcf_cagr = self._sequence_cagr(fcf_values, history)
        score, coverage = _average_score(
            tuple(
                None if value is None else _clip((value - 0.03) / 0.12)
                for value in (
                    revenue_cagr,
                    operating_income_cagr,
                    net_income_cagr,
                    fcf_cagr,
                )
            )
        )
        return self._assessment(
            CompanyFactor.GROWTH,
            score=score,
            confidence=coverage,
            metrics={
                "revenue_cagr": revenue_cagr,
                "operating_income_cagr": operating_income_cagr,
                "net_income_cagr": net_income_cagr,
                "free_cash_flow_cagr": fcf_cagr,
            },
        )

    def _earnings_quality(
        self,
        history: FinancialHistory,
    ) -> CompanyFactorAssessment:
        latest = history.latest
        cfo_conversion = (
            None
            if latest.operating_cash_flow is None
            or latest.net_income in {None, 0.0}
            else latest.operating_cash_flow / abs(latest.net_income)
        )
        fcf_conversion = (
            None
            if latest.free_cash_flow is None or latest.net_income in {None, 0.0}
            else latest.free_cash_flow / abs(latest.net_income)
        )
        accrual_ratio = (
            None
            if latest.net_income is None
            or latest.operating_cash_flow is None
            or latest.assets in {None, 0.0}
            else (latest.net_income - latest.operating_cash_flow) / latest.assets
        )
        score, coverage = _average_score(
            (
                (
                    None
                    if cfo_conversion is None
                    else _clip((cfo_conversion - 0.75) / 0.75)
                ),
                (
                    None
                    if fcf_conversion is None
                    else _clip((fcf_conversion - 0.50) / 0.75)
                ),
                (
                    None
                    if accrual_ratio is None
                    else _clip(-accrual_ratio / 0.10)
                ),
            )
        )
        return self._assessment(
            CompanyFactor.EARNINGS_QUALITY,
            score=score,
            confidence=coverage,
            metrics={
                "operating_cash_flow_to_net_income": cfo_conversion,
                "free_cash_flow_to_net_income": fcf_conversion,
                "accrual_ratio": accrual_ratio,
            },
        )

    def _valuation(
        self,
        history: FinancialHistory,
        market: CompanyMarketSnapshot,
    ) -> CompanyFactorAssessment:
        latest = history.latest
        earnings_yield = (
            None
            if latest.net_income is None
            else latest.net_income / market.market_cap
        )
        fcf_yield = (
            None
            if latest.free_cash_flow is None
            else latest.free_cash_flow / market.market_cap
        )
        sales_yield = latest.revenue / market.market_cap
        shareholder_yield = (
            market.dividend_per_share / market.current_price
            if market.current_price
            else None
        )
        score, coverage = _average_score(
            (
                (
                    None
                    if earnings_yield is None
                    else _clip((earnings_yield - 0.04) / 0.06)
                ),
                (
                    None
                    if fcf_yield is None
                    else _clip((fcf_yield - 0.04) / 0.06)
                ),
                _clip((sales_yield - 0.30) / 0.70),
                _clip((shareholder_yield - 0.01) / 0.04),
            )
        )
        return self._assessment(
            CompanyFactor.VALUATION,
            score=score,
            confidence=coverage,
            metrics={
                "earnings_yield": earnings_yield,
                "free_cash_flow_yield": fcf_yield,
                "sales_yield": sales_yield,
                "dividend_yield": shareholder_yield,
            },
        )

    def _momentum(
        self,
        market: CompanyMarketSnapshot,
    ) -> CompanyFactorAssessment:
        relative_return = (
            market.twelve_month_return - market.benchmark_twelve_month_return
        )
        trend_spread = (
            market.current_price / market.moving_average_200 - 1.0
            if market.moving_average_200 > 0.0
            else None
        )
        score, coverage = _average_score(
            (
                _clip(market.six_month_return / 0.25),
                _clip(market.twelve_month_return / 0.40),
                _clip(relative_return / 0.25),
                None if trend_spread is None else _clip(trend_spread / 0.20),
            )
        )
        return self._assessment(
            CompanyFactor.MOMENTUM,
            score=score,
            confidence=coverage,
            metrics={
                "six_month_return": market.six_month_return,
                "twelve_month_return": market.twelve_month_return,
                "relative_twelve_month_return": relative_return,
                "price_to_200_day_trend": trend_spread,
            },
        )

    def _regime_fit(
        self,
        regime: CompanyRegimeContext,
    ) -> CompanyFactorAssessment:
        cyclical = regime.industry_cyclicality
        duration = regime.duration_sensitivity
        score = (
            regime.growth_support * (0.20 + 0.25 * cyclical)
            + regime.liquidity_support * (0.20 + 0.20 * duration)
            + regime.credit_support * (0.20 + 0.15 * cyclical)
            + regime.market_risk_support * 0.20
        )
        normalization = (
            (0.20 + 0.25 * cyclical)
            + (0.20 + 0.20 * duration)
            + (0.20 + 0.15 * cyclical)
            + 0.20
        )
        score = score / normalization
        return self._assessment(
            CompanyFactor.REGIME_FIT,
            score=score,
            confidence=1.0,
            metrics={
                "growth_support": regime.growth_support,
                "liquidity_support": regime.liquidity_support,
                "credit_support": regime.credit_support,
                "market_risk_support": regime.market_risk_support,
                "industry_cyclicality": cyclical,
                "duration_sensitivity": duration,
            },
        )

    def _company_risk(
        self,
        history: FinancialHistory,
        market: CompanyMarketSnapshot,
    ) -> CompanyFactorAssessment:
        debt_to_assets = history.latest.debt_to_assets
        revenue_volatility = history.volatility("revenue")
        margin_values = tuple(item.operating_margin for item in history.periods)
        margin_volatility = self._relative_volatility(margin_values)
        # Higher factor scores mean better risk characteristics.
        score, coverage = _average_score(
            (
                (
                    None
                    if debt_to_assets is None
                    else _clip((0.45 - debt_to_assets) / 0.35)
                ),
                _clip((0.45 - market.annualized_volatility) / 0.30),
                _clip((0.40 - abs(market.maximum_drawdown)) / 0.30),
                (
                    None
                    if revenue_volatility is None
                    else _clip((0.25 - revenue_volatility) / 0.20)
                ),
                (
                    None
                    if margin_volatility is None
                    else _clip((0.30 - margin_volatility) / 0.25)
                ),
            )
        )
        return self._assessment(
            CompanyFactor.COMPANY_RISK,
            score=score,
            confidence=coverage,
            metrics={
                "debt_to_assets": debt_to_assets,
                "annualized_volatility": market.annualized_volatility,
                "maximum_drawdown": market.maximum_drawdown,
                "revenue_volatility": revenue_volatility,
                "operating_margin_volatility": margin_volatility,
            },
        )

    @staticmethod
    def _sequence_cagr(
        values: tuple[float | None, ...],
        history: FinancialHistory,
    ) -> float | None:
        if len(values) < 2:
            return None
        first, last = values[0], values[-1]
        if first is None or last is None or first <= 0.0 or last < 0.0:
            return None
        years = history.periods[-1].fiscal_year - history.periods[0].fiscal_year
        if years <= 0:
            return None
        return round((last / first) ** (1.0 / years) - 1.0, 8)

    @staticmethod
    def _relative_volatility(values: tuple[float | None, ...]) -> float | None:
        resolved = _available(values)
        if len(resolved) < 2:
            return None
        average = mean(resolved)
        if average == 0.0:
            return None
        variance = sum((item - average) ** 2 for item in resolved) / len(resolved)
        return round((variance**0.5) / abs(average), 8)


__all__ = ["CompanyAnalysisEngine", "CompanyAnalysisPolicy"]