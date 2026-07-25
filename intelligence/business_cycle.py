"""Deterministic U.S. business-cycle intelligence engine."""

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


class BusinessCycleComponent(str, Enum):
    REAL_GDP = "real_gdp"
    INDUSTRIAL_PRODUCTION = "industrial_production"
    REAL_CONSUMPTION = "real_consumption"
    PAYROLL_EMPLOYMENT = "payroll_employment"
    UNEMPLOYMENT = "unemployment"
    INITIAL_CLAIMS = "initial_claims"
    HOUSING_PERMITS = "housing_permits"


class BusinessCycleScoringMode(str, Enum):
    CHANGE_POSITIVE = "change_positive"
    CHANGE_INVERSE = "change_inverse"
    ABSOLUTE_CHANGE_INVERSE = "absolute_change_inverse"


class BusinessCycleLoadState(str, Enum):
    LOADED = "loaded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class BusinessCycleSeriesRequest:
    component: BusinessCycleComponent
    series: SeriesSpecification
    limit: int
    comparison_periods: int
    weight: float
    scoring_mode: BusinessCycleScoringMode
    sensitivity: float

    def __post_init__(self) -> None:
        if not isinstance(self.component, BusinessCycleComponent):
            raise TypeError("component must be a BusinessCycleComponent")
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
        if not isinstance(self.scoring_mode, BusinessCycleScoringMode):
            raise TypeError("scoring_mode must be a BusinessCycleScoringMode")
        for field_name in ("weight", "sensitivity"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be numeric")
            normalized = float(value)
            if not isfinite(normalized) or normalized <= 0:
                raise ValueError(f"{field_name} must be positive and finite")
            object.__setattr__(self, field_name, normalized)


@dataclass(frozen=True, slots=True)
class BusinessCycleSeriesLoad:
    request: BusinessCycleSeriesRequest
    state: BusinessCycleLoadState
    observations: tuple[NormalizedObservation, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, BusinessCycleSeriesRequest):
            raise TypeError("request must be a BusinessCycleSeriesRequest")
        if not isinstance(self.state, BusinessCycleLoadState):
            raise TypeError("state must be a BusinessCycleLoadState")
        if not all(isinstance(item, NormalizedObservation) for item in self.observations):
            raise TypeError("observations must contain NormalizedObservation values")
        if self.state is BusinessCycleLoadState.LOADED:
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
class BusinessCycleRun:
    as_of: datetime
    provider: str
    loads: tuple[BusinessCycleSeriesLoad, ...]
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
        if not all(isinstance(item, BusinessCycleSeriesLoad) for item in self.loads):
            raise TypeError("loads must contain BusinessCycleSeriesLoad values")
        if not isinstance(self.result, AnalyticalEngineResult):
            raise TypeError("result must be an AnalyticalEngineResult")
        if self.result.as_of != self.as_of:
            raise ValueError("result must use the run as_of")

    @property
    def loaded_count(self) -> int:
        return sum(
            load.state is BusinessCycleLoadState.LOADED for load in self.loads
        )

    @property
    def unavailable_count(self) -> int:
        return len(self.loads) - self.loaded_count


BUSINESS_CYCLE_FRED_REQUESTS = (
    BusinessCycleSeriesRequest(
        component=BusinessCycleComponent.REAL_GDP,
        series=FRED_SERIES["real_gdp"],
        limit=12,
        comparison_periods=4,
        weight=0.15,
        scoring_mode=BusinessCycleScoringMode.CHANGE_POSITIVE,
        sensitivity=0.03,
    ),
    BusinessCycleSeriesRequest(
        component=BusinessCycleComponent.INDUSTRIAL_PRODUCTION,
        series=FRED_SERIES["industrial_production"],
        limit=18,
        comparison_periods=12,
        weight=0.15,
        scoring_mode=BusinessCycleScoringMode.CHANGE_POSITIVE,
        sensitivity=0.04,
    ),
    BusinessCycleSeriesRequest(
        component=BusinessCycleComponent.REAL_CONSUMPTION,
        series=FRED_SERIES["real_personal_consumption"],
        limit=18,
        comparison_periods=12,
        weight=0.15,
        scoring_mode=BusinessCycleScoringMode.CHANGE_POSITIVE,
        sensitivity=0.04,
    ),
    BusinessCycleSeriesRequest(
        component=BusinessCycleComponent.PAYROLL_EMPLOYMENT,
        series=FRED_SERIES["nonfarm_payrolls"],
        limit=18,
        comparison_periods=12,
        weight=0.15,
        scoring_mode=BusinessCycleScoringMode.CHANGE_POSITIVE,
        sensitivity=0.025,
    ),
    BusinessCycleSeriesRequest(
        component=BusinessCycleComponent.UNEMPLOYMENT,
        series=FRED_SERIES["unemployment"],
        limit=8,
        comparison_periods=3,
        weight=0.15,
        scoring_mode=BusinessCycleScoringMode.ABSOLUTE_CHANGE_INVERSE,
        sensitivity=0.75,
    ),
    BusinessCycleSeriesRequest(
        component=BusinessCycleComponent.INITIAL_CLAIMS,
        series=FRED_SERIES["initial_jobless_claims"],
        limit=20,
        comparison_periods=13,
        weight=0.15,
        scoring_mode=BusinessCycleScoringMode.CHANGE_INVERSE,
        sensitivity=0.20,
    ),
    BusinessCycleSeriesRequest(
        component=BusinessCycleComponent.HOUSING_PERMITS,
        series=FRED_SERIES["housing_permits"],
        limit=18,
        comparison_periods=12,
        weight=0.10,
        scoring_mode=BusinessCycleScoringMode.CHANGE_POSITIVE,
        sensitivity=0.15,
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
    request: BusinessCycleSeriesRequest,
    observations: tuple[NormalizedObservation, ...],
) -> tuple[float, NormalizedObservation, NormalizedObservation, str]:
    ordered = tuple(
        sorted(
            observations,
            key=lambda item: (
                item.observation_date,
                item.provenance.released_at,
            ),
        )
    )
    latest = ordered[-1]
    baseline_index = max(0, len(ordered) - 1 - request.comparison_periods)
    baseline = ordered[baseline_index]
    if latest.value is None or baseline.value is None:
        raise ValueError("business-cycle comparison observations cannot be missing")

    latest_value = float(latest.value)
    baseline_value = float(baseline.value)
    if request.scoring_mode is BusinessCycleScoringMode.ABSOLUTE_CHANGE_INVERSE:
        raw_change = -(latest_value - baseline_value)
    else:
        denominator = max(abs(baseline_value), 1.0)
        raw_change = (latest_value - baseline_value) / denominator
        if request.scoring_mode is BusinessCycleScoringMode.CHANGE_INVERSE:
            raw_change *= -1.0
    score = _clip(raw_change / request.sensitivity)
    raw_direction = "rose" if latest_value > baseline_value else "fell"
    explanation = (
        f"{request.component.value.replace('_', ' ').title()} {raw_direction} "
        f"from {baseline_value:,.2f} to {latest_value:,.2f}; "
        f"the normalized business-cycle contribution is {score:+.2f}."
    )
    return score, latest, baseline, explanation


def _direction(score: int, evidence: tuple[EngineEvidence, ...]) -> EngineDirection:
    evidence_by_component = {item.component: item for item in evidence}
    unemployment = evidence_by_component.get(
        BusinessCycleComponent.UNEMPLOYMENT.value
    )
    claims = evidence_by_component.get(BusinessCycleComponent.INITIAL_CLAIMS.value)
    labor_stress = (
        unemployment is not None
        and claims is not None
        and unemployment.signal_score <= -0.75
        and claims.signal_score <= -0.75
    )
    if score <= 25 or labor_stress:
        return EngineDirection.STRESSED
    if score < 45:
        return EngineDirection.CONTRACTING
    if score <= 60:
        return EngineDirection.NEUTRAL
    return EngineDirection.EXPANDING


def _phase_description(
    direction: EngineDirection,
    evidence: tuple[EngineEvidence, ...],
) -> str:
    evidence_by_component = {item.component: item for item in evidence}
    leading = [
        evidence_by_component.get(BusinessCycleComponent.INITIAL_CLAIMS.value),
        evidence_by_component.get(BusinessCycleComponent.HOUSING_PERMITS.value),
    ]
    labor = [
        evidence_by_component.get(BusinessCycleComponent.PAYROLL_EMPLOYMENT.value),
        evidence_by_component.get(BusinessCycleComponent.UNEMPLOYMENT.value),
    ]
    leading_values = [item.signal_score for item in leading if item is not None]
    labor_values = [item.signal_score for item in labor if item is not None]
    leading_average = (
        sum(leading_values) / len(leading_values) if leading_values else 0.0
    )
    labor_average = sum(labor_values) / len(labor_values) if labor_values else 0.0
    if direction is EngineDirection.EXPANDING:
        if leading_average > 0.30 and labor_average < -0.05:
            return "early recovery"
        return "expansion"
    if direction is EngineDirection.NEUTRAL:
        return "slowdown or mixed conditions"
    if direction is EngineDirection.CONTRACTING:
        return "contraction"
    if direction is EngineDirection.STRESSED:
        return "broad contraction with labor stress"
    return "unavailable"


def _transmission(direction: EngineDirection) -> tuple[str, ...]:
    if direction is EngineDirection.EXPANDING:
        return (
            "Expanding activity can support corporate revenue and earnings breadth.",
            "Cyclical equity and credit exposures may receive a fundamental tailwind, subject to valuation and liquidity conditions.",
            "A healthy labor market can support household demand but may also keep policy-sensitive inflation risks relevant.",
        )
    if direction is EngineDirection.CONTRACTING:
        return (
            "Contracting activity can pressure earnings expectations and economically sensitive holdings.",
            "Lower-quality credit and highly operationally leveraged businesses may become more vulnerable.",
            "Defensive cash-flow quality and portfolio liquidity generally become more valuable as activity weakens.",
        )
    if direction is EngineDirection.STRESSED:
        return (
            "Broad economic stress can increase drawdown risk across cyclical equities and lower-quality credit.",
            "Labor deterioration can weaken consumption and raise default risk with a lag.",
            "Portfolio resilience, liquidity reserves, and concentration limits deserve greater attention during severe contraction.",
        )
    if direction is EngineDirection.UNAVAILABLE:
        return (
            "No business-cycle portfolio conclusion is available because the required evidence could not be retrieved.",
        )
    return (
        "Mixed business-cycle evidence does not provide a strong standalone portfolio signal.",
        "Portfolio decisions should depend on the broader evidence set and the investor's objectives rather than one ambiguous growth reading.",
    )


class BusinessCycleEngine:
    """Retrieve point-in-time real-economy evidence and publish one result."""

    engine_name = "business_cycle"
    scope = "United States real-economy business-cycle conditions"
    policy_version = "business-cycle-policy.v1"

    def __init__(
        self,
        provider: ObservationProvider,
        *,
        requests: tuple[
            BusinessCycleSeriesRequest, ...
        ] = BUSINESS_CYCLE_FRED_REQUESTS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(provider, ObservationProvider):
            raise TypeError("provider must implement ObservationProvider")
        if not requests:
            raise ValueError("requests cannot be empty")
        if not all(
            isinstance(item, BusinessCycleSeriesRequest) for item in requests
        ):
            raise TypeError(
                "requests must contain BusinessCycleSeriesRequest values"
            )
        components = [item.component for item in requests]
        if len(components) != len(set(components)):
            raise ValueError("business-cycle request components must be unique")
        self.provider = provider
        self.requests = requests
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self, *, as_of: datetime) -> BusinessCycleRun:
        if not isinstance(as_of, datetime):
            raise TypeError("as_of must be a datetime")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")

        loads: list[BusinessCycleSeriesLoad] = []
        evidence: list[EngineEvidence] = []
        loaded_weight = 0.0
        weighted_score = 0.0
        weighted_quality = 0.0
        stale_weight = 0.0

        for request in self.requests:
            query = ObservationQuery(
                series=request.series,
                as_of=as_of,
                limit=request.limit,
            )
            try:
                observations = tuple(self.provider.fetch(query))
            except ProviderError as error:
                loads.append(
                    BusinessCycleSeriesLoad(
                        request=request,
                        state=BusinessCycleLoadState.UNAVAILABLE,
                        error=str(error),
                    )
                )
                continue
            if not observations:
                loads.append(
                    BusinessCycleSeriesLoad(
                        request=request,
                        state=BusinessCycleLoadState.UNAVAILABLE,
                        error="provider returned no observations",
                    )
                )
                continue
            usable = tuple(
                item for item in observations if item.is_available_at(as_of)
            )
            if not usable:
                loads.append(
                    BusinessCycleSeriesLoad(
                        request=request,
                        state=BusinessCycleLoadState.UNAVAILABLE,
                        error=(
                            "no observations were available at the decision time"
                        ),
                    )
                )
                continue
            try:
                signal_score, latest, _baseline, explanation = _score_request(
                    request,
                    usable,
                )
            except ValueError as error:
                loads.append(
                    BusinessCycleSeriesLoad(
                        request=request,
                        state=BusinessCycleLoadState.UNAVAILABLE,
                        error=str(error),
                    )
                )
                continue
            loads.append(
                BusinessCycleSeriesLoad(
                    request=request,
                    state=BusinessCycleLoadState.LOADED,
                    observations=usable,
                )
            )
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
                    weighted_contribution=_clip(
                        request.weight * signal_score
                    ),
                    explanation=explanation,
                )
            )

        total_weight = sum(item.weight for item in self.requests)
        coverage = 0.0 if total_weight == 0 else loaded_weight / total_weight
        generated_at = as_of

        if loaded_weight == 0:
            result = AnalyticalEngineResult(
                identifier=(
                    f"analytical-engine:{self.engine_name}:{as_of.isoformat()}"
                ),
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
                summary="Business-cycle evidence is unavailable.",
                explanation=(
                    "The engine could not retrieve any required point-in-time "
                    "real-economy series, so it does not present a cycle conclusion."
                ),
                risks=tuple(
                    f"{load.request.component.value}: {load.error}"
                    for load in loads
                    if load.state is BusinessCycleLoadState.UNAVAILABLE
                ),
                transmission_channels=_transmission(
                    EngineDirection.UNAVAILABLE
                ),
                review_conditions=(
                    "Re-run the engine after provider access and required series are restored.",
                ),
                evidence=(),
            )
            return BusinessCycleRun(
                as_of=as_of,
                provider=self.provider.name,
                loads=tuple(loads),
                result=result,
            )

        composite = weighted_score / loaded_weight
        score = max(0, min(100, round(50 + 50 * composite)))
        direction = _direction(score, tuple(evidence))
        mean_absolute_deviation = sum(
            next(
                request.weight
                for request in self.requests
                if request.component.value == item.component
            )
            * abs(item.signal_score - composite)
            for item in evidence
        ) / loaded_weight
        agreement = max(0.0, 1.0 - min(1.0, mean_absolute_deviation))
        quality = weighted_quality / loaded_weight
        confidence = round(
            100 * (0.50 * coverage + 0.30 * quality + 0.20 * agreement)
        )
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
        phase = _phase_description(direction, tuple(evidence))
        summary = {
            EngineDirection.EXPANDING: (
                f"The U.S. business cycle is in {phase}."
            ),
            EngineDirection.NEUTRAL: (
                "The U.S. business cycle shows slowdown or mixed conditions."
            ),
            EngineDirection.CONTRACTING: (
                "The U.S. business cycle is contracting."
            ),
            EngineDirection.STRESSED: (
                "The U.S. business cycle is under broad economic and labor stress."
            ),
        }[direction]
        drivers: list[str] = []
        if positive:
            drivers.append(
                "supportive evidence led by "
                + ", ".join(
                    item.component.replace("_", " ") for item in positive[:2]
                )
            )
        if negative:
            drivers.append(
                "weak evidence led by "
                + ", ".join(
                    item.component.replace("_", " ") for item in negative[:2]
                )
            )
        explanation = (
            summary
            + (
                " The assessment reflects " + " while ".join(drivers) + "."
                if drivers
                else ""
            )
            + f" Weighted evidence coverage is {coverage:.0%}; confidence is {confidence}%."
        )
        risks = [
            f"{load.request.component.value}: {load.error}"
            for load in loads
            if load.state is BusinessCycleLoadState.UNAVAILABLE
        ]
        opposing = negative if direction is EngineDirection.EXPANDING else positive
        if opposing:
            risks.append(
                "Contradictory business-cycle evidence remains in "
                + ", ".join(
                    item.component.replace("_", " ") for item in opposing[:3]
                )
                + "."
            )
        evidence_by_component = {item.component: item for item in evidence}
        labor = evidence_by_component.get(
            BusinessCycleComponent.PAYROLL_EMPLOYMENT.value
        )
        production = evidence_by_component.get(
            BusinessCycleComponent.INDUSTRIAL_PRODUCTION.value
        )
        permits = evidence_by_component.get(
            BusinessCycleComponent.HOUSING_PERMITS.value
        )
        if (
            labor is not None
            and labor.signal_score > 0.20
            and production is not None
            and production.signal_score < -0.20
        ):
            risks.append(
                "Payroll growth remains resilient while industrial production weakens."
            )
        if (
            permits is not None
            and permits.signal_score < -0.40
            and direction is EngineDirection.EXPANDING
        ):
            risks.append(
                "Housing permits are weakening despite the positive composite cycle reading."
            )
        if status is EngineDataStatus.STALE:
            risks.append(
                "At least half of the loaded business-cycle evidence is stale at the decision time."
            )
        review_conditions = (
            "Reassess if the composite business-cycle score crosses 45 or 60.",
            "Escalate review if unemployment and initial claims both move into the stressed range.",
            "Reduce confidence when weighted evidence coverage falls below 75%.",
            "Review cyclical portfolio exposure if four or more components become materially negative.",
        )
        result = AnalyticalEngineResult(
            identifier=(
                f"analytical-engine:{self.engine_name}:{as_of.isoformat()}"
            ),
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
            review_conditions=review_conditions,
            evidence=tuple(evidence),
        )
        return BusinessCycleRun(
            as_of=as_of,
            provider=self.provider.name,
            loads=tuple(loads),
            result=result,
        )

    def run_current(self) -> BusinessCycleRun:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return self.run(as_of=now)


def build_fred_business_cycle_engine(
    *,
    provider: FREDProvider | None = None,
    clock: Callable[[], datetime] | None = None,
) -> BusinessCycleEngine:
    return BusinessCycleEngine(provider or FREDProvider(), clock=clock)


__all__ = [
    "BUSINESS_CYCLE_FRED_REQUESTS",
    "BusinessCycleComponent",
    "BusinessCycleEngine",
    "BusinessCycleLoadState",
    "BusinessCycleRun",
    "BusinessCycleScoringMode",
    "BusinessCycleSeriesLoad",
    "BusinessCycleSeriesRequest",
    "build_fred_business_cycle_engine",
]
