"""Deterministic United States credit-cycle intelligence engine."""

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


class CreditCycleComponent(str, Enum):
    HIGH_YIELD_SPREAD = "high_yield_spread"
    INVESTMENT_GRADE_SPREAD = "investment_grade_spread"
    LENDING_STANDARDS = "lending_standards"
    BANK_CREDIT = "bank_credit"
    BUSINESS_DELINQUENCIES = "business_delinquencies"
    REFINANCING_COST = "refinancing_cost"


class CreditCycleScoringMode(str, Enum):
    CENTERED_LEVEL_INVERSE = "centered_level_inverse"
    CHANGE_POSITIVE = "change_positive"
    CHANGE_INVERSE = "change_inverse"


class CreditCycleLoadState(str, Enum):
    LOADED = "loaded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CreditCycleSeriesRequest:
    component: CreditCycleComponent
    series: SeriesSpecification
    limit: int
    comparison_periods: int
    weight: float
    scoring_mode: CreditCycleScoringMode
    sensitivity: float
    neutral_level: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.component, CreditCycleComponent):
            raise TypeError("component must be a CreditCycleComponent")
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
        if not isinstance(self.scoring_mode, CreditCycleScoringMode):
            raise TypeError("scoring_mode must be a CreditCycleScoringMode")
        for field_name in ("weight", "sensitivity"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be numeric")
            normalized = float(value)
            if not isfinite(normalized) or normalized <= 0:
                raise ValueError(f"{field_name} must be positive and finite")
            object.__setattr__(self, field_name, normalized)
        if self.scoring_mode is CreditCycleScoringMode.CENTERED_LEVEL_INVERSE:
            if isinstance(self.neutral_level, bool) or not isinstance(
                self.neutral_level, (int, float)
            ):
                raise TypeError(
                    "neutral_level must be numeric for centered level scoring"
                )
            normalized_level = float(self.neutral_level)
            if not isfinite(normalized_level):
                raise ValueError("neutral_level must be finite")
            object.__setattr__(self, "neutral_level", normalized_level)
        elif self.neutral_level is not None:
            raise ValueError(
                "neutral_level is only valid for centered level scoring"
            )


@dataclass(frozen=True, slots=True)
class CreditCycleSeriesLoad:
    request: CreditCycleSeriesRequest
    state: CreditCycleLoadState
    observations: tuple[NormalizedObservation, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, CreditCycleSeriesRequest):
            raise TypeError("request must be a CreditCycleSeriesRequest")
        if not isinstance(self.state, CreditCycleLoadState):
            raise TypeError("state must be a CreditCycleLoadState")
        if not all(
            isinstance(item, NormalizedObservation) for item in self.observations
        ):
            raise TypeError(
                "observations must contain NormalizedObservation values"
            )
        if self.state is CreditCycleLoadState.LOADED:
            if not self.observations:
                raise ValueError("loaded series requires observations")
            if self.error is not None:
                raise ValueError("loaded series cannot contain an error")
        else:
            if self.observations:
                raise ValueError(
                    "unavailable series cannot contain observations"
                )
            if not isinstance(self.error, str) or not self.error.strip():
                raise ValueError("unavailable series requires an error")


@dataclass(frozen=True, slots=True)
class CreditCycleRun:
    as_of: datetime
    provider: str
    loads: tuple[CreditCycleSeriesLoad, ...]
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
        if not all(
            isinstance(item, CreditCycleSeriesLoad) for item in self.loads
        ):
            raise TypeError("loads must contain CreditCycleSeriesLoad values")
        if not isinstance(self.result, AnalyticalEngineResult):
            raise TypeError("result must be an AnalyticalEngineResult")
        if self.result.as_of != self.as_of:
            raise ValueError("result must use the run as_of")

    @property
    def loaded_count(self) -> int:
        return sum(
            load.state is CreditCycleLoadState.LOADED for load in self.loads
        )

    @property
    def unavailable_count(self) -> int:
        return len(self.loads) - self.loaded_count


CREDIT_CYCLE_FRED_REQUESTS = (
    CreditCycleSeriesRequest(
        component=CreditCycleComponent.HIGH_YIELD_SPREAD,
        series=FRED_SERIES["high_yield_option_adjusted_spread"],
        limit=80,
        comparison_periods=20,
        weight=0.25,
        scoring_mode=CreditCycleScoringMode.CENTERED_LEVEL_INVERSE,
        sensitivity=4.0,
        neutral_level=4.5,
    ),
    CreditCycleSeriesRequest(
        component=CreditCycleComponent.INVESTMENT_GRADE_SPREAD,
        series=FRED_SERIES["investment_grade_option_adjusted_spread"],
        limit=80,
        comparison_periods=20,
        weight=0.15,
        scoring_mode=CreditCycleScoringMode.CENTERED_LEVEL_INVERSE,
        sensitivity=1.5,
        neutral_level=1.5,
    ),
    CreditCycleSeriesRequest(
        component=CreditCycleComponent.LENDING_STANDARDS,
        series=FRED_SERIES["commercial_industrial_lending_standards"],
        limit=12,
        comparison_periods=1,
        weight=0.20,
        scoring_mode=CreditCycleScoringMode.CENTERED_LEVEL_INVERSE,
        sensitivity=40.0,
        neutral_level=0.0,
    ),
    CreditCycleSeriesRequest(
        component=CreditCycleComponent.BANK_CREDIT,
        series=FRED_SERIES["commercial_industrial_loans"],
        limit=18,
        comparison_periods=12,
        weight=0.15,
        scoring_mode=CreditCycleScoringMode.CHANGE_POSITIVE,
        sensitivity=0.08,
    ),
    CreditCycleSeriesRequest(
        component=CreditCycleComponent.BUSINESS_DELINQUENCIES,
        series=FRED_SERIES["business_loan_delinquency_rate"],
        limit=12,
        comparison_periods=4,
        weight=0.15,
        scoring_mode=CreditCycleScoringMode.CENTERED_LEVEL_INVERSE,
        sensitivity=2.0,
        neutral_level=2.0,
    ),
    CreditCycleSeriesRequest(
        component=CreditCycleComponent.REFINANCING_COST,
        series=FRED_SERIES["high_yield_effective_yield"],
        limit=80,
        comparison_periods=20,
        weight=0.10,
        scoring_mode=CreditCycleScoringMode.CENTERED_LEVEL_INVERSE,
        sensitivity=5.0,
        neutral_level=7.0,
    ),
)


def _clip(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _quality_weight(
    observation: NormalizedObservation,
    as_of: datetime,
) -> float:
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
    request: CreditCycleSeriesRequest,
    observations: tuple[NormalizedObservation, ...],
) -> tuple[
    float,
    NormalizedObservation,
    NormalizedObservation | None,
    str,
]:
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
    if latest.value is None:
        raise ValueError("latest credit-cycle observation is missing")
    latest_value = float(latest.value)

    if request.scoring_mode is CreditCycleScoringMode.CENTERED_LEVEL_INVERSE:
        assert request.neutral_level is not None
        score = _clip(
            (request.neutral_level - latest_value) / request.sensitivity
        )
        explanation = (
            f"{request.component.value.replace('_', ' ').title()} is "
            f"{latest_value:,.2f}; the policy neutral level is "
            f"{request.neutral_level:,.2f}, producing a normalized "
            f"credit contribution of {score:+.2f}."
        )
        return score, latest, None, explanation

    baseline_index = max(
        0,
        len(ordered) - 1 - request.comparison_periods,
    )
    baseline = ordered[baseline_index]
    if baseline.value is None:
        raise ValueError("credit-cycle comparison observation is missing")
    baseline_value = float(baseline.value)
    denominator = max(abs(baseline_value), 1.0)
    raw_change = (latest_value - baseline_value) / denominator
    if request.scoring_mode is CreditCycleScoringMode.CHANGE_INVERSE:
        raw_change *= -1.0
    score = _clip(raw_change / request.sensitivity)
    raw_direction = "rose" if latest_value > baseline_value else "fell"
    explanation = (
        f"{request.component.value.replace('_', ' ').title()} "
        f"{raw_direction} from {baseline_value:,.2f} to "
        f"{latest_value:,.2f}; the normalized credit contribution is "
        f"{score:+.2f}."
    )
    return score, latest, baseline, explanation


def _direction(
    score: int,
    evidence: tuple[EngineEvidence, ...],
) -> EngineDirection:
    by_component = {item.component: item for item in evidence}
    high_yield = by_component.get(
        CreditCycleComponent.HIGH_YIELD_SPREAD.value
    )
    standards = by_component.get(
        CreditCycleComponent.LENDING_STANDARDS.value
    )
    delinquencies = by_component.get(
        CreditCycleComponent.BUSINESS_DELINQUENCIES.value
    )
    refinancing = by_component.get(
        CreditCycleComponent.REFINANCING_COST.value
    )
    market_stress = (
        high_yield is not None and high_yield.signal_score <= -0.75
    )
    fundamental_confirmation = any(
        item is not None and item.signal_score <= -0.50
        for item in (standards, delinquencies, refinancing)
    )
    if score <= 25 or (market_stress and fundamental_confirmation):
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
    by_component = {item.component: item for item in evidence}
    standards = by_component.get(
        CreditCycleComponent.LENDING_STANDARDS.value
    )
    bank_credit = by_component.get(CreditCycleComponent.BANK_CREDIT.value)
    if direction is EngineDirection.EXPANDING:
        if (
            standards is not None
            and standards.signal_score > 0.15
            and bank_credit is not None
            and bank_credit.signal_score > 0.15
        ):
            return "broad credit expansion"
        return "market-led credit easing"
    if direction is EngineDirection.NEUTRAL:
        return "mixed or transitional credit conditions"
    if direction is EngineDirection.CONTRACTING:
        return "credit tightening"
    if direction is EngineDirection.STRESSED:
        return "broad credit stress"
    return "unavailable"


def _transmission(direction: EngineDirection) -> tuple[str, ...]:
    if direction is EngineDirection.EXPANDING:
        return (
            "Easier credit can support refinancing, investment, and risk appetite.",
            "Lower-quality borrowers may gain greater access to capital, although valuation discipline remains necessary.",
            "Credit-sensitive equity and fixed-income exposures may receive a tailwind when market pricing and bank lending confirm one another.",
        )
    if direction is EngineDirection.CONTRACTING:
        return (
            "Tighter credit can raise refinancing costs and pressure leveraged borrowers.",
            "Lower-quality corporate bonds, small companies, and capital-intensive businesses may become more vulnerable.",
            "Portfolio liquidity and balance-sheet quality become more valuable as credit availability deteriorates.",
        )
    if direction is EngineDirection.STRESSED:
        return (
            "Broad credit stress can accelerate defaults, impair market liquidity, and amplify equity drawdowns.",
            "Highly leveraged and refinancing-dependent holdings face elevated downside risk.",
            "Cash reserves, concentration limits, and counterparty exposures deserve greater attention during credit stress.",
        )
    if direction is EngineDirection.UNAVAILABLE:
        return (
            "No credit-cycle portfolio conclusion is available because the required evidence could not be retrieved.",
        )
    return (
        "Mixed credit evidence does not provide a strong standalone portfolio signal.",
        "Portfolio decisions should rely on the broader evidence set rather than one spread or lending survey.",
    )


class CreditCycleEngine:
    """Retrieve point-in-time credit evidence and publish one typed result."""

    engine_name = "credit_cycle"
    scope = "United States corporate and bank credit conditions"
    policy_version = "credit-cycle-policy.v1"

    def __init__(
        self,
        provider: ObservationProvider,
        *,
        requests: tuple[
            CreditCycleSeriesRequest, ...
        ] = CREDIT_CYCLE_FRED_REQUESTS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(provider, ObservationProvider):
            raise TypeError("provider must implement ObservationProvider")
        if not requests:
            raise ValueError("requests cannot be empty")
        if not all(
            isinstance(item, CreditCycleSeriesRequest) for item in requests
        ):
            raise TypeError(
                "requests must contain CreditCycleSeriesRequest values"
            )
        components = [item.component for item in requests]
        if len(components) != len(set(components)):
            raise ValueError("credit-cycle request components must be unique")
        self.provider = provider
        self.requests = requests
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self, *, as_of: datetime) -> CreditCycleRun:
        if not isinstance(as_of, datetime):
            raise TypeError("as_of must be a datetime")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")

        loads: list[CreditCycleSeriesLoad] = []
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
                    CreditCycleSeriesLoad(
                        request=request,
                        state=CreditCycleLoadState.UNAVAILABLE,
                        error=str(error),
                    )
                )
                continue
            if not observations:
                loads.append(
                    CreditCycleSeriesLoad(
                        request=request,
                        state=CreditCycleLoadState.UNAVAILABLE,
                        error="provider returned no observations",
                    )
                )
                continue
            usable = tuple(
                item for item in observations if item.is_available_at(as_of)
            )
            if not usable:
                loads.append(
                    CreditCycleSeriesLoad(
                        request=request,
                        state=CreditCycleLoadState.UNAVAILABLE,
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
                    CreditCycleSeriesLoad(
                        request=request,
                        state=CreditCycleLoadState.UNAVAILABLE,
                        error=str(error),
                    )
                )
                continue
            loads.append(
                CreditCycleSeriesLoad(
                    request=request,
                    state=CreditCycleLoadState.LOADED,
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
        coverage = (
            0.0 if total_weight == 0 else loaded_weight / total_weight
        )
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
                summary="Credit-cycle evidence is unavailable.",
                explanation=(
                    "The engine could not retrieve any required point-in-time "
                    "credit series, so it does not present a credit conclusion."
                ),
                risks=tuple(
                    f"{load.request.component.value}: {load.error}"
                    for load in loads
                    if load.state is CreditCycleLoadState.UNAVAILABLE
                ),
                transmission_channels=_transmission(
                    EngineDirection.UNAVAILABLE
                ),
                review_conditions=(
                    "Re-run the engine after provider access and required series are restored.",
                ),
                evidence=(),
            )
            return CreditCycleRun(
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
        agreement = max(
            0.0,
            1.0 - min(1.0, mean_absolute_deviation),
        )
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
                f"United States credit conditions show {phase}."
            ),
            EngineDirection.NEUTRAL: (
                "United States credit conditions are mixed or transitional."
            ),
            EngineDirection.CONTRACTING: (
                "United States credit conditions are tightening."
            ),
            EngineDirection.STRESSED: (
                "United States credit conditions show broad market and borrower stress."
            ),
        }[direction]
        drivers: list[str] = []
        if positive:
            drivers.append(
                "supportive evidence led by "
                + ", ".join(
                    item.component.replace("_", " ")
                    for item in positive[:2]
                )
            )
        if negative:
            drivers.append(
                "restrictive evidence led by "
                + ", ".join(
                    item.component.replace("_", " ")
                    for item in negative[:2]
                )
            )
        explanation = (
            summary
            + (
                " The assessment reflects " + " while ".join(drivers) + "."
                if drivers
                else ""
            )
            + f" Weighted evidence coverage is {coverage:.0%}; "
            f"confidence is {confidence}%."
        )
        risks = [
            f"{load.request.component.value}: {load.error}"
            for load in loads
            if load.state is CreditCycleLoadState.UNAVAILABLE
        ]
        opposing = (
            negative
            if direction is EngineDirection.EXPANDING
            else positive
        )
        if opposing:
            risks.append(
                "Contradictory credit evidence remains in "
                + ", ".join(
                    item.component.replace("_", " ")
                    for item in opposing[:3]
                )
                + "."
            )
        by_component = {item.component: item for item in evidence}
        high_yield = by_component.get(
            CreditCycleComponent.HIGH_YIELD_SPREAD.value
        )
        standards = by_component.get(
            CreditCycleComponent.LENDING_STANDARDS.value
        )
        delinquencies = by_component.get(
            CreditCycleComponent.BUSINESS_DELINQUENCIES.value
        )
        if (
            high_yield is not None
            and high_yield.signal_score > 0.25
            and standards is not None
            and standards.signal_score < -0.25
        ):
            risks.append(
                "Market spreads remain easy while bank lending standards are tightening."
            )
        if (
            high_yield is not None
            and high_yield.signal_score > 0.25
            and delinquencies is not None
            and delinquencies.signal_score < -0.25
        ):
            risks.append(
                "Corporate bond pricing remains calm while business-loan performance is deteriorating."
            )
        if status is EngineDataStatus.STALE:
            risks.append(
                "At least half of the loaded credit-cycle evidence is stale at the decision time."
            )
        review_conditions = (
            "Reassess if the composite credit-cycle score crosses 45 or 60.",
            "Escalate review if high-yield spreads enter stress and either lending standards or delinquencies confirm deterioration.",
            "Reduce confidence when weighted evidence coverage falls below 75%.",
            "Review leveraged and refinancing-dependent portfolio exposure if four or more components become materially negative.",
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
        return CreditCycleRun(
            as_of=as_of,
            provider=self.provider.name,
            loads=tuple(loads),
            result=result,
        )

    def run_current(self) -> CreditCycleRun:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError(
                "clock must return a timezone-aware datetime"
            )
        return self.run(as_of=now)


def build_fred_credit_cycle_engine(
    *,
    provider: FREDProvider | None = None,
    clock: Callable[[], datetime] | None = None,
) -> CreditCycleEngine:
    return CreditCycleEngine(provider or FREDProvider(), clock=clock)


__all__ = [
    "CREDIT_CYCLE_FRED_REQUESTS",
    "CreditCycleComponent",
    "CreditCycleEngine",
    "CreditCycleLoadState",
    "CreditCycleRun",
    "CreditCycleScoringMode",
    "CreditCycleSeriesLoad",
    "CreditCycleSeriesRequest",
    "build_fred_credit_cycle_engine",
]
