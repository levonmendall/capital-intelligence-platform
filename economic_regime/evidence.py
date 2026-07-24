"""Point-in-time evidence construction for economic-regime decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from math import isfinite
from typing import Iterable

from data import DataQualityState, NormalizedObservation
from economic_regime.engine import (
    EconomicRegimeEngine,
    EconomicRegimeInputs,
    EconomicRegimeResult,
)


class RegimeSignalName(str, Enum):
    """Canonical inputs consumed by the economic-regime engine."""

    GROWTH = "growth"
    INFLATION = "inflation"
    POLICY = "policy"
    LIQUIDITY = "liquidity"
    FINANCIAL_STRESS = "financial_stress"


_QUALITY_WEIGHTS = {
    DataQualityState.LIVE: 1.0,
    DataQualityState.CACHED: 0.90,
    DataQualityState.FIXTURE: 0.85,
    DataQualityState.STALE: 0.50,
    DataQualityState.FALLBACK: 0.35,
    DataQualityState.MISSING: 0.0,
}


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _bounded_score(value: float) -> float:
    if not isfinite(value):
        raise ValueError("regime score must be finite")
    return round(max(-1.0, min(1.0, value)), 4)


@dataclass(frozen=True, slots=True)
class RegimeScoringRules:
    """Versioned, deterministic transformations from evidence to scores."""

    version: str = "fred-us-v1"
    growth_full_scale_percent: float = 5.0
    inflation_target_percent: float = 2.0
    inflation_full_scale_deviation: float = 4.0
    real_policy_full_scale_percent: float = 4.0
    liquidity_full_scale_percent: float = 20.0
    stress_full_scale_index: float = 4.0
    year_over_year_tolerance_days: int = 45

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "version",
            _required_text(self.version, field_name="version"),
        )
        for field_name in (
            "growth_full_scale_percent",
            "inflation_full_scale_deviation",
            "real_policy_full_scale_percent",
            "liquidity_full_scale_percent",
            "stress_full_scale_index",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(
                value,
                (int, float),
            ):
                raise TypeError(f"{field_name} must be numeric")
            if not isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{field_name} must be positive")
        if (
            isinstance(self.year_over_year_tolerance_days, bool)
            or not isinstance(
                self.year_over_year_tolerance_days,
                int,
            )
        ):
            raise TypeError(
                "year_over_year_tolerance_days must be an int"
            )
        if not 0 <= self.year_over_year_tolerance_days <= 183:
            raise ValueError(
                "year_over_year_tolerance_days must be between "
                "0 and 183"
            )


@dataclass(frozen=True, slots=True)
class ObservationLineage:
    """Immutable reference to evidence used by one regime signal."""

    provider: str
    series_identifier: str
    observation_date: date
    released_at: datetime
    retrieved_at: datetime
    quality_state: DataQualityState
    value: float

    @classmethod
    def from_observation(
        cls,
        observation: NormalizedObservation,
        *,
        as_of: datetime | None = None,
    ) -> ObservationLineage:
        if not isinstance(observation, NormalizedObservation):
            raise TypeError(
                "observation must be a NormalizedObservation"
            )
        if observation.value is None:
            raise ValueError("lineage observation requires a value")
        quality_state = observation.provenance.quality_state
        if (
            as_of is not None
            and observation.is_stale_at(as_of)
        ):
            quality_state = DataQualityState.STALE
        return cls(
            provider=observation.provenance.provider,
            series_identifier=(
                observation.provenance.series_identifier
            ),
            observation_date=observation.observation_date,
            released_at=observation.provenance.released_at,
            retrieved_at=observation.provenance.retrieved_at,
            quality_state=quality_state,
            value=observation.value,
        )


@dataclass(frozen=True, slots=True)
class RegimeSignalEvidence:
    """One normalized regime signal and its source observations."""

    name: RegimeSignalName
    score: float | None
    calculation: str
    lineage: tuple[ObservationLineage, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, RegimeSignalName):
            raise TypeError("name must be a RegimeSignalName")
        object.__setattr__(
            self,
            "calculation",
            _required_text(
                self.calculation,
                field_name="calculation",
            ),
        )
        if self.score is None:
            if self.lineage:
                raise ValueError(
                    "missing signal cannot contain lineage"
                )
            return
        if isinstance(self.score, bool) or not isinstance(
            self.score,
            (int, float),
        ):
            raise TypeError("score must be numeric or None")
        normalized = float(self.score)
        if not -1.0 <= normalized <= 1.0:
            raise ValueError("score must be between -1.0 and 1.0")
        if not self.lineage:
            raise ValueError("scored signal requires lineage")
        if not all(
            isinstance(item, ObservationLineage)
            for item in self.lineage
        ):
            raise TypeError(
                "lineage must contain ObservationLineage values"
            )
        object.__setattr__(self, "score", normalized)

    @property
    def quality_score(self) -> float:
        """Return the weakest disclosed quality among dependencies."""

        if self.score is None:
            return 0.0
        return min(
            _QUALITY_WEIGHTS[item.quality_state]
            for item in self.lineage
        )


@dataclass(frozen=True, slots=True)
class RegimeEvidenceSnapshot:
    """Auditable point-in-time input set for regime classification."""

    as_of: datetime
    rules_version: str
    signals: tuple[RegimeSignalEvidence, ...]

    def __post_init__(self) -> None:
        _aware_datetime(self.as_of, field_name="as_of")
        object.__setattr__(
            self,
            "rules_version",
            _required_text(
                self.rules_version,
                field_name="rules_version",
            ),
        )
        expected = set(RegimeSignalName)
        observed = {signal.name for signal in self.signals}
        if observed != expected or len(self.signals) != len(expected):
            raise ValueError(
                "signals must contain each canonical regime signal once"
            )

    @property
    def inputs(self) -> EconomicRegimeInputs:
        scores = {
            signal.name: signal.score for signal in self.signals
        }
        return EconomicRegimeInputs(
            growth=scores[RegimeSignalName.GROWTH],
            inflation=scores[RegimeSignalName.INFLATION],
            policy=scores[RegimeSignalName.POLICY],
            liquidity=scores[RegimeSignalName.LIQUIDITY],
            financial_stress=scores[
                RegimeSignalName.FINANCIAL_STRESS
            ],
        )

    @property
    def data_coverage(self) -> float:
        available = sum(
            signal.score is not None for signal in self.signals
        )
        return round(available / len(self.signals), 4)

    @property
    def quality_score(self) -> float:
        return round(
            sum(signal.quality_score for signal in self.signals)
            / len(self.signals),
            4,
        )


@dataclass(frozen=True, slots=True)
class EvidenceBasedRegimeResult:
    """Regime output with evidence-adjusted confidence."""

    evidence: RegimeEvidenceSnapshot
    result: EconomicRegimeResult
    confidence: float

    def __post_init__(self) -> None:
        expected = round(
            self.result.confidence * self.evidence.quality_score,
            4,
        )
        if self.confidence != expected:
            raise ValueError(
                "confidence must equal engine confidence times "
                "evidence quality"
            )


class RegimeEvidenceBuilder:
    """Build versioned regime inputs from canonical observations."""

    _SERIES = {
        RegimeSignalName.GROWTH: ("FRED", "INDPRO"),
        RegimeSignalName.INFLATION: ("FRED", "CPIAUCSL"),
        RegimeSignalName.POLICY: ("FRED", "FEDFUNDS"),
        RegimeSignalName.LIQUIDITY: ("FRED", "WALCL"),
        RegimeSignalName.FINANCIAL_STRESS: (
            "FRED",
            "STLFSI4",
        ),
    }

    def __init__(
        self,
        rules: RegimeScoringRules | None = None,
    ) -> None:
        self.rules = rules or RegimeScoringRules()

    def build(
        self,
        observations: Iterable[NormalizedObservation],
        *,
        as_of: datetime,
    ) -> RegimeEvidenceSnapshot:
        decision_time = _aware_datetime(as_of, field_name="as_of")
        grouped = self._available_by_series(
            observations,
            as_of=decision_time,
        )

        growth = self._year_over_year_signal(
            RegimeSignalName.GROWTH,
            grouped,
            scale=self.rules.growth_full_scale_percent,
            offset=0.0,
            as_of=decision_time,
        )
        inflation = self._year_over_year_signal(
            RegimeSignalName.INFLATION,
            grouped,
            scale=self.rules.inflation_full_scale_deviation,
            offset=self.rules.inflation_target_percent,
            as_of=decision_time,
        )
        policy = self._policy_signal(
            grouped,
            inflation,
            as_of=decision_time,
        )
        liquidity = self._year_over_year_signal(
            RegimeSignalName.LIQUIDITY,
            grouped,
            scale=self.rules.liquidity_full_scale_percent,
            offset=0.0,
            as_of=decision_time,
        )
        stress = self._level_signal(
            RegimeSignalName.FINANCIAL_STRESS,
            grouped,
            scale=self.rules.stress_full_scale_index,
            as_of=decision_time,
        )

        return RegimeEvidenceSnapshot(
            as_of=decision_time,
            rules_version=self.rules.version,
            signals=(
                growth,
                inflation,
                policy,
                liquidity,
                stress,
            ),
        )

    def evaluate(
        self,
        observations: Iterable[NormalizedObservation],
        *,
        as_of: datetime,
        engine: EconomicRegimeEngine | None = None,
    ) -> EvidenceBasedRegimeResult:
        evidence = self.build(observations, as_of=as_of)
        result = (engine or EconomicRegimeEngine()).evaluate(
            evidence.inputs
        )
        return EvidenceBasedRegimeResult(
            evidence=evidence,
            result=result,
            confidence=round(
                result.confidence * evidence.quality_score,
                4,
            ),
        )

    def _available_by_series(
        self,
        observations: Iterable[NormalizedObservation],
        *,
        as_of: datetime,
    ) -> dict[
        tuple[str, str],
        list[NormalizedObservation],
    ]:
        grouped: dict[
            tuple[str, str],
            list[NormalizedObservation],
        ] = {}
        for observation in observations:
            if not isinstance(observation, NormalizedObservation):
                raise TypeError(
                    "observations must contain "
                    "NormalizedObservation values"
                )
            if not observation.is_available_at(as_of):
                continue
            source_key = (
                observation.provenance.provider,
                observation.provenance.series_identifier
            )
            grouped.setdefault(source_key, []).append(observation)
        for values in grouped.values():
            values.sort(
                key=lambda item: (
                    item.observation_date,
                    item.provenance.released_at,
                ),
                reverse=True,
            )
        return grouped

    def _year_over_year_signal(
        self,
        name: RegimeSignalName,
        grouped: dict[
            tuple[str, str],
            list[NormalizedObservation],
        ],
        *,
        scale: float,
        offset: float,
        as_of: datetime,
    ) -> RegimeSignalEvidence:
        pair = self._year_over_year_pair(
            grouped.get(self._SERIES[name], []),
            tolerance_days=(
                self.rules.year_over_year_tolerance_days
            ),
        )
        if pair is None:
            return RegimeSignalEvidence(
                name=name,
                score=None,
                calculation=(
                    "missing a current and year-earlier observation"
                ),
            )
        current, prior = pair
        if prior.value == 0:
            return RegimeSignalEvidence(
                name=name,
                score=None,
                calculation="year-earlier value cannot be zero",
            )
        change = ((current.value / prior.value) - 1.0) * 100.0
        score = _bounded_score((change - offset) / scale)
        return RegimeSignalEvidence(
            name=name,
            score=score,
            calculation=(
                f"(({current.value} / {prior.value}) - 1) * 100; "
                f"offset={offset}; scale={scale}"
            ),
            lineage=(
                ObservationLineage.from_observation(
                    current,
                    as_of=as_of,
                ),
                ObservationLineage.from_observation(
                    prior,
                    as_of=as_of,
                ),
            ),
        )

    def _policy_signal(
        self,
        grouped: dict[
            tuple[str, str],
            list[NormalizedObservation],
        ],
        inflation: RegimeSignalEvidence,
        *,
        as_of: datetime,
    ) -> RegimeSignalEvidence:
        policy_values = grouped.get(
            self._SERIES[RegimeSignalName.POLICY],
            [],
        )
        inflation_pair = self._year_over_year_pair(
            grouped.get(
                self._SERIES[RegimeSignalName.INFLATION],
                [],
            ),
            tolerance_days=(
                self.rules.year_over_year_tolerance_days
            ),
        )
        if not policy_values or inflation_pair is None:
            return RegimeSignalEvidence(
                name=RegimeSignalName.POLICY,
                score=None,
                calculation=(
                    "missing policy rate or year-over-year inflation"
                ),
            )
        policy = policy_values[0]
        current_cpi, prior_cpi = inflation_pair
        if prior_cpi.value == 0:
            return RegimeSignalEvidence(
                name=RegimeSignalName.POLICY,
                score=None,
                calculation="year-earlier CPI cannot be zero",
            )
        inflation_rate = (
            (current_cpi.value / prior_cpi.value) - 1.0
        ) * 100.0
        real_policy = policy.value - inflation_rate
        return RegimeSignalEvidence(
            name=RegimeSignalName.POLICY,
            score=_bounded_score(
                real_policy
                / self.rules.real_policy_full_scale_percent
            ),
            calculation=(
                f"({policy.value} - {inflation_rate:.4f}) / "
                f"{self.rules.real_policy_full_scale_percent}"
            ),
            lineage=(
                ObservationLineage.from_observation(
                    policy,
                    as_of=as_of,
                ),
                *inflation.lineage,
            ),
        )

    def _level_signal(
        self,
        name: RegimeSignalName,
        grouped: dict[
            tuple[str, str],
            list[NormalizedObservation],
        ],
        *,
        scale: float,
        as_of: datetime,
    ) -> RegimeSignalEvidence:
        values = grouped.get(self._SERIES[name], [])
        if not values:
            return RegimeSignalEvidence(
                name=name,
                score=None,
                calculation="missing current observation",
            )
        current = values[0]
        return RegimeSignalEvidence(
            name=name,
            score=_bounded_score(current.value / scale),
            calculation=f"{current.value} / {scale}",
            lineage=(
                ObservationLineage.from_observation(
                    current,
                    as_of=as_of,
                ),
            ),
        )

    @staticmethod
    def _year_over_year_pair(
        values: list[NormalizedObservation],
        *,
        tolerance_days: int,
    ) -> tuple[
        NormalizedObservation,
        NormalizedObservation,
    ] | None:
        if len(values) < 2:
            return None
        current = values[0]
        try:
            target = current.observation_date.replace(
                year=current.observation_date.year - 1
            )
        except ValueError:
            target = current.observation_date.replace(
                year=current.observation_date.year - 1,
                day=28,
            )
        candidates = [
            value
            for value in values[1:]
            if (
                value.observation_date
                < current.observation_date
                and abs(
                    (value.observation_date - target).days
                )
                <= tolerance_days
            )
        ]
        if not candidates:
            return None
        prior = min(
            candidates,
            key=lambda value: (
                abs((value.observation_date - target).days),
                -value.observation_date.toordinal(),
                -value.provenance.released_at.timestamp(),
            ),
        )
        return current, prior


__all__ = [
    "EvidenceBasedRegimeResult",
    "ObservationLineage",
    "RegimeEvidenceBuilder",
    "RegimeEvidenceSnapshot",
    "RegimeScoringRules",
    "RegimeSignalEvidence",
    "RegimeSignalName",
]
