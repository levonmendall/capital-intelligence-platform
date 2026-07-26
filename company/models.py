"""Normalized point-in-time company financial and analytical contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from math import isfinite

from cio import EvidenceQuality


class FinancialMetric(str, Enum):
    REVENUE = "revenue"
    OPERATING_INCOME = "operating_income"
    NET_INCOME = "net_income"
    OPERATING_CASH_FLOW = "operating_cash_flow"
    CAPITAL_EXPENDITURES = "capital_expenditures"
    ASSETS = "assets"
    LIABILITIES = "liabilities"
    EQUITY = "equity"
    CASH = "cash"
    DEBT = "debt"
    CURRENT_ASSETS = "current_assets"
    CURRENT_LIABILITIES = "current_liabilities"
    DILUTED_SHARES = "diluted_shares"


class CompanyFactor(str, Enum):
    QUALITY = "quality"
    FINANCIAL_STRENGTH = "financial_strength"
    GROWTH = "growth"
    EARNINGS_QUALITY = "earnings_quality"
    VALUATION = "valuation"
    MOMENTUM = "momentum"
    REGIME_FIT = "regime_fit"
    COMPANY_RISK = "company_risk"


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _finite(
    value: object,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    if maximum is not None and normalized > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}")
    return round(normalized, 8)


def _optional_finite(
    value: object,
    *,
    field_name: str,
    minimum: float | None = None,
) -> float | None:
    if value is None:
        return None
    return _finite(value, field_name=field_name, minimum=minimum)


def _text_tuple(
    value: object,
    *,
    field_name: str,
    minimum: int = 0,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(
        _required_text(item, field_name=field_name) for item in value
    )
    if len(normalized) < minimum:
        raise ValueError(
            f"{field_name} must contain at least {minimum} item(s)"
        )
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0.0:
        return None
    return round(numerator / denominator, 8)


@dataclass(frozen=True, slots=True)
class NormalizedAnnualFinancials:
    """One accepted annual statement snapshot without synthetic missing values."""

    cik: str
    fiscal_year: int
    period_end: date
    available_at: datetime
    accession_numbers: tuple[str, ...]
    source_fact_identifiers: tuple[str, ...]
    revenue: float
    operating_income: float | None = None
    net_income: float | None = None
    operating_cash_flow: float | None = None
    capital_expenditures: float | None = None
    assets: float | None = None
    liabilities: float | None = None
    equity: float | None = None
    cash: float | None = None
    debt: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    diluted_shares: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cik", _required_text(self.cik, field_name="cik"))
        if isinstance(self.fiscal_year, bool) or not isinstance(self.fiscal_year, int):
            raise TypeError("fiscal_year must be an integer")
        if not 1900 <= self.fiscal_year <= 3000:
            raise ValueError("fiscal_year is outside the supported range")
        if not isinstance(self.period_end, date) or isinstance(self.period_end, datetime):
            raise TypeError("period_end must be a date")
        available = _aware(self.available_at, field_name="available_at")
        if self.period_end > available.date():
            raise ValueError("period_end cannot be later than available_at")
        object.__setattr__(
            self,
            "accession_numbers",
            _text_tuple(
                self.accession_numbers,
                field_name="accession_numbers",
                minimum=1,
            ),
        )
        object.__setattr__(
            self,
            "source_fact_identifiers",
            _text_tuple(
                self.source_fact_identifiers,
                field_name="source_fact_identifiers",
                minimum=1,
            ),
        )
        object.__setattr__(
            self,
            "revenue",
            _finite(self.revenue, field_name="revenue", minimum=0.0),
        )
        for field_name in (
            "operating_income",
            "net_income",
            "operating_cash_flow",
            "capital_expenditures",
            "equity",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_finite(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "assets",
            "liabilities",
            "cash",
            "debt",
            "current_assets",
            "current_liabilities",
            "diluted_shares",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                ),
            )

    @property
    def free_cash_flow(self) -> float | None:
        if self.operating_cash_flow is None or self.capital_expenditures is None:
            return None
        return round(self.operating_cash_flow - abs(self.capital_expenditures), 8)

    @property
    def operating_margin(self) -> float | None:
        return _safe_divide(self.operating_income, self.revenue)

    @property
    def net_margin(self) -> float | None:
        return _safe_divide(self.net_income, self.revenue)

    @property
    def free_cash_flow_margin(self) -> float | None:
        return _safe_divide(self.free_cash_flow, self.revenue)

    @property
    def debt_to_assets(self) -> float | None:
        return _safe_divide(self.debt, self.assets)

    @property
    def current_ratio(self) -> float | None:
        return _safe_divide(self.current_assets, self.current_liabilities)

    @property
    def cash_to_debt(self) -> float | None:
        return _safe_divide(self.cash, self.debt)

    @property
    def invested_capital(self) -> float | None:
        if self.equity is None and self.debt is None:
            return None
        capital = (self.equity or 0.0) + (self.debt or 0.0) - (self.cash or 0.0)
        return round(capital, 8) if capital > 0.0 else None

    def return_on_invested_capital(self, tax_rate: float = 0.21) -> float | None:
        if not 0.0 <= tax_rate <= 1.0:
            raise ValueError("tax_rate must be between 0 and 1")
        if self.operating_income is None or self.invested_capital is None:
            return None
        nopat = self.operating_income * (1.0 - tax_rate)
        return _safe_divide(nopat, self.invested_capital)

    @property
    def coverage(self) -> float:
        values = (
            self.revenue,
            self.operating_income,
            self.net_income,
            self.operating_cash_flow,
            self.capital_expenditures,
            self.assets,
            self.liabilities,
            self.equity,
            self.cash,
            self.debt,
            self.current_assets,
            self.current_liabilities,
            self.diluted_shares,
        )
        return round(sum(value is not None for value in values) / len(values), 6)


@dataclass(frozen=True, slots=True)
class FinancialHistory:
    cik: str
    as_of: datetime
    periods: tuple[NormalizedAnnualFinancials, ...]
    normalization_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "cik", _required_text(self.cik, field_name="cik"))
        _aware(self.as_of, field_name="as_of")
        object.__setattr__(
            self,
            "normalization_version",
            _required_text(
                self.normalization_version,
                field_name="normalization_version",
            ),
        )
        if not isinstance(self.periods, tuple) or not all(
            isinstance(item, NormalizedAnnualFinancials) for item in self.periods
        ):
            raise TypeError("periods must contain NormalizedAnnualFinancials values")
        if not self.periods:
            raise ValueError("financial history requires at least one annual period")
        if any(item.cik != self.cik for item in self.periods):
            raise ValueError("all periods must match the history CIK")
        if any(item.available_at > self.as_of for item in self.periods):
            raise ValueError("financial history cannot include future-available periods")
        ordered = tuple(sorted(self.periods, key=lambda item: item.period_end))
        if ordered != self.periods:
            raise ValueError("periods must be ordered by period_end")
        years = tuple(item.fiscal_year for item in self.periods)
        if len(years) != len(set(years)):
            raise ValueError("financial history cannot contain duplicate fiscal years")

    @property
    def latest(self) -> NormalizedAnnualFinancials:
        return self.periods[-1]

    @property
    def coverage(self) -> float:
        return round(sum(item.coverage for item in self.periods) / len(self.periods), 6)

    def cagr(self, field_name: str) -> float | None:
        if len(self.periods) < 2:
            return None
        first = getattr(self.periods[0], field_name)
        last = getattr(self.periods[-1], field_name)
        if first is None or last is None or first <= 0.0 or last < 0.0:
            return None
        years = self.periods[-1].fiscal_year - self.periods[0].fiscal_year
        if years <= 0:
            return None
        return round((last / first) ** (1.0 / years) - 1.0, 8)

    def volatility(self, field_name: str) -> float | None:
        values = [getattr(item, field_name) for item in self.periods]
        resolved = [float(item) for item in values if item is not None]
        if len(resolved) < 2:
            return None
        mean = sum(resolved) / len(resolved)
        if mean == 0.0:
            return None
        variance = sum((item - mean) ** 2 for item in resolved) / len(resolved)
        return round((variance**0.5) / abs(mean), 8)


@dataclass(frozen=True, slots=True)
class CompanyMarketSnapshot:
    as_of: datetime
    current_price: float
    market_cap: float
    shares_outstanding: float
    dividend_per_share: float
    six_month_return: float
    twelve_month_return: float
    benchmark_twelve_month_return: float
    annualized_volatility: float
    maximum_drawdown: float
    moving_average_200: float
    average_daily_dollar_volume: float
    data_age_hours: float
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        _aware(self.as_of, field_name="as_of")
        for field_name in (
            "current_price",
            "market_cap",
            "shares_outstanding",
            "moving_average_200",
            "average_daily_dollar_volume",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                ),
            )
        if self.current_price <= 0.0 or self.market_cap <= 0.0:
            raise ValueError("current_price and market_cap must be positive")
        for field_name in (
            "dividend_per_share",
            "six_month_return",
            "twelve_month_return",
            "benchmark_twelve_month_return",
            "maximum_drawdown",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "annualized_volatility",
            _finite(
                self.annualized_volatility,
                field_name="annualized_volatility",
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "data_age_hours",
            _finite(
                self.data_age_hours,
                field_name="data_age_hours",
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _text_tuple(
                self.evidence_identifiers,
                field_name="evidence_identifiers",
                minimum=1,
            ),
        )


@dataclass(frozen=True, slots=True)
class CompanyRegimeContext:
    as_of: datetime
    growth_support: float
    liquidity_support: float
    credit_support: float
    market_risk_support: float
    industry_cyclicality: float
    duration_sensitivity: float
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        _aware(self.as_of, field_name="as_of")
        for field_name in (
            "growth_support",
            "liquidity_support",
            "credit_support",
            "market_risk_support",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=-1.0,
                    maximum=1.0,
                ),
            )
        for field_name in ("industry_cyclicality", "duration_sensitivity"):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                    maximum=1.0,
                ),
            )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _text_tuple(
                self.evidence_identifiers,
                field_name="evidence_identifiers",
                minimum=1,
            ),
        )


@dataclass(frozen=True, slots=True)
class CompanyFactorAssessment:
    factor: CompanyFactor
    score: float
    confidence: float
    evidence: tuple[str, ...]
    risks: tuple[str, ...]
    metrics: tuple[tuple[str, float], ...]
    methodology_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.factor, CompanyFactor):
            raise TypeError("factor must be a CompanyFactor")
        object.__setattr__(
            self,
            "score",
            _finite(self.score, field_name="score", minimum=-1.0, maximum=1.0),
        )
        object.__setattr__(
            self,
            "confidence",
            _finite(
                self.confidence,
                field_name="confidence",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        for field_name, minimum in (("evidence", 1), ("risks", 1)):
            object.__setattr__(
                self,
                field_name,
                _text_tuple(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=minimum,
                ),
            )
        if not isinstance(self.metrics, tuple):
            raise TypeError("metrics must be a tuple")
        normalized: list[tuple[str, float]] = []
        for name, value in self.metrics:
            normalized.append(
                (
                    _required_text(name, field_name="metric name"),
                    _finite(value, field_name=f"metric {name}"),
                )
            )
        if len(normalized) != len({name for name, _ in normalized}):
            raise ValueError("factor metric names must be unique")
        object.__setattr__(self, "metrics", tuple(normalized))
        object.__setattr__(
            self,
            "methodology_version",
            _required_text(
                self.methodology_version,
                field_name="methodology_version",
            ),
        )


@dataclass(frozen=True, slots=True)
class CompanyAnalysis:
    cik: str
    symbol: str
    as_of: datetime
    history: FinancialHistory
    market: CompanyMarketSnapshot
    regime: CompanyRegimeContext
    factors: tuple[CompanyFactorAssessment, ...]
    evidence_quality: EvidenceQuality
    analysis_version: str

    def __post_init__(self) -> None:
        for field_name in ("cik", "symbol", "analysis_version"):
            value = _required_text(getattr(self, field_name), field_name=field_name)
            object.__setattr__(
                self,
                field_name,
                value.upper() if field_name == "symbol" else value,
            )
        _aware(self.as_of, field_name="as_of")
        if self.history.cik != self.cik:
            raise ValueError("history does not match analysis CIK")
        if self.history.as_of != self.as_of:
            raise ValueError("history must share the analysis timestamp")
        if self.market.as_of != self.as_of or self.regime.as_of != self.as_of:
            raise ValueError("market and regime inputs must share analysis timestamp")
        if not isinstance(self.factors, tuple) or not all(
            isinstance(item, CompanyFactorAssessment) for item in self.factors
        ):
            raise TypeError("factors must contain CompanyFactorAssessment values")
        factor_names = tuple(item.factor for item in self.factors)
        if set(factor_names) != set(CompanyFactor):
            raise ValueError("company analysis requires all eight company factors")
        if len(factor_names) != len(set(factor_names)):
            raise ValueError("company analysis cannot contain duplicate factors")
        if not isinstance(self.evidence_quality, EvidenceQuality):
            raise TypeError("evidence_quality must be EvidenceQuality")

    def factor(self, factor: CompanyFactor) -> CompanyFactorAssessment:
        return next(item for item in self.factors if item.factor is factor)

    @property
    def overall_score(self) -> float:
        weights = {
            CompanyFactor.QUALITY: 0.18,
            CompanyFactor.FINANCIAL_STRENGTH: 0.12,
            CompanyFactor.GROWTH: 0.14,
            CompanyFactor.EARNINGS_QUALITY: 0.10,
            CompanyFactor.VALUATION: 0.16,
            CompanyFactor.MOMENTUM: 0.12,
            CompanyFactor.REGIME_FIT: 0.08,
            CompanyFactor.COMPANY_RISK: 0.10,
        }
        return round(
            sum(item.score * weights[item.factor] for item in self.factors),
            8,
        )

    @property
    def confidence(self) -> float:
        factor_confidence = sum(item.confidence for item in self.factors) / len(
            self.factors
        )
        return round(
            min(factor_confidence, self.evidence_quality.ceiling),
            6,
        )

    @property
    def evidence_identifiers(self) -> tuple[str, ...]:
        values = (
            tuple(
                identifier
                for period in self.history.periods
                for identifier in period.source_fact_identifiers
            )
            + self.market.evidence_identifiers
            + self.regime.evidence_identifiers
        )
        return tuple(dict.fromkeys(values))


__all__ = [
    "CompanyAnalysis",
    "CompanyFactor",
    "CompanyFactorAssessment",
    "CompanyMarketSnapshot",
    "CompanyRegimeContext",
    "FinancialHistory",
    "FinancialMetric",
    "NormalizedAnnualFinancials",
]