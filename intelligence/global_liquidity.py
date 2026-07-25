"""Deterministic U.S.-led global liquidity intelligence engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from typing import Callable

from data import (
    DataQualityState,
    NormalizedObservation,
    ObservationProvider,
    ObservationQuery,
    ProviderError,
    SeriesSpecification,
)
from intelligence.analytical_engine import (
    AnalyticalEngineResult,
    EngineDataStatus,
    EngineDirection,
    EngineEvidence,
)
from providers.fred import FREDProvider
from providers.fred_series import FRED_SERIES


class LiquidityComponent(str, Enum):
    FED_BALANCE_SHEET = "fed_balance_sheet"
    RESERVE_BALANCES = "reserve_balances"
    TREASURY_CASH = "treasury_cash"
    REVERSE_REPO = "reverse_repo"
    BROAD_MONEY = "broad_money"
    DOLLAR_FUNDING = "dollar_funding"
    FINANCIAL_CONDITIONS = "financial_conditions"


class LiquidityScoringMode(str, Enum):
    CHANGE_POSITIVE = "change_positive"
    CHANGE_INVERSE = "change_inverse"
    LEVEL_INVERSE = "level_inverse"


class LiquidityLoadState(str, Enum):
    LOADED = "loaded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class LiquiditySeriesRequest:
    component: LiquidityComponent
    series: SeriesSpecification
    limit: int
    comparison_periods: int
    weight: float
    scoring_mode: LiquidityScoringMode
    sensitivity: float

    def __post_init__(self) -> None:
        if not isinstance(self.component, LiquidityComponent):
            raise TypeError("component must be a LiquidityComponent")
        if not isinstance(self.series, SeriesSpecification):
            raise TypeError("series must be a SeriesSpecification")
        for field_name in ("limit", "comparison_periods"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an int")
            if value < 1:
                raise ValueError(f"{field_name} must be positive")
        if self.comparison_periods >= self.limit:
            raise ValueError("comparison_periods must be smaller than limit")
        if not isinstance(self.scoring_mode, LiquidityScoringMode):
            raise TypeError("scoring_mode must be a LiquidityScoringMode")
        for field_name in ("weight", "sensitivity"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be numeric")
            normalized = float(value)
            if not isfinite(normalized) or normalized <= 0:
                raise ValueError(f"{field_name} must be positive and finite")
            object.__setattr__(self, field_name, normalized)


@dataclass(frozen=True, slots=True)
class LiquiditySeriesLoad:
    request: LiquiditySeriesRequest
    state: LiquidityLoadState
    observations: tuple[NormalizedObservation, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, LiquiditySeriesRequest):
            raise TypeError("request must be a LiquiditySeriesRequest")
        if not isinstance(self.state, LiquidityLoadState):
            raise TypeError("state must be a LiquidityLoadState")
        if not all(isinstance(item, NormalizedObservation) for item in self.observations):
            raise TypeError("observations must contain NormalizedObservation values")
        if self.state is LiquidityLoadState.LOADED:
            if not self.observations:
                raise ValueError("loaded series requires observations")
            if self.error is not None:
                raise ValueError("loaded series cannot contain an error")
        else:
            if self.observations:
                raise ValueError("unavailable series cannot contain observations")
            if not isinstance(self.error, str) or not self.error.strip():
                raise ValueError("unavailable series requires an error")


@dataclass(frozen=True, slots=True)
class GlobalLiquidityRun:
    as_of: datetime
    provider: str
    loads: tuple[LiquiditySeriesLoad, ...]
    result: AnalyticalEngineResult

    def __post_init__(self) -> None:
        if not isinstance(self.as_of, datetime):
            raise TypeError("as_of must be a datetime")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("provider must be a non-empty string")
        if not self.loads:
            raise ValueError("loads cannot be empty")
        if not all(isinstance(item, LiquiditySeriesLoad) for item in self.loads):
            raise TypeError("loads must contain LiquiditySeriesLoad values")
        if not isinstance(self.result, AnalyticalEngineResult):
            raise TypeError("result must be an AnalyticalEngineResult")
        if self.result.as_of != self.as_of:
            raise ValueError("result must use the run as_of")

    @property
    def loaded_count(self) -> int:
        return sum(load.state is LiquidityLoadState.LOADED for load in self.loads)

    @property
    def unavailable_count(self) -> int:
        return len(self.loads) - self.loaded_count


GLOBAL_LIQUIDITY_FRED_REQUESTS = (
    LiquiditySeriesRequest(
        component=LiquidityComponent.FED_BALANCE_SHEET,
        series=FRED_SERIES["federal_reserve_total_assets"],
        limit=30,
        comparison_periods=13,
        weight=0.20,
        scoring_mode=LiquidityScoringMode.CHANGE_POSITIVE,
        sensitivity=0.05,
    ),
    LiquiditySeriesRequest(
        component=LiquidityComponent.RESERVE_BALANCES,
        series=FRED_SERIES["reserve_balances"],
        limit=30,
        comparison_periods=13,
        weight=0.20,
        scoring_mode=LiquidityScoringMode.CHANGE_POSITIVE,
        sensitivity=0.10,
    ),
    LiquiditySeriesRequest(
        component=LiquidityComponent.TREASURY_CASH,
        series=FRED_SERIES["treasury_general_account"],
        limit=30,
        comparison_periods=13,
        weight=0.15,
        scoring_mode=LiquidityScoringMode.CHANGE_INVERSE,
        sensitivity=0.30,
    ),
    LiquiditySeriesRequest(
        component=LiquidityComponent.REVERSE_REPO,
        series=FRED_SERIES["overnight_reverse_repo"],
        limit=30,
        comparison_periods=13,
        weight=0.15,
        scoring_mode=LiquidityScoringMode.CHANGE_INVERSE,
        sensitivity=0.50,
    ),
    LiquiditySeriesRequest(
        component=LiquidityComponent.BROAD_MONEY,
        series=FRED_SERIES["broad_money_m2"],
        limit=18,
        comparison_periods=3,
        weight=0.15,
        scoring_mode=LiquidityScoringMode.CHANGE_POSITIVE,
        sensitivity=0.04,
    ),
    LiquiditySeriesRequest(
        component=LiquidityComponent.DOLLAR_FUNDING,
        series=FRED_SERIES["broad_dollar_index"],
        limit=45,
        comparison_periods=20,
        weight=0.10,
        scoring_mode=LiquidityScoringMode.CHANGE_INVERSE,
        sensitivity=0.04,
    ),
    LiquiditySeriesRequest(
        component=LiquidityComponent.FINANCIAL_CONDITIONS,
        series=FRED_SERIES["national_financial_conditions"],
        limit=12,
        comparison_periods=4,
        weight=0.05,
        scoring_mode=LiquidityScoringMode.LEVEL_INVERSE,
        sensitivity=1.0,
    ),
)


def _clip(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _quality_weight(observation: NormalizedObservation, as_of: datetime) -> float:
    if observation.is_stale_at(as_of):
        return 0.40
    return {
        DataQualityState.LIVE: 1.00,
        DataQualityState.FIXTURE: 1.00,
        DataQualityState.CACHED: 0.90,
        DataQualityState.FALLBACK: 0.60,
        DataQualityState.STALE: 0.40,
        DataQualityState.MISSING: 0.00,
    }[observation.provenance.quality_state]


def _score_request(
    request: LiquiditySeriesRequest,
    observations: tuple[NormalizedObservation, ...],
) -> tuple[float, NormalizedObservation, NormalizedObservation | None, str]:
    ordered = tuple(
        sorted(
            observations,
            key=lambda item: (item.observation_date, item.provenance.released_at),
        )
    )
    latest = ordered[-1]
    if latest.value is None:
        raise ValueError("latest observation is missing")
    if request.scoring_mode is LiquidityScoringMode.LEVEL_INVERSE:
        score = _clip(-float(latest.value) / request.sensitivity)
        explanation = (
            f"{request.component.value.replace('_', ' ').title()} is "
            f"{float(latest.value):.2f}; lower values indicate easier conditions."
        )
        return score, latest, None, explanation

    baseline_index = max(0, len(ordered) - 1 - request.comparison_periods)
    baseline = ordered[baseline_index]
    if baseline.value is None:
        raise ValueError("comparison observation is missing")
    denominator = max(abs(float(baseline.value)), 1.0)
    change = (float(latest.value) - float(baseline.value)) / denominator
    if request.scoring_mode is LiquidityScoringMode.CHANGE_INVERSE:
        change *= -1.0
    score = _clip(change / request.sensitivity)
    raw_direction = "rose" if float(latest.value) > float(baseline.value) else "fell"
    explanation = (
        f"{request.component.value.replace('_', ' ').title()} {raw_direction} "
        f"from {float(baseline.value):,.2f} to {float(latest.value):,.2f}; "
        f"the normalized liquidity contribution is {score:+.2f}."
    )
    return score, latest, baseline, explanation


def _direction(score: int, evidence: tuple[EngineEvidence, ...]) -> EngineDirection:
    stress = next(
        (
            item
            for item in evidence
            if item.component == LiquidityComponent.FINANCIAL_CONDITIONS.value
            and item.signal_score <= -0.80
        ),
        None,
    )
    if score <= 25 or stress is not None:
        return EngineDirection.STRESSED
    if score < 45:
        return EngineDirection.CONTRACTING
    if score <= 60:
        return EngineDirection.NEUTRAL
    return EngineDirection.EXPANDING


def _transmission(direction: EngineDirection) -> tuple[str, ...]:
    if direction is EngineDirection.EXPANDING:
        return (
            "Improving liquidity can support equity valuations and broader risk appetite.",
            "Easier funding conditions can reduce pressure on credit-sensitive borrowers.",
            "A weaker funding backdrop for the U.S. dollar can help international and emerging-market assets.",
        )
    if direction is EngineDirection.CONTRACTING:
        return (
            "Tighter liquidity can pressure expensive or highly leveraged risk assets.",
            "Refinancing conditions may become less forgiving for lower-quality borrowers.",
            "A firmer U.S. dollar can weigh on international, commodity, and emerging-market exposures.",
        )
    if direction is EngineDirection.STRESSED:
        return (
            "Stressed funding conditions can amplify volatility and reduce market depth.",
            "Credit-sensitive and leveraged exposures may face outsized downside risk.",
            "Liquidity reserves and portfolio optionality become more valuable when funding markets are stressed.",
        )
    if direction is EngineDirection.UNAVAILABLE:
        return (
            "No portfolio transmission conclusion is available because the required evidence could not be retrieved.",
        )
    return (
        "Liquidity is not currently providing a strong directional tailwind or headwind.",
        "Portfolio decisions should rely on the broader evidence set rather than liquidity alone.",
    )


class GlobalLiquidityEngine:
    """Retrieve point-in-time liquidity evidence and publish one typed result."""

    engine_name = "global_liquidity"
    scope = "U.S.-led global liquidity conditions"
    policy_version = "global-liquidity-policy.v1"

    def __init__(
        self,
        provider: ObservationProvider,
        *,
        requests: tuple[LiquiditySeriesRequest, ...] = GLOBAL_LIQUIDITY_FRED_REQUESTS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(provider, ObservationProvider):
            raise TypeError("provider must implement ObservationProvider")
        if not requests:
            raise ValueError("requests cannot be empty")
        if not all(isinstance(item, LiquiditySeriesRequest) for item in requests):
            raise TypeError("requests must contain LiquiditySeriesRequest values")
        components = [item.component for item in requests]
        if len(components) != len(set(components)):
            raise ValueError("liquidity request components must be unique")
        self.provider = provider
        self.requests = requests
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self, *, as_of: datetime) -> GlobalLiquidityRun:
        if not isinstance(as_of, datetime):
            raise TypeError("as_of must be a datetime")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")

        loads: list[LiquiditySeriesLoad] = []
        evidence: list[EngineEvidence] = []
        loaded_weight = weighted_score = weighted_quality = stale_weight = 0.0

        for request in self.requests:
            query = ObservationQuery(series=request.series, as_of=as_of, limit=request.limit)
            try:
                observations = tuple(self.provider.fetch(query))
            except ProviderError as error:
                loads.append(LiquiditySeriesLoad(request, LiquidityLoadState.UNAVAILABLE, error=str(error)))
                continue
            if not observations:
                loads.append(LiquiditySeriesLoad(request, LiquidityLoadState.UNAVAILABLE, error="provider returned no observations"))
                continue
            usable = tuple(item for item in observations if item.is_available_at(as_of))
            if not usable:
                loads.append(LiquiditySeriesLoad(request, LiquidityLoadState.UNAVAILABLE, error="no observations were available at the decision time"))
                continue
            try:
                signal_score, latest, _baseline, explanation = _score_request(request, usable)
            except ValueError as error:
                loads.append(LiquiditySeriesLoad(request, LiquidityLoadState.UNAVAILABLE, error=str(error)))
                continue
            loads.append(LiquiditySeriesLoad(request, LiquidityLoadState.LOADED, observations=usable))
            quality = _quality_weight(latest, as_of)
            loaded_weight += request.weight
            weighted_score += request.weight * signal_score
            weighted_quality += request.weight * quality
            if latest.is_stale_at(as_of):
                stale_weight += request.weight
            evidence.append(
                EngineEvidence(
                    identifier=(
                        f"engine-evidence:{self.engine_name}:"
                        f"{latest.provenance.series_identifier}:"
                        f"{latest.observation_date.isoformat()}"
                    ),
                    component=request.component.value,
                    indicator=latest.indicator,
                    provider=latest.provenance.provider,
                    series_identifier=latest.provenance.series_identifier,
                    observation_date=latest.observation_date,
                    released_at=latest.provenance.released_at,
                    retrieved_at=latest.provenance.retrieved_at,
                    vintage_date=latest.provenance.vintage_date,
                    quality_state=latest.provenance.quality_state.value,
                    signal_score=signal_score,
                    weighted_contribution=_clip(request.weight * signal_score),
                    explanation=explanation,
                )
            )

        total_weight = sum(item.weight for item in self.requests)
        coverage = 0.0 if total_weight == 0 else loaded_weight / total_weight
        generated_at = as_of

        if loaded_weight == 0:
            result = AnalyticalEngineResult(
                identifier=f"analytical-engine:{self.engine_name}:{as_of.isoformat()}",
                engine=self.engine_name,
                scope=self.scope,
                policy_version=self.policy_version,
                as_of=as_of,
                generated_at=generated_at,
                direction=EngineDirection.UNAVAILABLE,
                score=50,
                confidence=0,
                coverage=0.0,
                data_status=EngineDataStatus.UNAVAILABLE,
                summary="Global liquidity evidence is unavailable.",
                explanation=(
                    "The engine could not retrieve any required point-in-time series, "
                    "so it does not present a directional liquidity conclusion."
                ),
                risks=tuple(
                    f"{load.request.component.value}: {load.error}"
                    for load in loads
                    if load.state is LiquidityLoadState.UNAVAILABLE
                ),
                transmission_channels=_transmission(EngineDirection.UNAVAILABLE),
                review_conditions=(
                    "Re-run the engine after provider access and required series are restored.",
                ),
                evidence=(),
            )
            return GlobalLiquidityRun(as_of, self.provider.name, tuple(loads), result)

        composite = weighted_score / loaded_weight
        score = max(0, min(100, round(50 + 50 * composite)))
        direction = _direction(score, tuple(evidence))
        mean_absolute_deviation = sum(
            next(request.weight for request in self.requests if request.component.value == item.component)
            * abs(item.signal_score - composite)
            for item in evidence
        ) / loaded_weight
        agreement = max(0.0, 1.0 - min(1.0, mean_absolute_deviation))
        quality = weighted_quality / loaded_weight
        confidence = round(100 * (0.50 * coverage + 0.30 * quality + 0.20 * agreement))
        stale_share = stale_weight / loaded_weight
        if stale_share >= 0.50:
            status = EngineDataStatus.STALE
        elif coverage < 0.999:
            status = EngineDataStatus.INCOMPLETE
        else:
            status = EngineDataStatus.CURRENT

        positive = sorted(
            (item for item in evidence if item.signal_score > 0.05),
            key=lambda item: item.weighted_contribution,
            reverse=True,
        )
        negative = sorted(
            (item for item in evidence if item.signal_score < -0.05),
            key=lambda item: item.weighted_contribution,
        )
        summary = {
            EngineDirection.EXPANDING: "U.S.-led global liquidity conditions are improving.",
            EngineDirection.NEUTRAL: "Global liquidity is not providing a strong directional signal.",
            EngineDirection.CONTRACTING: "U.S.-led global liquidity conditions are tightening.",
            EngineDirection.STRESSED: "Global funding and liquidity conditions are stressed.",
        }[direction]
        drivers: list[str] = []
        if positive:
            drivers.append("supportive evidence led by " + ", ".join(item.component.replace("_", " ") for item in positive[:2]))
        if negative:
            drivers.append("restrictive evidence led by " + ", ".join(item.component.replace("_", " ") for item in negative[:2]))
        explanation = (
            summary
            + (" The assessment reflects " + " while ".join(drivers) + "." if drivers else "")
            + f" Weighted evidence coverage is {coverage:.0%}; confidence is {confidence}%."
        )
        risks = [
            f"{load.request.component.value}: {load.error}"
            for load in loads
            if load.state is LiquidityLoadState.UNAVAILABLE
        ]
        opposing = negative if direction is EngineDirection.EXPANDING else positive
        if opposing:
            risks.append(
                "Contradictory evidence remains in "
                + ", ".join(item.component.replace("_", " ") for item in opposing[:3])
                + "."
            )
        if status is EngineDataStatus.STALE:
            risks.append("At least half of the loaded evidence is stale at the decision time.")
        result = AnalyticalEngineResult(
            identifier=f"analytical-engine:{self.engine_name}:{as_of.isoformat()}",
            engine=self.engine_name,
            scope=self.scope,
            policy_version=self.policy_version,
            as_of=as_of,
            generated_at=generated_at,
            direction=direction,
            score=score,
            confidence=confidence,
            coverage=round(coverage, 6),
            data_status=status,
            summary=summary,
            explanation=explanation,
            risks=tuple(risks),
            transmission_channels=_transmission(direction),
            review_conditions=(
                "Reassess if the composite liquidity score crosses 45 or 60.",
                "Escalate review if financial conditions move into the stressed range.",
                "Reduce confidence when weighted evidence coverage falls below 75%.",
            ),
            evidence=tuple(evidence),
        )
        return GlobalLiquidityRun(as_of, self.provider.name, tuple(loads), result)

    def run_current(self) -> GlobalLiquidityRun:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return self.run(as_of=now)


def build_fred_global_liquidity_engine(
    *,
    provider: FREDProvider | None = None,
    clock: Callable[[], datetime] | None = None,
) -> GlobalLiquidityEngine:
    return GlobalLiquidityEngine(provider or FREDProvider(), clock=clock)


__all__ = [
    "GLOBAL_LIQUIDITY_FRED_REQUESTS",
    "GlobalLiquidityEngine",
    "GlobalLiquidityRun",
    "LiquidityComponent",
    "LiquidityLoadState",
    "LiquidityScoringMode",
    "LiquiditySeriesLoad",
    "LiquiditySeriesRequest",
    "build_fred_global_liquidity_engine",
]
