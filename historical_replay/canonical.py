"""Research-only walk-forward replay through the production CanonicalCIOCycle.

This adapter translates immutable historical records into the same candidate,
specialist, opportunity, and portfolio contracts used by the production CIO.
It never creates execution authority, mutates the canonical paper portfolio, or
promotes policy. Non-strict public bridges remain visibly research-only.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from application.cio_cycle import (
    CandidateCycleContext,
    CandidateExposureProfile,
    CanonicalCIOCycle,
    CyclePortfolioState,
)
from cio import (
    CIOAction,
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
)
from committee.specialists import (
    AssetValuationSpecialistContext,
    CrossAssetForecastSpecialistContext,
    ForecastScenarioAssessment,
    MacroSpecialistContext,
    MarketSpecialistContext,
)
from opportunity import AlternativeKind, AlternativeUse, OpportunitySetContext
from portfolio.construction_api import ConstructionStatus, PortfolioAsset

from .features import market_features
from .models import HistoricalRecord, iso_timestamp
from .replay import replay_dates
from .store import HistoricalStore

UTC = timezone.utc
_DEFAULT_ETFS = {
    "SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "TLT", "IEF", "LQD",
    "HYG", "GLD", "SLV", "USO", "VNQ",
}
_SECTORS = {
    "AAPL": "technology", "MSFT": "technology", "NVDA": "technology",
    "AMZN": "consumer_discretionary", "GOOGL": "communication_services",
    "META": "communication_services", "TSLA": "consumer_discretionary",
    "JPM": "financials", "XOM": "energy",
}


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def _decision_time(value: date) -> datetime:
    return datetime.combine(value, time(23, 59, 59), tzinfo=UTC)


def _symbol(value: object) -> str:
    raw = str(value or "").strip().upper()
    return raw[:-3] if raw.endswith(".US") else raw


def _asset_class(symbol: str, raw_symbol: str) -> CandidateAssetClass:
    if "-USD" in raw_symbol:
        return CandidateAssetClass.CRYPTO
    if symbol in _DEFAULT_ETFS:
        return CandidateAssetClass.US_ETF
    return CandidateAssetClass.US_EQUITY


def _metadata(symbol: str, raw_symbol: str) -> tuple[str, str, str, str]:
    asset = _asset_class(symbol, raw_symbol)
    if asset is CandidateAssetClass.CRYPTO:
        return "digital_assets", "crypto", "COINBASE", "spot_crypto"
    if asset is CandidateAssetClass.US_ETF:
        if symbol in {"TLT", "IEF", "LQD", "HYG"}:
            return "fixed_income", "rates_credit", "STOOQ", "etf"
        if symbol in {"GLD", "SLV", "USO"}:
            return "commodities", "real_assets", "STOOQ", "etf"
        if symbol == "VNQ":
            return "real_estate", "real_assets", "STOOQ", "etf"
        if symbol in {"EFA", "EEM"}:
            return "international_equity", "international_equity", "STOOQ", "etf"
        return "broad_market", "us_equity", "STOOQ", "etf"
    sector = _SECTORS.get(symbol, "unclassified_equity")
    return sector, f"us_equity:{sector}", "STOOQ", "equity"


def _price_records(records: tuple[HistoricalRecord, ...]) -> dict[str, list[HistoricalRecord]]:
    grouped: dict[str, list[HistoricalRecord]] = {}
    for record in records:
        if "close" not in record.payload or not record.payload.get("symbol"):
            continue
        grouped.setdefault(_symbol(record.payload.get("symbol")), []).append(record)
    for values in grouped.values():
        values.sort(key=lambda item: (item.observed_datetime, item.record_id))
    return grouped


def _average_dollar_volume(records: list[HistoricalRecord]) -> float:
    values: list[float] = []
    for record in records[-20:]:
        close = record.payload.get("close")
        volume = record.payload.get("volume")
        if isinstance(close, (int, float)) and isinstance(volume, (int, float)):
            values.append(max(0.0, float(close) * float(volume)))
    return sum(values) / len(values) if values else 0.0


def _cash_return(records: tuple[HistoricalRecord, ...], cutoff: datetime) -> tuple[float, str]:
    candidates = [
        item for item in records
        if item.dataset == "series.fedfunds" and item.available_datetime <= cutoff
    ]
    if not candidates:
        return 0.0, f"historical-replay:cash-rate-unavailable:{cutoff.date()}"
    latest = max(candidates, key=lambda item: item.available_datetime)
    value = latest.payload.get("value")
    return (float(value) / 100.0 if isinstance(value, (int, float)) else 0.0), latest.record_id


def _latest_series(records: tuple[HistoricalRecord, ...], dataset: str) -> HistoricalRecord | None:
    values = [item for item in records if item.dataset == dataset]
    return max(values, key=lambda item: item.available_datetime) if values else None


def _macro_context(records: tuple[HistoricalRecord, ...], cutoff: datetime) -> MacroSpecialistContext:
    curve = _latest_series(records, "series.t10y2y")
    vix = _latest_series(records, "series.vixcls")
    curve_value = float(curve.payload.get("value", 0.0)) if curve else 0.0
    vix_value = float(vix.payload.get("value", 20.0)) if vix else 20.0
    if vix_value >= 30.0 or curve_value <= -0.5:
        regime, impact = "risk_off", -0.03
        tailwinds, headwinds = (), ("Elevated systemic stress or inverted curve",)
    elif vix_value <= 20.0 and curve_value >= 0.0:
        regime, impact = "risk_on", 0.02
        tailwinds, headwinds = ("Contained volatility and non-inverted curve",), ()
    else:
        regime, impact = "mixed", 0.0
        tailwinds, headwinds = (), ("Macro signals are mixed",)
    evidence = tuple(item.record_id for item in (curve, vix) if item is not None)
    if not evidence:
        evidence = (f"historical-replay:macro-unavailable:{cutoff.date()}",)
    return MacroSpecialistContext(
        as_of=cutoff,
        regime=regime,
        expected_return_impact=impact,
        confidence=0.75 if curve and vix else 0.5,
        tailwinds=tailwinds,
        headwinds=headwinds,
        systemic_risks=("Historical macro relationships may change across regimes",),
        scenarios=("Reclassify when curve or volatility regime changes",),
        evidence_identifiers=evidence,
    )


@dataclass(slots=True)
class ReplayPortfolioState:
    value: float = 250_000.0
    cash_weight: float = 1.0
    weights: dict[str, float] = field(default_factory=dict)
    previous_prices: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, tuple[str, str, float, float, float, str]] = field(default_factory=dict)

    def mark_to_market(self, prices: Mapping[str, float]) -> None:
        if not self.previous_prices or not self.weights:
            self.previous_prices = dict(prices)
            return
        cash_value = self.value * self.cash_weight
        asset_values: dict[str, float] = {}
        for symbol, weight in self.weights.items():
            previous = self.previous_prices.get(symbol)
            current = prices.get(symbol)
            ratio = current / previous if previous and current and previous > 0.0 else 1.0
            asset_values[symbol] = self.value * weight * ratio
        total = cash_value + sum(asset_values.values())
        if total > 0.0:
            self.value = total
            self.cash_weight = cash_value / total
            self.weights = {symbol: value / total for symbol, value in asset_values.items() if value > 0.0}
        self.previous_prices = dict(prices)

    def apply_construction(self, construction: object | None) -> None:
        if construction is None:
            return
        status = getattr(construction, "status", None)
        if status not in {ConstructionStatus.FEASIBLE, ConstructionStatus.PARTIAL, ConstructionStatus.NO_ACTION}:
            return
        cost = float(getattr(construction, "estimated_cost_return", 0.0) or 0.0)
        self.value *= max(0.0, 1.0 - cost)
        targets = dict(getattr(construction, "target_weights", ()) or ())
        self.weights = {
            str(symbol).upper(): float(weight)
            for symbol, weight in targets.items()
            if float(weight) > 0.0
        }
        self.cash_weight = float(getattr(construction, "target_cash_weight", 1.0))


class HistoricalCanonicalContextBuilder:
    """Build production-domain CIO inputs from the historical evidence store."""

    def __init__(self, *, minimum_observations: int = 63, maximum_candidates: int = 25) -> None:
        if minimum_observations < 21:
            raise ValueError("minimum_observations must be at least 21")
        if maximum_candidates < 1:
            raise ValueError("maximum_candidates must be positive")
        self.minimum_observations = minimum_observations
        self.maximum_candidates = maximum_candidates

    def build(
        self,
        *,
        records: tuple[HistoricalRecord, ...],
        cutoff: datetime,
        state: ReplayPortfolioState,
        strict_only: bool,
    ) -> tuple[
        tuple[CandidateDecisionRecord, ...],
        tuple[CandidateCycleContext, ...],
        OpportunitySetContext,
        CyclePortfolioState,
        dict[str, float],
    ]:
        cutoff_text = iso_timestamp(cutoff)
        features = market_features(records, cutoff=cutoff_text)
        grouped = _price_records(records)
        eligible = [
            symbol for symbol, values in grouped.items()
            if symbol in features and len(values) >= self.minimum_observations
        ]
        eligible.sort(
            key=lambda symbol: (
                _average_dollar_volume(grouped[symbol]),
                features[symbol]["momentum"]
                / max(features[symbol]["annualized_volatility"], 0.05),
                symbol,
            ),
            reverse=True,
        )
        eligible = eligible[: self.maximum_candidates]
        prices = {symbol: float(features[symbol]["last_close"]) for symbol in eligible}
        state.mark_to_market(prices)
        cash_return, _cash_evidence = _cash_return(records, cutoff)
        macro = _macro_context(records, cutoff)
        breadth = (
            sum(1 for value in features.values() if value["momentum"] > 0.0)
            / len(features)
            if features else 0.5
        )

        candidates: list[CandidateDecisionRecord] = []
        contexts: list[CandidateCycleContext] = []
        profiles: list[CandidateExposureProfile] = []
        for symbol in eligible:
            values = grouped[symbol]
            latest = values[-1]
            raw_symbol = str(latest.payload.get("symbol", symbol)).upper()
            feature = features[symbol]
            asset = _asset_class(symbol, raw_symbol)
            sector, bucket, venue, instrument_type = _metadata(symbol, raw_symbol)
            adv = _average_dollar_volume(values)
            momentum = float(feature["momentum"])
            volatility = max(0.01, float(feature["annualized_volatility"]))
            drawdown = float(feature["drawdown"])
            base_return = _clamp(momentum * 0.50, -0.25, 0.35)
            bull_return = _clamp(
                base_return + max(0.08, volatility * 0.65), -0.10, 0.80
            )
            bear_return = _clamp(
                base_return - max(0.10, volatility * 0.90), -0.85, 0.10
            )
            evidence_ids = tuple(item.record_id for item in values[-5:])
            quality = EvidenceQuality(
                reliability=0.82 if latest.strict_replay_eligible else 0.72,
                freshness=0.90,
                relevance=0.90,
                independence=0.70,
                completeness=min(0.90, len(values) / 252),
                point_in_time_integrity=(
                    0.85 if latest.strict_replay_eligible else 0.55
                ),
            )
            transaction_cost = 10.0 if asset is CandidateAssetClass.CRYPTO else 5.0
            slippage = 15.0 if asset is CandidateAssetClass.CRYPTO else 5.0
            current_weight = state.weights.get(symbol, 0.0)
            candidate_id = f"historical:{cutoff.date()}:{symbol}"
            instrument = CandidateInstrument(
                instrument_id=f"historical-instrument:{raw_symbol}",
                symbol=symbol,
                name=f"Historical replay {symbol}",
                asset_class=asset,
                venue=venue,
                country_code=(
                    "US" if asset is not CandidateAssetClass.CRYPTO else "XX"
                ),
                average_daily_dollar_volume=adv,
                data_age_hours=max(
                    0.0,
                    (cutoff - latest.available_datetime).total_seconds() / 3600.0,
                ),
                analytical_coverage=min(1.0, len(values) / 252),
                security_master_snapshot_identifier=(
                    f"historical-security-master:{cutoff.date()}"
                ),
                security_master_record_identifiers=(
                    f"historical-security-master:{raw_symbol}",
                ),
                instrument_type=instrument_type,
            )
            candidate = CandidateDecisionRecord(
                identifier=candidate_id,
                as_of=cutoff,
                schema_version="historical-canonical-candidate.v1",
                instrument=instrument,
                current_price=float(feature["last_close"]),
                decision_horizon_days=365,
                base_case_return=base_return,
                bull_case_return=bull_return,
                bear_case_return=bear_return,
                base_case_probability=0.50,
                bull_case_probability=0.25,
                bear_case_probability=0.25,
                estimated_fair_value=float(feature["last_close"])
                * (1.0 + base_return),
                expected_upside=max(0.0, bull_return),
                expected_downside=min(0.0, bear_return),
                probability_of_success=(
                    0.60 if base_return > cash_return else 0.40
                ),
                primary_catalysts=(
                    "Historical trend and cross-asset conditions remain supportive",
                ),
                key_risks=(
                    f"Annualized volatility is {volatility:.2%}; "
                    f"drawdown is {drawdown:.2%}",
                ),
                critical_assumptions=(
                    "Point-in-time price relationships remain informative over the decision horizon",
                ),
                invalidation_conditions=(
                    "Momentum reverses or drawdown breaches the historical risk budget",
                ),
                supporting_evidence=(
                    f"{len(values)} point-in-time price observations",
                ),
                contradictory_evidence=(
                    ("Current momentum is negative",) if momentum < 0.0 else ()
                ),
                evidence_quality=quality,
                liquidity_score=_clamp(
                    math.log10(max(adv, 1.0)) / 10.0, 0.0, 1.0
                ),
                transaction_cost_bps=transaction_cost,
                slippage_bps=slippage,
                opportunity_cost_return=cash_return,
                expected_portfolio_contribution=base_return
                * min(0.10, 1.0 - state.cash_weight + 0.10),
                current_portfolio_weight=current_weight,
                maximum_position_weight=max(0.10, current_weight),
                monitoring_indicators=(
                    "momentum", "volatility", "drawdown", "macro_regime"
                ),
                review_at=cutoff + timedelta(days=30),
                evidence_identifiers=evidence_ids,
                model_versions=("historical-canonical-context.v1",),
            )
            market_impact = _clamp(momentum * 0.10, -0.10, 0.10)
            market = MarketSpecialistContext(
                as_of=cutoff,
                market_regime=(
                    "positive_trend" if momentum > 0.0 else "negative_trend"
                ),
                expected_return_impact=market_impact,
                confidence=min(0.90, quality.score),
                trend=_clamp(momentum, -1.0, 1.0),
                momentum=_clamp(momentum, -1.0, 1.0),
                breadth=_clamp(breadth * 2.0 - 1.0, -1.0, 1.0),
                liquidity=_clamp(
                    math.log10(max(adv, 1.0)) / 10.0, -1.0, 1.0
                ),
                positioning=0.0,
                evidence=(
                    f"Momentum={momentum:.2%}",
                    f"Breadth={breadth:.2%}",
                ),
                risks=(f"Volatility={volatility:.2%}",),
                entry_conditions=(
                    "Price trend remains consistent through the next review",
                ),
                evidence_identifiers=evidence_ids,
            )
            forecast = CrossAssetForecastSpecialistContext(
                as_of=cutoff,
                forecast_horizon_days=365,
                scenarios=(
                    ForecastScenarioAssessment(
                        "base", 0.50, base_return * 0.10,
                        min(0.0, drawdown),
                        "Central historical trend case", evidence_ids,
                    ),
                    ForecastScenarioAssessment(
                        "bull", 0.25, max(0.0, bull_return * 0.10),
                        min(0.0, drawdown * 0.5),
                        "Supportive historical distribution tail", evidence_ids,
                    ),
                    ForecastScenarioAssessment(
                        "bear", 0.25, min(0.0, bear_return * 0.10),
                        min(-0.01, bear_return),
                        "Adverse historical distribution tail", evidence_ids,
                    ),
                ),
                aggregate_confidence=min(0.80, quality.score),
                calibration_score=0.60 if len(values) >= 252 else 0.50,
                model_agreement=0.60,
                forecast_stability=0.60,
                path_drawdown_probability=_clamp(volatility, 0.0, 1.0),
                cross_asset_signals=(
                    f"Macro regime={macro.regime}",
                    f"Market breadth={breadth:.2%}",
                ),
                contradictory_evidence=(
                    ("Negative momentum conflicts with upside case",)
                    if momentum < 0.0 else ()
                ),
                limitations=(
                    "Historical distributions do not guarantee future outcomes",
                ),
                change_conditions=(
                    "Re-estimate after a material regime or volatility change",
                ),
                model_versions=("historical-distribution-forecast.v1",),
                evidence_identifiers=evidence_ids,
            )
            valuation = AssetValuationSpecialistContext(
                as_of=cutoff,
                asset_class=asset,
                expected_return_impact=_clamp(
                    base_return * 0.20, -0.10, 0.10
                ),
                confidence=min(0.80, quality.score),
                valuation_evidence=(
                    f"Price-implied one-year central return={base_return:.2%}",
                ),
                contradictory_evidence=(
                    (
                        "Valuation relies on market history without complete issuer fundamentals",
                    )
                    if asset is CandidateAssetClass.US_EQUITY else ()
                ),
                critical_assumptions=(
                    "Historical return distribution remains a valid valuation cross-check",
                ),
                risks=(
                    "Valuation may change as new fundamentals or market structure evidence arrives",
                ),
                limitations=(
                    "Research bridge; issuer-level normalization may be incomplete",
                ),
                change_conditions=(
                    "Refresh when paid or official point-in-time fundamentals expand",
                ),
                evidence_identifiers=evidence_ids,
            )
            candidates.append(candidate)
            contexts.append(
                CandidateCycleContext(
                    candidate_identifier=candidate_id,
                    analysis_completed_at=cutoff,
                    macro=macro,
                    market=market,
                    forecast=forecast,
                    company=None,
                    asset_valuation=valuation,
                )
            )
            profiles.append(
                CandidateExposureProfile(
                    candidate_identifier=candidate_id,
                    sector=sector,
                    factor_loadings=((
                        "momentum", _clamp(momentum, -1.0, 1.0)
                    ),),
                    correlation_bucket=bucket,
                )
            )
            state.metadata[symbol] = (
                sector, bucket, adv, transaction_cost, slippage,
                instrument.instrument_id,
            )

        positions: list[PortfolioAsset] = []
        for symbol, weight in state.weights.items():
            sector, bucket, adv, transaction_cost, slippage, instrument_id = (
                state.metadata.get(
                    symbol,
                    (
                        "unclassified", "unclassified", 0.0, 5.0, 5.0,
                        f"historical-instrument:{symbol}",
                    ),
                )
            )
            positions.append(
                PortfolioAsset(
                    symbol=symbol,
                    current_weight=weight,
                    expected_return=0.0,
                    sector=sector,
                    factor_loadings=(),
                    correlation_bucket=bucket,
                    average_daily_dollar_volume=adv,
                    transaction_cost_bps=transaction_cost,
                    slippage_bps=slippage,
                    instrument_identifier=instrument_id,
                )
            )
        portfolio = CyclePortfolioState(
            identifier=f"historical-portfolio:{cutoff.date()}",
            as_of=cutoff,
            portfolio_value=state.value,
            cash_weight=state.cash_weight,
            cash_expected_return=cash_return,
            positions=tuple(positions),
            exposure_profiles=tuple(profiles),
        )
        alternatives = [
            AlternativeUse(
                identifier="CASH",
                kind=AlternativeKind.CASH,
                expected_return=cash_return,
                implementation_cost_return=0.0,
                evidence_quality=1.0,
                liquidity_score=1.0,
                current_weight=state.cash_weight,
            )
        ]
        for position in positions:
            alternatives.append(
                AlternativeUse(
                    identifier=position.symbol,
                    kind=AlternativeKind.CURRENT_HOLDING,
                    expected_return=position.expected_return,
                    implementation_cost_return=position.total_cost_bps / 10_000.0,
                    evidence_quality=0.70,
                    liquidity_score=0.70,
                    current_weight=position.current_weight,
                )
            )
        opportunity = OpportunitySetContext(
            identifier=f"historical-opportunity:{cutoff.date()}",
            as_of=cutoff,
            alternatives=tuple(alternatives),
        )
        return (
            tuple(candidates), tuple(contexts), opportunity, portfolio, prices
        )


class CanonicalHistoricalReplayEngine:
    """Run the real canonical CIO over immutable historical cutoffs."""

    def __init__(
        self,
        store: HistoricalStore,
        *,
        cycle: CanonicalCIOCycle | None = None,
        builder: HistoricalCanonicalContextBuilder | None = None,
    ) -> None:
        self.store = store
        self.cycle = cycle or CanonicalCIOCycle()
        self.builder = builder or HistoricalCanonicalContextBuilder()

    @staticmethod
    def _decision_payload(decision: object) -> dict[str, Any]:
        return {
            "identifier": getattr(decision, "identifier"),
            "candidate_identifier": getattr(decision, "candidate_identifier"),
            "action": getattr(getattr(decision, "action"), "value"),
            "final_confidence": getattr(decision, "final_confidence"),
            "expected_return": getattr(decision, "expected_return"),
            "recommended_position_weight": getattr(
                decision, "recommended_position_weight"
            ),
            "funding_source": getattr(decision, "funding_source"),
            "evidence_vetoes": list(getattr(decision, "evidence_vetoes")),
            "implementation_blocks": list(
                getattr(decision, "implementation_blocks")
            ),
            "explanation": getattr(decision, "explanation"),
        }

    def run(
        self,
        *,
        start: date,
        end: date,
        cadence: str = "monthly",
        strict_only: bool = False,
        initial_portfolio_value: float = 250_000.0,
    ) -> dict[str, Any]:
        if initial_portfolio_value <= 0.0:
            raise ValueError("initial_portfolio_value must be positive")
        state = ReplayPortfolioState(value=float(initial_portfolio_value))
        decisions: list[dict[str, Any]] = []
        completed = blocked = 0
        for cutoff_date in replay_dates(start, end, cadence):
            cutoff = _decision_time(cutoff_date)
            records = tuple(
                self.store.iter_records(
                    available_before=iso_timestamp(cutoff),
                    strict_only=strict_only,
                )
            )
            try:
                candidates, contexts, opportunity, portfolio, prices = (
                    self.builder.build(
                        records=records,
                        cutoff=cutoff,
                        state=state,
                        strict_only=strict_only,
                    )
                )
                if not candidates:
                    raise RuntimeError(
                        "no historical candidates satisfy the point-in-time coverage gate"
                    )
                result = self.cycle.run(
                    identifier=f"historical-canonical-cycle:{cutoff_date}",
                    candidates=candidates,
                    opportunity_context=opportunity,
                    specialist_contexts=contexts,
                    portfolio=portfolio,
                    code_version="historical-canonical-replay.v1",
                )
                state.apply_construction(result.construction)
                state.previous_prices.update(prices)
                construction = result.construction
                payload = {
                    "cutoff": iso_timestamp(cutoff),
                    "state": "completed",
                    "canonical_cio_invoked": True,
                    "candidate_count": len(candidates),
                    "decision_count": len(result.decisions),
                    "decisions": [
                        self._decision_payload(item) for item in result.decisions
                    ],
                    "construction": (
                        None if construction is None else {
                            "status": construction.status.value,
                            "target_cash_weight": construction.target_cash_weight,
                            "target_weights": dict(construction.target_weights),
                            "turnover": construction.turnover,
                            "estimated_cost_return": construction.estimated_cost_return,
                            "blocks": list(construction.blocks),
                        }
                    ),
                    "portfolio_value": state.value,
                    "portfolio_weights": dict(state.weights),
                    "cash_weight": state.cash_weight,
                }
                completed += 1
            except Exception as error:
                payload = {
                    "cutoff": iso_timestamp(cutoff),
                    "state": "blocked",
                    "canonical_cio_invoked": False,
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "portfolio_value": state.value,
                    "portfolio_weights": dict(state.weights),
                    "cash_weight": state.cash_weight,
                }
                blocked += 1
            decisions.append(payload)
        report = {
            "schema_version": "canonical-historical-replay.v1",
            "generated_at": iso_timestamp(datetime.now(tz=UTC)),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "cadence": cadence,
            "strict_only": strict_only,
            "strict_replay": strict_only,
            "research_only": True,
            "canonical_cio_available": True,
            "canonical_cio_invoked_count": completed,
            "blocked_cutoff_count": blocked,
            "decision_cutoff_count": len(decisions),
            "initial_portfolio_value": float(initial_portfolio_value),
            "ending_portfolio_value": state.value,
            "ending_weights": dict(state.weights),
            "ending_cash_weight": state.cash_weight,
            "decisions": decisions,
            "execution_authorized": False,
            "paper_execution_authorized": False,
            "real_money_authorized": False,
            "policy_promotion_authorized": False,
            "performance_claims_authorized": False,
        }
        self.store.write_manifest("latest-canonical-replay", report)
        return report


def load_replay_config(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return dict(payload.get("canonical_replay", {}))


__all__ = [
    "CanonicalHistoricalReplayEngine",
    "HistoricalCanonicalContextBuilder",
    "ReplayPortfolioState",
    "load_replay_config",
]
