"""Point-in-time candidate and holding evidence for the listed-wrapper paper pilot.

The builder converts authenticated Alpaca IEX daily bars and quotes plus official FRED
macro observations into the existing canonical candidate, specialist, and holding
contracts.  It does not decide, rank, size, construct, or execute a portfolio.  Missing
or future-known evidence remains an explicit exclusion, and evidence for an existing
holding is mandatory.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from math import isfinite, log10, sqrt
from statistics import median, pstdev
from typing import Any, Callable, Mapping, Sequence

from application.cio_cycle import CandidateExposureProfile
from application.production_context import (
    EvidenceCertificationState,
    GovernedEvidenceLineage,
    ProductionCandidateEvidence,
    ProductionHoldingEvidence,
)
from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceDependency,
    EvidenceQuality,
)
from company import (
    CompanyAnalysisEngine,
    CompanyCandidateBuilder,
    CompanyFactNormalizer,
    CompanyMarketSnapshot,
    CompanyRegimeContext,
)
from company.models import CompanyFactor
from data import FilingQuery
from committee.specialists import (
    AssetValuationSpecialistContext,
    CrossAssetForecastSpecialistContext,
    ForecastScenarioAssessment,
    MacroSpecialistContext,
    MarketSpecialistContext,
)
from operations.free_paper_pilot import FreePaperPilotInstrument, FreePaperPilotUniverse
from portfolio.state import CanonicalPortfolioSnapshot
from providers.alpaca_paper import create_alpaca_paper_client
from providers.fred import FREDProvider
from providers.sec_edgar import SECEdgarProvider

EvidenceProbe = Callable[[FreePaperPilotUniverse, datetime], Mapping[str, object]]

_MINIMUM_BARS = 252
_HISTORY_DAYS = 365 * 10 + 20
_MODEL_VERSION = "listed-wrapper-evidence.v1"
_FORECAST_VERSION = "listed-wrapper-macro-distribution-forecast.v1"
_VALUATION_VERSION = "listed-wrapper-distribution-valuation.v1"
_COMPANY_EVIDENCE_VERSION = "sec-company-equity-evidence.v1"


class ProductionPaperEvidenceError(RuntimeError):
    """Raised when mandatory point-in-time paper evidence cannot be certified."""


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _clip(value: float, minimum: float = -1.0, maximum: float = 1.0) -> float:
    return round(max(minimum, min(maximum, float(value))), 8)


def _number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProductionPaperEvidenceError(f"{field_name} must be numeric")
    result = float(value)
    if not isfinite(result):
        raise ProductionPaperEvidenceError(f"{field_name} must be finite")
    return result


def _timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ProductionPaperEvidenceError(f"{field_name} is unavailable")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ProductionPaperEvidenceError(f"{field_name} is invalid") from error
    return _aware(parsed, field_name=field_name)


def _evidence_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _default_probe(
    universe: FreePaperPilotUniverse,
    decision_as_of: datetime,
) -> Mapping[str, object]:
    as_of = _aware(decision_as_of, field_name="decision_as_of")
    symbols = tuple(item.symbol for item in universe.instruments)
    client = create_alpaca_paper_client()
    bars = client.historical_bars(
        symbols,
        start=as_of - timedelta(days=_HISTORY_DAYS),
        end=as_of,
        timeframe="1Day",
    )
    quotes = client.latest_quotes(symbols)
    fred = FREDProvider()
    macro = {
        series: fred.get_latest_value(series)
        for series in ("DGS10", "T10Y2Y", "VIXCLS", "DFF")
    }
    company_facts: dict[str, object] = {}
    stock_instruments = tuple(
        item for item in universe.instruments
        if item.execution_asset_class is CandidateAssetClass.US_EQUITY
        and item.instrument_type == "common_stock"
    )
    if stock_instruments:
        sec = SECEdgarProvider()
        for instrument in stock_instruments:
            if instrument.issuer_cik is None:
                continue
            company_facts[instrument.symbol] = sec.fetch_company_facts(
                FilingQuery(
                    cik=instrument.issuer_cik,
                    as_of=as_of,
                    forms=("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"),
                    limit=10_000,
                )
            )
    provider_clock = client.clock()
    return {
        "bars": bars,
        "quotes": quotes,
        "macro": macro,
        "company_facts": company_facts,
        "provider_clock": provider_clock,
    }


def collect_paper_evidence(
    universe: FreePaperPilotUniverse,
    decision_as_of: datetime,
    *,
    probe: EvidenceProbe | None = None,
) -> Mapping[str, object]:
    """Collect one immutable evidence payload through an injectable provider boundary."""

    if not isinstance(universe, FreePaperPilotUniverse):
        raise TypeError("universe must be FreePaperPilotUniverse")
    as_of = _aware(decision_as_of, field_name="decision_as_of")
    payload = (probe or _default_probe)(universe, as_of)
    if not isinstance(payload, Mapping):
        raise ProductionPaperEvidenceError("paper evidence probe must return a mapping")
    for field_name in ("bars", "quotes", "macro"):
        if not isinstance(payload.get(field_name), Mapping):
            raise ProductionPaperEvidenceError(
                f"paper evidence payload is missing {field_name}"
            )
    normalized = dict(payload)
    normalized["_live_collection"] = probe is None
    return normalized


@dataclass(frozen=True, slots=True)
class ListedSecurityFeatures:
    symbol: str
    as_of: datetime
    current_price: float
    latest_observed_at: datetime
    one_month_return: float
    three_month_return: float
    six_month_return: float
    twelve_month_return: float
    annualized_volatility: float
    maximum_drawdown: float
    average_daily_dollar_volume: float
    long_run_annual_return: float
    rolling_annual_median: float
    rolling_success_rate: float
    bar_count: int
    evidence_identifiers: tuple[str, ...]
    moving_average_200: float = 0.0

    @property
    def momentum(self) -> float:
        return _clip(
            0.15 * self.one_month_return
            + 0.25 * self.three_month_return
            + 0.25 * self.six_month_return
            + 0.35 * self.twelve_month_return,
            -0.75,
            0.75,
        )

    @property
    def liquidity_score(self) -> float:
        return _clip(log10(max(self.average_daily_dollar_volume, 1.0)) / 9.0, 0.0, 1.0)


ListedWrapperFeatures = ListedSecurityFeatures


@dataclass(frozen=True, slots=True)
class PaperEvidenceBuildResult:
    candidates: tuple[CandidateDecisionRecord, ...]
    candidate_evidence: tuple[ProductionCandidateEvidence, ...]
    holding_evidence: tuple[ProductionHoldingEvidence, ...]
    exclusions: tuple[tuple[str, tuple[str, ...]], ...]
    macro: MacroSpecialistContext

    @property
    def candidate_evidence_by_identifier(self) -> dict[str, ProductionCandidateEvidence]:
        return {item.candidate_identifier: item for item in self.candidate_evidence}


_EXPOSURE_METADATA: dict[str, tuple[str, str, float]] = {
    "us_equity": ("us_equity", "growth_risk", 1.0),
    "international_equity": ("international_equity", "growth_risk", 0.9),
    "government_bonds": ("government_bonds", "duration_defensive", -0.5),
    "investment_grade_credit": ("investment_grade_credit", "credit", 0.35),
    "high_yield_credit": ("high_yield_credit", "credit", 0.7),
    "cash_treasury": ("cash_treasury", "cash", 0.0),
    "broad_commodities": ("commodities", "inflation_real_assets", 0.15),
    "gold": ("gold", "defensive_real_assets", -0.2),
    "foreign_exchange": ("foreign_exchange", "dollar", -0.15),
    "crypto": ("crypto_proxy", "high_beta_alternative", 1.0),
    "real_estate": ("real_estate", "rate_sensitive", 0.75),
    "managed_futures": ("managed_futures", "trend_alternative", 0.0),
    "option_strategies": ("option_strategy", "equity_income", 0.45),
    "volatility": ("volatility_proxy", "crisis_hedge", -1.0),
    "market_neutral_alternatives": ("market_neutral", "alternative", -0.1),
}

_EXPOSURE_ASSET_CLASSES: dict[str, CandidateAssetClass] = {
    "us_equity": CandidateAssetClass.US_EQUITY,
    "international_equity": CandidateAssetClass.INTERNATIONAL_EQUITY,
    "government_bonds": CandidateAssetClass.FIXED_INCOME,
    "investment_grade_credit": CandidateAssetClass.FIXED_INCOME,
    "high_yield_credit": CandidateAssetClass.FIXED_INCOME,
    "cash_treasury": CandidateAssetClass.CASH_EQUIVALENT,
    "broad_commodities": CandidateAssetClass.COMMODITY,
    "gold": CandidateAssetClass.COMMODITY,
    "foreign_exchange": CandidateAssetClass.FX,
    "crypto": CandidateAssetClass.CRYPTO,
    "real_estate": CandidateAssetClass.REAL_ESTATE,
    "managed_futures": CandidateAssetClass.ALTERNATIVE,
    "option_strategies": CandidateAssetClass.OPTION,
    "volatility": CandidateAssetClass.VOLATILITY,
    "market_neutral_alternatives": CandidateAssetClass.ALTERNATIVE,
}


def _history_depth(features: ListedSecurityFeatures) -> float:
    return _clip(features.bar_count / 2520.0, 0.10, 1.0)


def _scenario_probabilities(
    features: ListedSecurityFeatures,
    *,
    cash_expected_return: float,
    base_return: float,
) -> tuple[float, float, float]:
    momentum = features.momentum
    success_edge = features.rolling_success_rate - 0.50
    return_edge = base_return - cash_expected_return
    volatility = min(1.0, max(0.0, features.annualized_volatility))
    bull = _clip(
        0.20
        + 0.20 * max(0.0, success_edge)
        + 0.10 * max(0.0, momentum)
        + 0.05 * max(0.0, return_edge),
        0.10,
        0.40,
    )
    bear = _clip(
        0.20
        + 0.20 * max(0.0, -success_edge)
        + 0.12 * max(0.0, -momentum)
        + 0.08 * volatility,
        0.10,
        0.45,
    )
    if bull + bear > 0.70:
        scale = 0.70 / (bull + bear)
        bull = round(bull * scale, 8)
        bear = round(bear * scale, 8)
    base = round(1.0 - bull - bear, 8)
    return base, bull, bear


def _evidence_quality(
    features: ListedSecurityFeatures,
    *,
    data_age_hours: float,
) -> EvidenceQuality:
    depth = _history_depth(features)
    freshness = _clip(1.0 - data_age_hours / 48.0, 0.55, 0.96)
    liquidity = features.liquidity_score
    return EvidenceQuality(
        reliability=_clip(0.64 + 0.20 * depth + 0.05 * liquidity, 0.64, 0.89),
        freshness=freshness,
        relevance=_clip(0.72 + 0.12 * depth, 0.72, 0.86),
        independence=_clip(0.50 + 0.08 * depth, 0.50, 0.58),
        completeness=_clip(0.58 + 0.28 * depth, 0.58, 0.86),
        point_in_time_integrity=0.90,
    )


def _cost_assumptions(features: ListedSecurityFeatures) -> tuple[float, float]:
    illiquidity = 1.0 - features.liquidity_score
    volatility = min(1.0, max(0.0, features.annualized_volatility))
    transaction = round(2.0 + 8.0 * illiquidity, 4)
    slippage = round(2.0 + 12.0 * illiquidity + 10.0 * volatility, 4)
    return transaction, slippage


def _forecast_quality(
    features: ListedSecurityFeatures,
    *,
    distribution_anchor: float,
) -> tuple[float, float, float, float]:
    depth = _history_depth(features)
    volatility = min(1.0, max(0.0, features.annualized_volatility))
    anchor_gap = min(1.0, abs(features.momentum - distribution_anchor))
    calibration = _clip(0.42 + 0.30 * depth - 0.08 * volatility, 0.35, 0.72)
    agreement = _clip(0.45 + 0.24 * (1.0 - anchor_gap), 0.40, 0.69)
    stability = _clip(0.40 + 0.28 * depth + 0.18 * (1.0 - volatility), 0.40, 0.75)
    aggregate = _clip((calibration + agreement + stability) / 3.0, 0.35, 0.72)
    return aggregate, calibration, agreement, stability


def _metadata(instrument: FreePaperPilotInstrument) -> tuple[str, str, float]:
    return _EXPOSURE_METADATA.get(
        instrument.economic_exposure,
        (instrument.economic_exposure, instrument.economic_exposure, 0.0),
    )


def _bar_rows(
    symbol: str,
    raw: object,
    *,
    as_of: datetime,
) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ProductionPaperEvidenceError(f"historical bars are unavailable for {symbol}")
    selected: dict[datetime, dict[str, object]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        observed_at = _timestamp(item.get("t"), field_name=f"{symbol} bar timestamp")
        if observed_at > as_of:
            continue
        close = _number(item.get("c"), field_name=f"{symbol} close")
        volume = _number(item.get("v", 0.0), field_name=f"{symbol} volume")
        if close <= 0.0 or volume < 0.0:
            continue
        selected[observed_at] = {
            "t": observed_at,
            "c": close,
            "v": volume,
        }
    rows = tuple(selected[key] for key in sorted(selected))
    if len(rows) < _MINIMUM_BARS:
        raise ProductionPaperEvidenceError(
            f"{symbol} requires at least {_MINIMUM_BARS} point-in-time daily bars; found {len(rows)}"
        )
    return rows


def _period_return(closes: Sequence[float], periods: int) -> float:
    if len(closes) <= periods or closes[-periods - 1] <= 0.0:
        return 0.0
    return closes[-1] / closes[-periods - 1] - 1.0


def _features(
    symbol: str,
    raw_bars: object,
    quote: object,
    *,
    as_of: datetime,
    cash_expected_return: float,
    maximum_quote_age_minutes: int,
    maximum_future_skew_seconds: int = 0,
    future_reference_at: datetime | None = None,
) -> ListedSecurityFeatures:
    rows = _bar_rows(symbol, raw_bars, as_of=as_of)
    closes = [float(item["c"]) for item in rows]
    volumes = [float(item["v"]) for item in rows]
    if not isinstance(quote, Mapping):
        raise ProductionPaperEvidenceError(f"current quote is unavailable for {symbol}")
    quote_time = _timestamp(quote.get("t"), field_name=f"{symbol} quote timestamp")
    reference_time = (
        as_of
        if future_reference_at is None
        else _aware(future_reference_at, field_name="future_reference_at")
    )
    if maximum_future_skew_seconds >= 0:
        maximum_future_skew = timedelta(seconds=maximum_future_skew_seconds)
        if quote_time > reference_time + maximum_future_skew:
            raise ProductionPaperEvidenceError(f"{symbol} quote is future-known")
    effective_quote_time = min(quote_time, as_of)
    quote_age = as_of - effective_quote_time
    # Strategic analysis may use the latest official close when pre-market IEX
    # top-of-book evidence is older than the execution freshness limit. The
    # paper executor independently requires a current positive non-crossed quote.
    quote_is_current = quote_age <= timedelta(minutes=maximum_quote_age_minutes)
    bid = quote.get("bp")
    ask = quote.get("ap")
    quote_price: float | None = None
    if quote_is_current and isinstance(bid, (int, float)) and isinstance(ask, (int, float)):
        if float(bid) > 0.0 and float(ask) >= float(bid):
            quote_price = (float(bid) + float(ask)) / 2.0
    current_price = closes[-1] if quote_price is None else quote_price
    daily = [
        closes[index] / closes[index - 1] - 1.0
        for index in range(1, len(closes))
        if closes[index - 1] > 0.0
    ]
    annualized_volatility = pstdev(daily[-252:]) * sqrt(252.0) if len(daily) >= 2 else 0.0
    running_peak = closes[0]
    maximum_drawdown = 0.0
    for close in closes:
        running_peak = max(running_peak, close)
        maximum_drawdown = min(maximum_drawdown, close / running_peak - 1.0)
    years = max((rows[-1]["t"] - rows[0]["t"]).days / 365.25, 1.0)
    long_run = (closes[-1] / closes[0]) ** (1.0 / years) - 1.0
    rolling = [
        closes[index] / closes[index - 252] - 1.0
        for index in range(252, len(closes))
        if closes[index - 252] > 0.0
    ]
    rolling_median = median(rolling) if rolling else _period_return(closes, 252)
    success = (
        sum(value > cash_expected_return for value in rolling) / len(rolling)
        if rolling
        else (0.60 if rolling_median > cash_expected_return else 0.40)
    )
    adv = sum(
        closes[index] * volumes[index]
        for index in range(max(0, len(closes) - 20), len(closes))
    ) / min(20, len(closes))
    bar_material = [
        {
            "t": item["t"].isoformat(),
            "c": round(float(item["c"]), 12),
            "v": round(float(item["v"]), 4),
        }
        for item in rows
    ]
    quote_material = {
        "t": quote_time.isoformat(),
        "bp": None if bid is None else float(bid),
        "ap": None if ask is None else float(ask),
    }
    evidence = (
        (
            f"alpaca-iex-bars:{symbol}:{rows[0]['t'].isoformat()}:"
            f"{rows[-1]['t'].isoformat()}:{len(rows)}:{_evidence_digest(bar_material)}"
        ),
        f"alpaca-iex-quote:{symbol}:{quote_time.isoformat()}:{_evidence_digest(quote_material)}",
    )
    return ListedSecurityFeatures(
        symbol=symbol,
        as_of=as_of,
        current_price=round(current_price, 8),
        latest_observed_at=(max(rows[-1]["t"], effective_quote_time) if quote_is_current else rows[-1]["t"]),
        one_month_return=_period_return(closes, 21),
        three_month_return=_period_return(closes, 63),
        six_month_return=_period_return(closes, 126),
        twelve_month_return=_period_return(closes, 252),
        annualized_volatility=round(annualized_volatility, 8),
        maximum_drawdown=round(maximum_drawdown, 8),
        average_daily_dollar_volume=round(max(0.0, adv), 8),
        moving_average_200=round(sum(closes[-200:]) / min(200, len(closes)), 8),
        long_run_annual_return=_clip(long_run, -0.60, 1.50),
        rolling_annual_median=_clip(rolling_median, -0.60, 1.50),
        rolling_success_rate=_clip(success, 0.0, 1.0),
        bar_count=len(rows),
        evidence_identifiers=evidence,
    )


def _macro_value(raw: object, series: str) -> tuple[str, float]:
    value = raw.get(series) if isinstance(raw, Mapping) else None
    if isinstance(value, Mapping):
        date = str(value.get("date", "")).strip()
        number = value.get("value")
    else:
        date = str(getattr(value, "date", "")).strip()
        number = getattr(value, "value", None)
    if not date:
        raise ProductionPaperEvidenceError(f"FRED {series} observation date is unavailable")
    return date, _number(number, field_name=f"FRED {series} value")


def _macro_context(raw: object, *, as_of: datetime) -> tuple[MacroSpecialistContext, dict[str, float], tuple[str, ...]]:
    values: dict[str, float] = {}
    identifiers: list[str] = []
    for series in ("DGS10", "T10Y2Y", "VIXCLS", "DFF"):
        date, number = _macro_value(raw, series)
        try:
            observation_date = datetime.fromisoformat(date).date()
        except ValueError as error:
            raise ProductionPaperEvidenceError(
                f"FRED {series} observation date is invalid"
            ) from error
        if observation_date > as_of.date():
            raise ProductionPaperEvidenceError(
                f"FRED {series} observation is future-known"
            )
        if (as_of.date() - observation_date).days > 10:
            raise ProductionPaperEvidenceError(
                f"FRED {series} observation is stale"
            )
        values[series] = number
        identifiers.append(f"fred:{series}:{date}")
    ten_year = values["DGS10"]
    curve = values["T10Y2Y"]
    vix = values["VIXCLS"]
    policy_rate = values["DFF"]
    restrictive_rates = policy_rate >= 4.50 or ten_year >= 4.75
    easing_support = policy_rate <= 3.00 and curve >= 0.0
    if vix >= 30.0 or curve <= -0.50:
        regime = "risk_off"
        impact = -0.025
        tailwinds = ("Defensive exposures may benefit from elevated systemic stress",)
        headwinds = ("Risk assets face an inverted curve or elevated volatility",)
    elif restrictive_rates and vix > 20.0:
        regime = "restrictive_mixed"
        impact = -0.010
        tailwinds = ("Cash and short-duration carry remain comparatively supported",)
        headwinds = (
            "The policy rate or long yield is restrictive while volatility is elevated",
        )
    elif vix <= 20.0 and curve >= 0.0 and not restrictive_rates:
        regime = "constructive_growth"
        impact = 0.015
        tailwinds = ("Contained volatility and a non-inverted curve support risk taking",)
        headwinds = ()
    elif easing_support:
        regime = "easing_constructive"
        impact = 0.010
        tailwinds = ("Lower policy rates and a non-inverted curve support financial conditions",)
        headwinds = ()
    else:
        regime = "mixed"
        impact = 0.0
        tailwinds = ()
        headwinds = (
            "Long yields, curve shape, policy rates, and volatility signals are mixed",
        )
    if policy_rate >= 5.0:
        impact -= 0.005
    if ten_year >= 5.0:
        impact -= 0.005
    if easing_support and vix <= 25.0:
        impact += 0.005
    impact = _clip(impact, -0.04, 0.03)
    return (
        MacroSpecialistContext(
            as_of=as_of,
            regime=regime,
            expected_return_impact=impact,
            confidence=_clip(
                0.62
                + 0.04 * (curve >= 0.0)
                + 0.04 * (vix <= 25.0)
                + 0.04 * (policy_rate < 5.0)
                + 0.04 * (ten_year < 5.0),
                0.55,
                0.78,
            ),
            tailwinds=tailwinds,
            headwinds=headwinds,
            systemic_risks=(
                "Current macro relationships can change after policy or growth shocks",
            ),
            scenarios=(
                "Reclassify when long yields, curve shape, policy rates, or VIX change materially",
            ),
            evidence_identifiers=tuple(identifiers),
        ),
        values,
        tuple(identifiers),
    )


def _exposure_macro_impact(exposure: str, macro: MacroSpecialistContext) -> float:
    _sector, _bucket, risk_beta = _EXPOSURE_METADATA.get(exposure, (exposure, exposure, 0.0))
    return _clip(macro.expected_return_impact * risk_beta, -0.04, 0.04)


def _candidate_and_evidence(
    instrument: FreePaperPilotInstrument,
    features: ListedSecurityFeatures,
    *,
    universe: FreePaperPilotUniverse,
    as_of: datetime,
    cash_expected_return: float,
    macro: MacroSpecialistContext,
    macro_identifiers: tuple[str, ...],
    current_weight: float,
) -> tuple[CandidateDecisionRecord, ProductionCandidateEvidence]:
    sector, bucket, risk_beta = _metadata(instrument)
    macro_impact = _exposure_macro_impact(instrument.economic_exposure, macro)
    trend_anchor = features.momentum
    distribution_anchor = 0.5 * features.long_run_annual_return + 0.5 * features.rolling_annual_median
    base_return = _clip(
        0.55 * distribution_anchor + 0.35 * trend_anchor + macro_impact,
        -0.30,
        0.45,
    )
    if instrument.economic_exposure == "cash_treasury":
        base_return = cash_expected_return
    bull_return = _clip(
        base_return + max(0.05, features.annualized_volatility * 0.60),
        -0.05,
        0.90,
    )
    bear_return = _clip(
        base_return - max(0.08, features.annualized_volatility * 0.90),
        -0.85,
        0.05,
    )
    success = _clip(
        0.65 * features.rolling_success_rate
        + 0.20 * (1.0 if trend_anchor > cash_expected_return else 0.0)
        + 0.15 * (1.0 if base_return > cash_expected_return else 0.0),
        0.05,
        0.95,
    )
    data_age = max(0.0, (as_of - features.latest_observed_at).total_seconds() / 3600.0)
    quality = _evidence_quality(features, data_age_hours=data_age)
    base_probability, bull_probability, bear_probability = _scenario_probabilities(
        features,
        cash_expected_return=cash_expected_return,
        base_return=base_return,
    )
    transaction_cost_bps, slippage_bps = _cost_assumptions(features)
    aggregate_confidence, calibration_score, model_agreement, forecast_stability = (
        _forecast_quality(features, distribution_anchor=distribution_anchor)
    )
    current = max(0.0, current_weight)
    maximum = max(current, min(instrument.maximum_weight, 0.10))
    candidate_identifier = f"candidate:paper-pilot:{as_of.strftime('%Y%m%dT%H%M%S%fZ')}:{instrument.symbol}"
    market_ids = features.evidence_identifiers
    evidence_ids = tuple(dict.fromkeys((*market_ids, *macro_identifiers)))
    candidate = CandidateDecisionRecord(
        identifier=candidate_identifier,
        as_of=as_of,
        schema_version="paper-listed-wrapper-candidate.v1",
        instrument=CandidateInstrument(
            instrument_id=instrument.instrument_identifier,
            symbol=instrument.symbol,
            name=instrument.name,
            asset_class=instrument.execution_asset_class,
            venue=instrument.venue,
            country_code=instrument.country_code,
            average_daily_dollar_volume=features.average_daily_dollar_volume,
            data_age_hours=data_age,
            analytical_coverage=min(1.0, features.bar_count / 756.0),
            security_master_snapshot_identifier=f"alpaca-paper-assets:{as_of.strftime('%Y%m%dT%H%M%S%fZ')}",
            security_master_record_identifiers=(
                f"alpaca-paper-asset:{instrument.symbol}",
            ),
            instrument_type=instrument.instrument_type,
            economic_exposure_class=_EXPOSURE_ASSET_CLASSES.get(
                instrument.economic_exposure,
                instrument.execution_asset_class,
            ),
            leverage_multiplier=1.0,
            uses_derivatives=instrument.economic_exposure in {
                "managed_futures",
                "option_strategies",
                "volatility",
            },
            replication_method="us-listed-economic-exposure-wrapper",
        ),
        current_price=features.current_price,
        decision_horizon_days=365,
        base_case_return=base_return,
        bull_case_return=bull_return,
        bear_case_return=bear_return,
        base_case_probability=base_probability,
        bull_case_probability=bull_probability,
        bear_case_probability=bear_probability,
        estimated_fair_value=max(0.0, features.current_price * (1.0 + base_return)),
        expected_upside=max(0.0, bull_return),
        expected_downside=min(0.0, bear_return),
        probability_of_success=success,
        primary_catalysts=(
            f"Twelve-month return is {features.twelve_month_return:.2%} and the macro regime is {macro.regime}",
        ),
        key_risks=(
            f"Annualized volatility is {features.annualized_volatility:.2%} and maximum drawdown is {features.maximum_drawdown:.2%}",
        ),
        critical_assumptions=(
            "The listed wrapper continues to represent its governed economic exposure",
            "Point-in-time return distributions remain informative over the one-year horizon",
        ),
        invalidation_conditions=(
            "Twelve-month momentum reverses materially",
            "The macro regime or rolling return distribution changes materially",
        ),
        supporting_evidence=(
            f"{features.bar_count} authenticated point-in-time IEX daily bars",
            f"Rolling one-year median return is {features.rolling_annual_median:.2%}",
        ),
        contradictory_evidence=(
            ("Current composite momentum is negative",) if features.momentum < 0.0 else ()
        ),
        evidence_quality=quality,
        liquidity_score=features.liquidity_score,
        transaction_cost_bps=transaction_cost_bps,
        slippage_bps=slippage_bps,
        opportunity_cost_return=cash_expected_return,
        expected_portfolio_contribution=base_return * maximum,
        current_portfolio_weight=current,
        maximum_position_weight=maximum,
        monitoring_indicators=(
            "one_month_return",
            "twelve_month_return",
            "annualized_volatility",
            "maximum_drawdown",
            "macro_regime",
        ),
        review_at=as_of + timedelta(days=30),
        evidence_identifiers=evidence_ids,
        model_versions=(_MODEL_VERSION,),
        evidence_dependencies=(
            EvidenceDependency(
                identifier=f"derived-market-distribution:{instrument.symbol}:{as_of.date().isoformat()}",
                parent_identifiers=market_ids,
            ),
            EvidenceDependency(
                identifier=f"derived-macro-translation:{instrument.symbol}:{as_of.date().isoformat()}",
                parent_identifiers=macro_identifiers,
            ),
        ),
    )
    market_impact = _clip(features.momentum * 0.10, -0.08, 0.08)
    market = MarketSpecialistContext(
        as_of=as_of,
        market_regime="positive_trend" if features.momentum >= 0.0 else "negative_trend",
        expected_return_impact=market_impact,
        confidence=min(0.68, quality.score),
        trend=_clip(features.twelve_month_return, -1.0, 1.0),
        momentum=_clip(features.momentum, -1.0, 1.0),
        breadth=0.0,
        liquidity=_clip(features.liquidity_score * 2.0 - 1.0, -1.0, 1.0),
        positioning=0.0,
        evidence=(
            f"One-month return={features.one_month_return:.2%}",
            f"Six-month return={features.six_month_return:.2%}",
            f"Twelve-month return={features.twelve_month_return:.2%}",
            "Cross-sectional market breadth is unavailable in the free IEX pilot",
            "Independent positioning data is unavailable in the free-data pilot",
        ),
        risks=(
            f"Realized annualized volatility={features.annualized_volatility:.2%}",
            "IEX is a limited free-data feed rather than consolidated full-market evidence",
            "Breadth and positioning are unavailable rather than neutral",
        ),
        entry_conditions=(
            "The latest quote remains current and non-crossed at execution",
            "Trend and volatility remain inside the governed review range",
        ),
        evidence_identifiers=market_ids,
    )
    forecast = CrossAssetForecastSpecialistContext(
        as_of=as_of,
        forecast_horizon_days=365,
        scenarios=(
            ForecastScenarioAssessment(
                label="base macro-distribution case",
                probability=base_probability,
                candidate_return_impact=macro_impact,
                expected_path_drawdown=min(0.0, features.maximum_drawdown * 0.50),
                rationale="Current macro regime translated through disclosed exposure sensitivity",
                evidence_identifiers=macro_identifiers,
            ),
            ForecastScenarioAssessment(
                label="bull distribution case",
                probability=bull_probability,
                candidate_return_impact=max(0.0, min(0.04, features.annualized_volatility * 0.15)),
                expected_path_drawdown=min(0.0, features.maximum_drawdown * 0.25),
                rationale="Supportive tail of the independently measured rolling return distribution",
                evidence_identifiers=market_ids,
            ),
            ForecastScenarioAssessment(
                label="bear distribution case",
                probability=bear_probability,
                candidate_return_impact=min(-0.01, -features.annualized_volatility * 0.20),
                expected_path_drawdown=min(-0.01, bear_return),
                rationale="Adverse volatility and drawdown path from current point-in-time evidence",
                evidence_identifiers=market_ids,
            ),
        ),
        aggregate_confidence=aggregate_confidence,
        calibration_score=calibration_score,
        model_agreement=model_agreement,
        forecast_stability=forecast_stability,
        path_drawdown_probability=_clip(features.annualized_volatility, 0.0, 1.0),
        cross_asset_signals=(
            f"Macro regime={macro.regime}",
            f"Risk sensitivity={risk_beta:+.2f}",
        ),
        contradictory_evidence=(
            ("Negative momentum conflicts with the central upside case",)
            if features.momentum < 0.0
            else ()
        ),
        limitations=(
            "The free-data forecast uses evidence-derived, versioned pilot priors rather than calibrated institutional probabilities",
            "Shared market observations are dependency-disclosed and do not count as independent sources",
        ),
        change_conditions=(
            "Refresh after a material macro, volatility, or trend-regime change",
        ),
        model_versions=(_FORECAST_VERSION,),
        evidence_identifiers=evidence_ids,
    )
    valuation_anchor = features.rolling_annual_median
    valuation_impact = _clip((valuation_anchor - base_return) * 0.25, -0.05, 0.05)
    valuation = AssetValuationSpecialistContext(
        as_of=as_of,
        asset_class=instrument.execution_asset_class,
        expected_return_impact=valuation_impact,
        confidence=_clip(0.42 + 0.25 * _history_depth(features), 0.42, 0.67),
        valuation_evidence=(
            f"Rolling one-year median return={valuation_anchor:.2%}",
            f"Long-run annualized return={features.long_run_annual_return:.2%}",
            f"Distribution-implied central value={features.current_price * (1.0 + valuation_anchor):.4f}",
        ),
        contradictory_evidence=(
            "Listed-wrapper distribution valuation does not replace issuer or underlying-asset fundamentals",
        ),
        critical_assumptions=(
            "The wrapper remains liquid and continues to track the intended exposure",
        ),
        risks=(
            "Historical return anchors can be distorted by structural breaks and changing carry",
        ),
        limitations=(
            "This is an evidence-derived distribution prior and not intrinsic-value certainty",
        ),
        change_conditions=(
            "Revalue when the rolling annual distribution or tracking structure changes materially",
        ),
        evidence_identifiers=market_ids,
    )
    lineage = GovernedEvidenceLineage(
        certification_identifier=f"certification:paper-listed-wrapper:{instrument.symbol}:{as_of.strftime('%Y%m%dT%H%M%S%fZ')}",
        certification_state=EvidenceCertificationState.APPROVED,
        certification_expires_at=as_of + timedelta(days=2),
        fresh_until=as_of + timedelta(days=1),
        evidence_identifiers=evidence_ids,
        source_versions=(
            (f"ALPACA_IEX:{instrument.symbol}", features.latest_observed_at.isoformat()),
            (
                "FRED_MACRO",
                hashlib.sha256(
                    "|".join(macro_identifiers).encode("utf-8")
                ).hexdigest(),
            ),
        ),
        model_versions=(
            ("candidate", _MODEL_VERSION),
            ("forecast", _FORECAST_VERSION),
            ("valuation", _VALUATION_VERSION),
        ),
    )
    governed = ProductionCandidateEvidence(
        identifier=f"candidate-evidence:{candidate_identifier}",
        candidate_identifier=candidate_identifier,
        symbol=instrument.symbol,
        as_of=as_of,
        knowledge_cutoff=as_of,
        analysis_completed_at=as_of,
        macro=macro,
        market=market,
        company=None,
        exposure_profile=CandidateExposureProfile(
            candidate_identifier=candidate_identifier,
            sector=sector,
            factor_loadings=(
                ("trend", _clip(features.momentum, -1.0, 1.0)),
                ("risk_sensitivity", _clip(risk_beta, -1.0, 1.0)),
            ),
            correlation_bucket=bucket,
        ),
        fundamental_evidence_identifiers=market_ids,
        fundamental_model_version=_VALUATION_VERSION,
        lineage=lineage,
        forecast=forecast,
        asset_valuation=valuation,
    )
    return candidate, governed



def _company_candidate_and_evidence(
    instrument: FreePaperPilotInstrument,
    features: ListedSecurityFeatures,
    *,
    company_facts: object,
    benchmark: ListedSecurityFeatures,
    as_of: datetime,
    cash_expected_return: float,
    macro: MacroSpecialistContext,
    macro_values: Mapping[str, float],
    macro_identifiers: tuple[str, ...],
    current_weight: float,
) -> tuple[CandidateDecisionRecord, ProductionCandidateEvidence]:
    if instrument.issuer_cik is None:
        raise ProductionPaperEvidenceError(
            f"SEC issuer identity is unavailable for {instrument.symbol}"
        )
    if not isinstance(company_facts, tuple):
        raise ProductionPaperEvidenceError(
            f"SEC company facts are unavailable for {instrument.symbol}"
        )
    try:
        history = CompanyFactNormalizer(minimum_annual_periods=2).normalize(
            company_facts,
            as_of=as_of,
        )
    except (TypeError, ValueError) as error:
        raise ProductionPaperEvidenceError(
            f"SEC company facts cannot be normalized for {instrument.symbol}: {error}"
        ) from error
    shares = history.latest.diluted_shares
    if shares is None or shares <= 0.0:
        raise ProductionPaperEvidenceError(
            f"diluted shares are unavailable for {instrument.symbol}"
        )
    market = CompanyMarketSnapshot(
        as_of=as_of,
        current_price=features.current_price,
        market_cap=features.current_price * shares,
        shares_outstanding=shares,
        dividend_per_share=0.0,
        six_month_return=features.six_month_return,
        twelve_month_return=features.twelve_month_return,
        benchmark_twelve_month_return=benchmark.twelve_month_return,
        annualized_volatility=features.annualized_volatility,
        maximum_drawdown=features.maximum_drawdown,
        moving_average_200=features.moving_average_200,
        average_daily_dollar_volume=features.average_daily_dollar_volume,
        data_age_hours=max(
            0.0,
            (as_of - features.latest_observed_at).total_seconds() / 3600.0,
        ),
        evidence_identifiers=features.evidence_identifiers,
    )
    curve = float(macro_values.get("T10Y2Y", 0.0))
    vix = float(macro_values.get("VIXCLS", 20.0))
    policy_rate = float(macro_values.get("DFF", 4.0))
    ten_year = float(macro_values.get("DGS10", 4.0))
    regime = CompanyRegimeContext(
        as_of=as_of,
        growth_support=_clip(0.35 * (curve / 2.0) - 0.20 * ((policy_rate - 3.0) / 3.0)),
        liquidity_support=_clip((4.0 - policy_rate) / 3.0),
        credit_support=_clip(0.5 * (curve / 2.0) + 0.5 * ((5.0 - ten_year) / 3.0)),
        market_risk_support=_clip((25.0 - vix) / 15.0),
        industry_cyclicality=0.50,
        duration_sensitivity=0.50,
        evidence_identifiers=macro_identifiers,
    )
    analysis = CompanyAnalysisEngine().analyze(
        symbol=instrument.symbol,
        history=history,
        market=market,
        regime=regime,
    )
    transaction_cost_bps, slippage_bps = _cost_assumptions(features)
    maximum = max(current_weight, instrument.maximum_weight)
    candidate = CompanyCandidateBuilder().build(
        analysis,
        instrument_id=instrument.instrument_identifier,
        venue=instrument.venue,
        security_master_snapshot_identifier=(
            f"sec-alpaca-company-master:{as_of.strftime('%Y%m%dT%H%M%S%fZ')}"
        ),
        security_master_record_identifiers=(
            f"sec-company:{instrument.issuer_cik}:{instrument.symbol}",
            f"alpaca-paper-asset:{instrument.symbol}",
        ),
        opportunity_cost_return=cash_expected_return,
        maximum_position_weight=maximum,
        current_portfolio_weight=current_weight,
        transaction_cost_bps=transaction_cost_bps,
        slippage_bps=slippage_bps,
    )
    # Scenario probabilities are evidence-derived for the production lane rather
    # than inherited from the generic company-analysis prior.
    base_probability, bull_probability, bear_probability = _scenario_probabilities(
        features,
        cash_expected_return=cash_expected_return,
        base_return=candidate.base_case_return,
    )
    success = _clip(
        0.45
        + 0.20 * analysis.overall_score
        + 0.15 * analysis.confidence
        + 0.20 * features.rolling_success_rate,
        0.05,
        0.95,
    )
    instrument_contract = replace(
        candidate.instrument,
        name=instrument.name,
        instrument_type="common_stock",
        economic_exposure_class=CandidateAssetClass.US_EQUITY,
        replication_method=(
            "direct-common-equity-scaled"
            if current_weight > 0.0
            else "direct-common-equity-exploratory"
        ),
    )
    candidate = replace(
        candidate,
        schema_version="paper-company-equity-candidate.v1",
        instrument=instrument_contract,
        base_case_probability=base_probability,
        bull_case_probability=bull_probability,
        bear_case_probability=bear_probability,
        probability_of_success=success,
        maximum_position_weight=maximum,
        expected_portfolio_contribution=round(
            candidate.base_case_return * maximum,
            8,
        ),
        model_versions=tuple(
            dict.fromkeys((*candidate.model_versions, _COMPANY_EVIDENCE_VERSION))
        ),
    )
    market_context = MarketSpecialistContext(
        as_of=as_of,
        market_regime=(
            "company_relative_strength"
            if features.twelve_month_return >= benchmark.twelve_month_return
            else "company_relative_weakness"
        ),
        expected_return_impact=_clip(
            0.06 * (features.twelve_month_return - benchmark.twelve_month_return)
            + 0.04 * features.momentum,
            -0.08,
            0.08,
        ),
        confidence=min(0.80, analysis.evidence_quality.score),
        trend=_clip(features.twelve_month_return),
        momentum=_clip(features.momentum),
        breadth=0.0,
        liquidity=_clip(features.liquidity_score * 2.0 - 1.0),
        positioning=0.0,
        evidence=(
            f"Company twelve-month return={features.twelve_month_return:.2%}",
            f"VTI twelve-month return={benchmark.twelve_month_return:.2%}",
            f"Company relative strength={features.twelve_month_return - benchmark.twelve_month_return:.2%}",
            "Cross-sectional discovery ranked the full SEC/Alpaca eligible company set",
            "Independent positioning data is unavailable in the free-data pilot",
        ),
        risks=(
            f"Realized annualized volatility={features.annualized_volatility:.2%}",
            f"Maximum historical drawdown={features.maximum_drawdown:.2%}",
            "IEX is a limited feed and company facts are periodic rather than continuous",
        ),
        entry_conditions=(
            "The company remains in the daily broad-equity discovery set",
            "Execution receives a current positive non-crossed quote",
        ),
        evidence_identifiers=tuple(
            dict.fromkeys((*features.evidence_identifiers, *analysis.evidence_identifiers))
        ),
    )
    aggregate_confidence, calibration_score, model_agreement, forecast_stability = (
        _forecast_quality(features, distribution_anchor=candidate.base_case_return)
    )
    forecast = CrossAssetForecastSpecialistContext(
        as_of=as_of,
        forecast_horizon_days=365,
        scenarios=(
            ForecastScenarioAssessment(
                label="company base case",
                probability=base_probability,
                candidate_return_impact=_exposure_macro_impact("us_equity", macro),
                expected_path_drawdown=min(0.0, features.maximum_drawdown * 0.50),
                rationale="Normalized SEC fundamentals, market trend, and current macro regime",
                evidence_identifiers=analysis.evidence_identifiers,
            ),
            ForecastScenarioAssessment(
                label="company upside case",
                probability=bull_probability,
                candidate_return_impact=max(0.0, candidate.bull_case_return - candidate.base_case_return),
                expected_path_drawdown=min(0.0, features.maximum_drawdown * 0.25),
                rationale="Fundamental improvement and persistent relative strength",
                evidence_identifiers=features.evidence_identifiers,
            ),
            ForecastScenarioAssessment(
                label="company downside case",
                probability=bear_probability,
                candidate_return_impact=min(-0.01, candidate.bear_case_return - candidate.base_case_return),
                expected_path_drawdown=min(-0.01, candidate.bear_case_return),
                rationale="Fundamental disappointment, volatility, or relative-strength reversal",
                evidence_identifiers=tuple(
                    dict.fromkeys((*features.evidence_identifiers, *macro_identifiers))
                ),
            ),
        ),
        aggregate_confidence=min(aggregate_confidence, analysis.confidence),
        calibration_score=calibration_score,
        model_agreement=model_agreement,
        forecast_stability=forecast_stability,
        path_drawdown_probability=_clip(features.annualized_volatility, 0.0, 1.0),
        cross_asset_signals=(
            f"Macro regime={macro.regime}",
            f"VTI-relative strength={features.twelve_month_return - benchmark.twelve_month_return:+.2%}",
        ),
        contradictory_evidence=tuple(candidate.contradictory_evidence),
        limitations=(
            "Company forecasts remain versioned hypotheses rather than performance guarantees",
            "Free IEX and public SEC evidence do not include analyst estimate revisions",
        ),
        change_conditions=(
            "Refresh after new SEC filings, a relative-strength reversal, or a material macro change",
        ),
        model_versions=(_FORECAST_VERSION, analysis.analysis_version),
        evidence_identifiers=tuple(
            dict.fromkeys((*candidate.evidence_identifiers, *macro_identifiers))
        ),
    )
    evidence_ids = tuple(
        dict.fromkeys((*candidate.evidence_identifiers, *analysis.evidence_identifiers, *macro_identifiers))
    )
    lineage = GovernedEvidenceLineage(
        certification_identifier=(
            f"certification:paper-company-equity:{instrument.symbol}:"
            f"{as_of.strftime('%Y%m%dT%H%M%S%fZ')}"
        ),
        certification_state=EvidenceCertificationState.APPROVED,
        certification_expires_at=as_of + timedelta(days=2),
        fresh_until=as_of + timedelta(days=1),
        evidence_identifiers=evidence_ids,
        source_versions=(
            (f"ALPACA_IEX:{instrument.symbol}", features.latest_observed_at.isoformat()),
            (f"SEC_COMPANY_FACTS:{instrument.issuer_cik}", history.latest.available_at.isoformat()),
            ("FRED_MACRO", hashlib.sha256("|".join(macro_identifiers).encode("utf-8")).hexdigest()),
        ),
        model_versions=(
            ("company_normalization", history.normalization_version),
            ("company_analysis", analysis.analysis_version),
            ("company_candidate", _COMPANY_EVIDENCE_VERSION),
            ("forecast", _FORECAST_VERSION),
        ),
    )
    governed = ProductionCandidateEvidence(
        identifier=f"candidate-evidence:{candidate.identifier}",
        candidate_identifier=candidate.identifier,
        symbol=instrument.symbol,
        as_of=as_of,
        knowledge_cutoff=as_of,
        analysis_completed_at=as_of,
        macro=macro,
        market=market_context,
        company=analysis,
        exposure_profile=CandidateExposureProfile(
            candidate_identifier=candidate.identifier,
            sector="us_equity_company",
            factor_loadings=(
                ("quality", analysis.factor(CompanyFactor.QUALITY).score),
                ("growth", analysis.factor(CompanyFactor.GROWTH).score),
                ("momentum", analysis.factor(CompanyFactor.MOMENTUM).score),
                ("market_beta", 1.0),
            ),
            correlation_bucket="single_name_equity",
        ),
        fundamental_evidence_identifiers=analysis.evidence_identifiers,
        fundamental_model_version=analysis.analysis_version,
        lineage=lineage,
        forecast=forecast,
        asset_valuation=None,
    )
    return candidate, governed


def _holding_evidence(
    position,
    features: ListedSecurityFeatures,
    instrument: FreePaperPilotInstrument,
    *,
    as_of: datetime,
    cash_expected_return: float,
    macro: MacroSpecialistContext,
    macro_identifiers: tuple[str, ...],
) -> ProductionHoldingEvidence:
    sector, bucket, risk_beta = _metadata(instrument)
    expected_return = _clip(
        0.60 * features.rolling_annual_median
        + 0.30 * features.momentum
        + _exposure_macro_impact(instrument.economic_exposure, macro),
        -0.50,
        0.60,
    )
    evidence_ids = tuple(dict.fromkeys((*features.evidence_identifiers, *macro_identifiers)))
    lineage = GovernedEvidenceLineage(
        certification_identifier=f"certification:paper-holding:{position.symbol}:{as_of.strftime('%Y%m%dT%H%M%S%fZ')}",
        certification_state=EvidenceCertificationState.APPROVED,
        certification_expires_at=as_of + timedelta(days=2),
        fresh_until=as_of + timedelta(days=1),
        evidence_identifiers=evidence_ids,
        source_versions=(
            (f"ALPACA_IEX:{position.symbol}", features.latest_observed_at.isoformat()),
            (
                "FRED_MACRO",
                hashlib.sha256(
                    "|".join(macro_identifiers).encode("utf-8")
                ).hexdigest(),
            ),
        ),
        model_versions=(("holding_expected_return", _MODEL_VERSION),),
    )
    return ProductionHoldingEvidence(
        identifier=f"holding-evidence:{position.symbol}:{as_of.strftime('%Y%m%dT%H%M%S%fZ')}",
        symbol=position.symbol,
        as_of=as_of,
        knowledge_cutoff=as_of,
        expected_return=expected_return,
        evidence_quality=_evidence_quality(
            features,
            data_age_hours=max(
                0.0,
                (as_of - features.latest_observed_at).total_seconds() / 3600.0,
            ),
        ).score,
        liquidity_score=features.liquidity_score,
        sector=sector,
        factor_loadings=(
            ("trend", _clip(features.momentum, -1.0, 1.0)),
            ("risk_sensitivity", _clip(risk_beta, -1.0, 1.0)),
        ),
        correlation_bucket=bucket,
        average_daily_dollar_volume=features.average_daily_dollar_volume,
        transaction_cost_bps=_cost_assumptions(features)[0],
        slippage_bps=_cost_assumptions(features)[1],
        minimum_weight=0.0,
        funding_eligible=True,
        lineage=lineage,
    )


def build_paper_evidence(
    *,
    universe: FreePaperPilotUniverse,
    decision_as_of: datetime,
    cash_expected_return: float,
    portfolio: CanonicalPortfolioSnapshot,
    payload: Mapping[str, object],
) -> PaperEvidenceBuildResult:
    """Build complete candidate and current-holding evidence without decision authority."""

    as_of = _aware(decision_as_of, field_name="decision_as_of")
    if portfolio.as_of != as_of:
        raise ProductionPaperEvidenceError(
            "portfolio and paper evidence must share the exact decision timestamp"
        )
    bars = payload.get("bars")
    quotes = payload.get("quotes")
    raw_macro = payload.get("macro")
    company_facts = payload.get("company_facts", {})
    live_collection = payload.get("_live_collection") is True
    maximum_future_skew_seconds = -1 if live_collection else 0
    future_reference_at = as_of
    if live_collection:
        raw_provider_clock = payload.get("provider_clock")
        if not isinstance(raw_provider_clock, Mapping):
            raise ProductionPaperEvidenceError(
                "live paper evidence payload is missing the Alpaca market clock"
            )
        future_reference_at = _timestamp(
            raw_provider_clock.get("timestamp"),
            field_name="Alpaca market clock timestamp",
        )
        if abs((future_reference_at - as_of).total_seconds()) > 900:
            raise ProductionPaperEvidenceError(
                "Alpaca market clock differs from the collection-complete decision timestamp by more than 15 minutes"
            )
    if not isinstance(bars, Mapping) or not isinstance(quotes, Mapping):
        raise ProductionPaperEvidenceError("bars and quotes must be mappings")
    if not isinstance(company_facts, Mapping):
        raise ProductionPaperEvidenceError("company_facts must be a mapping")
    macro, macro_values, macro_ids = _macro_context(raw_macro, as_of=as_of)
    instrument_by_symbol = {item.symbol: item for item in universe.instruments}
    unknown_holdings = sorted(
        {item.symbol for item in portfolio.positions} - set(instrument_by_symbol)
    )
    if unknown_holdings:
        raise ProductionPaperEvidenceError(
            f"canonical holdings are outside the governed paper universe: {unknown_holdings}"
        )
    nav = portfolio.nav
    if nav <= 0.0:
        raise ProductionPaperEvidenceError("canonical portfolio NAV must be positive")
    current_weights = {
        item.symbol: round(item.market_value / nav, 8)
        for item in portfolio.positions
    }
    features_by_symbol: dict[str, ListedSecurityFeatures] = {}
    exclusions: list[tuple[str, tuple[str, ...]]] = []
    for instrument in universe.instruments:
        try:
            features_by_symbol[instrument.symbol] = _features(
                instrument.symbol,
                bars.get(instrument.symbol),
                quotes.get(instrument.symbol),
                as_of=as_of,
                cash_expected_return=cash_expected_return,
                maximum_quote_age_minutes=universe.maximum_quote_age_minutes,
                maximum_future_skew_seconds=maximum_future_skew_seconds,
                future_reference_at=future_reference_at,
            )
        except (ProductionPaperEvidenceError, TypeError, ValueError) as error:
            if instrument.symbol in current_weights:
                raise ProductionPaperEvidenceError(
                    f"mandatory holding evidence failed for {instrument.symbol}: {error}"
                ) from error
            exclusions.append(
                (
                    instrument.instrument_identifier,
                    (f"Certified listed-wrapper evidence is incomplete: {error}",),
                )
            )
    candidates: list[CandidateDecisionRecord] = []
    candidate_evidence: list[ProductionCandidateEvidence] = []
    candidate_by_symbol: dict[str, CandidateDecisionRecord] = {}
    benchmark = features_by_symbol.get("VTI")
    if benchmark is None:
        raise ProductionPaperEvidenceError("VTI benchmark evidence is mandatory")
    for instrument in universe.instruments:
        features = features_by_symbol.get(instrument.symbol)
        if features is None:
            continue
        try:
            if (
                instrument.execution_asset_class is CandidateAssetClass.US_EQUITY
                and instrument.instrument_type == "common_stock"
            ):
                candidate, governed = _company_candidate_and_evidence(
                    instrument,
                    features,
                    company_facts=company_facts.get(instrument.symbol),
                    benchmark=benchmark,
                    as_of=as_of,
                    cash_expected_return=cash_expected_return,
                    macro=macro,
                    macro_values=macro_values,
                    macro_identifiers=macro_ids,
                    current_weight=current_weights.get(instrument.symbol, 0.0),
                )
            else:
                candidate, governed = _candidate_and_evidence(
                    instrument,
                    features,
                    universe=universe,
                    as_of=as_of,
                    cash_expected_return=cash_expected_return,
                    macro=macro,
                    macro_identifiers=macro_ids,
                    current_weight=current_weights.get(instrument.symbol, 0.0),
                )
        except (ProductionPaperEvidenceError, TypeError, ValueError) as error:
            if instrument.symbol in current_weights:
                raise ProductionPaperEvidenceError(
                    f"mandatory holding evidence failed for {instrument.symbol}: {error}"
                ) from error
            exclusions.append(
                (
                    instrument.instrument_identifier,
                    (f"Certified company evidence is incomplete: {error}",),
                )
            )
            continue
        candidates.append(candidate)
        candidate_evidence.append(governed)
        candidate_by_symbol[instrument.symbol] = candidate
    holding_values: list[ProductionHoldingEvidence] = []
    for position in portfolio.positions:
        instrument = instrument_by_symbol[position.symbol]
        features = features_by_symbol[position.symbol]
        company_candidate = candidate_by_symbol.get(position.symbol)
        if (
            instrument.execution_asset_class is CandidateAssetClass.US_EQUITY
            and company_candidate is not None
        ):
            governed = next(
                item for item in candidate_evidence
                if item.candidate_identifier == company_candidate.identifier
            )
            transaction_cost_bps, slippage_bps = _cost_assumptions(features)
            holding_values.append(
                ProductionHoldingEvidence(
                    identifier=f"holding-evidence:{position.symbol}:{as_of.strftime('%Y%m%dT%H%M%S%fZ')}",
                    symbol=position.symbol,
                    as_of=as_of,
                    knowledge_cutoff=as_of,
                    expected_return=company_candidate.net_expected_return,
                    evidence_quality=company_candidate.evidence_quality.score,
                    liquidity_score=company_candidate.liquidity_score,
                    sector=governed.exposure_profile.sector,
                    factor_loadings=governed.exposure_profile.factor_loadings,
                    correlation_bucket=governed.exposure_profile.correlation_bucket,
                    average_daily_dollar_volume=features.average_daily_dollar_volume,
                    transaction_cost_bps=transaction_cost_bps,
                    slippage_bps=slippage_bps,
                    minimum_weight=0.0,
                    funding_eligible=True,
                    lineage=governed.lineage,
                )
            )
        else:
            holding_values.append(
                _holding_evidence(
                    position,
                    features,
                    instrument,
                    as_of=as_of,
                    cash_expected_return=cash_expected_return,
                    macro=macro,
                    macro_identifiers=macro_ids,
                )
            )
    holding_evidence = tuple(holding_values)
    return PaperEvidenceBuildResult(
        candidates=tuple(candidates),
        candidate_evidence=tuple(candidate_evidence),
        holding_evidence=holding_evidence,
        exclusions=tuple(exclusions),
        macro=macro,
    )


__all__ = [
    "EvidenceProbe",
    "ListedSecurityFeatures",
    "PaperEvidenceBuildResult",
    "ProductionPaperEvidenceError",
    "build_paper_evidence",
    "collect_paper_evidence",
]
