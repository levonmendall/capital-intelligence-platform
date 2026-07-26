"""Deterministic point-in-time equity-market valuation intelligence engine."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from data import DataQualityState
from intelligence.analytical_engine import (
    AnalyticalEngineResult,
    EngineDataStatus,
    EngineDirection,
    EngineEvidence,
)


class ValuationDataError(RuntimeError):
    """Raised when a valuation source is unavailable or invalid."""


class ValuationMetric(str, Enum):
    """Yield-oriented measures where a higher value means more valuation support."""

    EARNINGS_YIELD = "earnings_yield"
    FREE_CASH_FLOW_YIELD = "free_cash_flow_yield"
    SALES_YIELD = "sales_yield"
    BOOK_YIELD = "book_yield"
    DIVIDEND_YIELD = "dividend_yield"
    EQUITY_RISK_PREMIUM = "equity_risk_premium"


class ValuationLoadState(str, Enum):
    """Whether one valuation component was usable."""

    LOADED = "loaded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ValuationObservation:
    """One point-in-time benchmark valuation observation."""

    metric: ValuationMetric
    value: float
    observation_date: date
    available_at: datetime
    retrieved_at: datetime
    quality_state: DataQualityState
    source_identifier: str
    benchmark: str
    methodology_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.metric, ValuationMetric):
            raise TypeError("metric must be a ValuationMetric")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise TypeError("value must be numeric")
        normalized = float(self.value)
        if not isfinite(normalized):
            raise ValueError("value must be finite")
        object.__setattr__(self, "value", normalized)
        if isinstance(self.observation_date, datetime) or not isinstance(
            self.observation_date, date
        ):
            raise TypeError("observation_date must be a date")
        available_at = _require_aware(self.available_at, "available_at")
        retrieved_at = _require_aware(self.retrieved_at, "retrieved_at")
        if available_at > retrieved_at:
            raise ValueError("available_at cannot be later than retrieved_at")
        if self.observation_date > available_at.date():
            raise ValueError("observation_date cannot be later than available_at")
        if not isinstance(self.quality_state, DataQualityState):
            raise TypeError("quality_state must be a DataQualityState")
        if self.quality_state is DataQualityState.MISSING:
            raise ValueError("valuation observations cannot use missing quality")
        for field_name in ("source_identifier", "benchmark", "methodology_version"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())


@dataclass(frozen=True, slots=True)
class ValuationDataset:
    """Immutable valuation history for one benchmark and methodology."""

    provider: str
    source_identifier: str
    source_fingerprint: str
    benchmark: str
    currency: str
    methodology_version: str
    retrieved_at: datetime
    observations: tuple[ValuationObservation, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "provider",
            "source_identifier",
            "benchmark",
            "currency",
            "methodology_version",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            normalized = (
                value.strip().upper()
                if field_name in {"provider", "currency"}
                else value.strip()
            )
            object.__setattr__(self, field_name, normalized)
        if (
            not isinstance(self.source_fingerprint, str)
            or len(self.source_fingerprint.strip()) != 64
            or any(
                character not in "0123456789abcdefABCDEF"
                for character in self.source_fingerprint
            )
        ):
            raise ValueError(
                "source_fingerprint must be a 64-character SHA-256 hex digest"
            )
        object.__setattr__(
            self, "source_fingerprint", self.source_fingerprint.strip().lower()
        )
        retrieved_at = _require_aware(self.retrieved_at, "retrieved_at")
        if not isinstance(self.observations, tuple) or not self.observations:
            raise ValueError("observations must be a non-empty tuple")
        if not all(
            isinstance(observation, ValuationObservation)
            for observation in self.observations
        ):
            raise TypeError("observations must contain ValuationObservation values")
        for observation in self.observations:
            if observation.benchmark != self.benchmark:
                raise ValueError("all observations must use the dataset benchmark")
            if observation.methodology_version != self.methodology_version:
                raise ValueError(
                    "all observations must use the dataset methodology version"
                )
            if observation.retrieved_at > retrieved_at:
                raise ValueError(
                    "observation retrieved_at cannot exceed dataset retrieved_at"
                )
        identities = [
            (
                observation.metric,
                observation.observation_date,
                observation.available_at,
            )
            for observation in self.observations
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("valuation observations cannot contain duplicates")


@runtime_checkable
class ValuationDataProvider(Protocol):
    """Provider for one immutable point-in-time valuation history."""

    @property
    def name(self) -> str:
        """Stable provider identifier."""

    def fetch(self, *, as_of: datetime) -> ValuationDataset:
        """Return valuation evidence available at the decision timestamp."""


@dataclass(frozen=True, slots=True)
class ValuationMetricLoad:
    """One scored or unavailable valuation component."""

    metric: ValuationMetric
    state: ValuationLoadState
    latest: ValuationObservation | None = None
    history_count: int = 0
    percentile: float | None = None
    signal: float | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.metric, ValuationMetric):
            raise TypeError("metric must be a ValuationMetric")
        if not isinstance(self.state, ValuationLoadState):
            raise TypeError("state must be a ValuationLoadState")
        if isinstance(self.history_count, bool) or not isinstance(
            self.history_count, int
        ):
            raise TypeError("history_count must be an int")
        if self.history_count < 0:
            raise ValueError("history_count cannot be negative")
        if self.state is ValuationLoadState.LOADED:
            if not isinstance(self.latest, ValuationObservation):
                raise ValueError("loaded metrics require a latest observation")
            if self.percentile is None or self.signal is None:
                raise ValueError("loaded metrics require percentile and signal")
            if not 0.0 <= float(self.percentile) <= 1.0:
                raise ValueError("percentile must be between 0 and 1")
            if not -1.0 <= float(self.signal) <= 1.0:
                raise ValueError("signal must be between -1 and 1")
            if self.error is not None:
                raise ValueError("loaded metrics cannot contain an error")
        else:
            if self.latest is not None:
                raise ValueError("unavailable metrics cannot contain latest")
            if self.percentile is not None or self.signal is not None:
                raise ValueError(
                    "unavailable metrics cannot contain percentile or signal"
                )
            if not isinstance(self.error, str) or not self.error.strip():
                raise ValueError("unavailable metrics require an error")


@dataclass(frozen=True, slots=True)
class ValuationRun:
    """Detailed valuation execution plus the shared analytical result."""

    as_of: datetime
    provider: str
    dataset: ValuationDataset | None
    loads: tuple[ValuationMetricLoad, ...]
    result: AnalyticalEngineResult

    @property
    def loaded_count(self) -> int:
        return sum(load.state is ValuationLoadState.LOADED for load in self.loads)

    @property
    def unavailable_count(self) -> int:
        return len(self.loads) - self.loaded_count


@dataclass(frozen=True, slots=True)
class _Component:
    metric: ValuationMetric
    signal: float
    percentile: float
    history_count: int
    latest: ValuationObservation
    quality: float
    stale: bool
    explanation: str


_METRIC_WEIGHTS = {
    ValuationMetric.EARNINGS_YIELD: 0.22,
    ValuationMetric.FREE_CASH_FLOW_YIELD: 0.22,
    ValuationMetric.SALES_YIELD: 0.13,
    ValuationMetric.BOOK_YIELD: 0.10,
    ValuationMetric.DIVIDEND_YIELD: 0.13,
    ValuationMetric.EQUITY_RISK_PREMIUM: 0.20,
}

_QUALITY_WEIGHT = {
    DataQualityState.LIVE: 1.00,
    DataQualityState.FIXTURE: 1.00,
    DataQualityState.CACHED: 0.90,
    DataQualityState.FALLBACK: 0.60,
    DataQualityState.STALE: 0.40,
    DataQualityState.MISSING: 0.00,
}

_NONPOSITIVE_INVALID = {
    ValuationMetric.EARNINGS_YIELD,
    ValuationMetric.FREE_CASH_FLOW_YIELD,
    ValuationMetric.SALES_YIELD,
    ValuationMetric.BOOK_YIELD,
}

_METRIC_LABELS = {
    ValuationMetric.EARNINGS_YIELD: "earnings yield",
    ValuationMetric.FREE_CASH_FLOW_YIELD: "free-cash-flow yield",
    ValuationMetric.SALES_YIELD: "sales yield",
    ValuationMetric.BOOK_YIELD: "book-value yield",
    ValuationMetric.DIVIDEND_YIELD: "dividend yield",
    ValuationMetric.EQUITY_RISK_PREMIUM: "equity risk premium",
}


class UnavailableValuationProvider:
    """Explicit unavailable provider until a licensed source is configured."""

    name = "UNCONFIGURED_VALUATION"

    def fetch(self, *, as_of: datetime) -> ValuationDataset:
        _require_aware(as_of, "as_of")
        raise ValuationDataError(
            "valuation source is not configured; set "
            "CAPITAL_INTELLIGENCE_VALUATION_FILE to an immutable provider export"
        )


class JSONValuationProvider:
    """Read one immutable benchmark valuation-history export."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self._payload: dict[str, Any] | None = None
        self._fingerprint: str | None = None

    @property
    def name(self) -> str:
        payload = self._load()
        return str(payload.get("provider", "FILE_VALUATION")).strip().upper()

    def _load(self) -> dict[str, Any]:
        if self._payload is None:
            try:
                raw = self.path.read_bytes()
            except OSError as error:
                raise ValuationDataError(
                    f"valuation file is unavailable: {self.path}: {error}"
                ) from error
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValuationDataError(
                    f"valuation file is not valid UTF-8 JSON: {self.path}"
                ) from error
            if not isinstance(payload, dict):
                raise ValuationDataError("valuation document must be a JSON object")
            if payload.get("schema_version") != "valuation-input.v1":
                raise ValuationDataError(
                    "valuation document must use valuation-input.v1"
                )
            self._payload = payload
            self._fingerprint = hashlib.sha256(raw).hexdigest()
        return self._payload

    def fetch(self, *, as_of: datetime) -> ValuationDataset:
        resolved = _require_aware(as_of, "as_of")
        payload = self._load()
        benchmark = str(payload.get("benchmark", "")).strip()
        methodology_version = str(payload.get("methodology_version", "")).strip()
        if not benchmark or not methodology_version:
            raise ValuationDataError(
                "valuation document requires benchmark and methodology_version"
            )
        observations_payload = payload.get("observations")
        if not isinstance(observations_payload, list):
            raise ValuationDataError("valuation document is missing observations")
        observations: list[ValuationObservation] = []
        for item in observations_payload:
            if not isinstance(item, dict):
                continue
            available_at = _parse_datetime(
                item.get("available_at"), "observation.available_at"
            )
            if available_at > resolved:
                continue
            retrieved_at = _parse_datetime(
                item.get("retrieved_at", item.get("available_at")),
                "observation.retrieved_at",
            )
            observations.append(
                ValuationObservation(
                    metric=ValuationMetric(str(item.get("metric", ""))),
                    value=float(item["value"]),
                    observation_date=_parse_date(
                        item.get("observation_date"),
                        "observation.observation_date",
                    ),
                    available_at=available_at,
                    retrieved_at=retrieved_at,
                    quality_state=_quality_state(
                        item.get("quality_state", "cached")
                    ),
                    source_identifier=str(
                        item.get(
                            "source_identifier",
                            payload.get("source_identifier", self.path.name),
                        )
                    ),
                    benchmark=benchmark,
                    methodology_version=methodology_version,
                )
            )
        if not observations:
            raise ValuationDataError(
                "no valuation observations were available at as_of"
            )
        dataset_retrieved_at = max(
            observation.retrieved_at for observation in observations
        )
        return ValuationDataset(
            provider=self.name,
            source_identifier=str(payload.get("source_identifier", self.path.name)),
            source_fingerprint=str(self._fingerprint),
            benchmark=benchmark,
            currency=str(payload.get("currency", "USD")),
            methodology_version=methodology_version,
            retrieved_at=dataset_retrieved_at,
            observations=tuple(observations),
        )


class ValuationEngine:
    """Measure valuation support for one explicit equity benchmark."""

    engine_name = "valuation"
    scope = "Configured point-in-time U.S. equity benchmark valuation support"
    policy_version = "valuation-policy.v1"

    def __init__(
        self,
        provider: ValuationDataProvider,
        *,
        minimum_history: int = 12,
        stale_after: timedelta = timedelta(days=120),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not hasattr(provider, "fetch"):
            raise TypeError("provider must expose fetch")
        if isinstance(minimum_history, bool) or not isinstance(
            minimum_history, int
        ):
            raise TypeError("minimum_history must be an int")
        if minimum_history < 6:
            raise ValueError("minimum_history must be at least 6")
        if not isinstance(stale_after, timedelta) or stale_after <= timedelta(0):
            raise ValueError("stale_after must be a positive timedelta")
        self.provider = provider
        self.minimum_history = minimum_history
        self.stale_after = stale_after
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self, *, as_of: datetime) -> ValuationRun:
        resolved = _require_aware(as_of, "as_of")
        try:
            dataset = self.provider.fetch(as_of=resolved)
        except (ValuationDataError, OSError, ValueError, TypeError) as error:
            result = self._unavailable(resolved, str(error))
            return ValuationRun(
                as_of=resolved,
                provider=getattr(self.provider, "name", "valuation"),
                dataset=None,
                loads=(),
                result=result,
            )

        loads: list[ValuationMetricLoad] = []
        components: list[_Component] = []
        for metric in ValuationMetric:
            try:
                component = self._component(metric, dataset, as_of=resolved)
            except ValuationDataError as error:
                loads.append(
                    ValuationMetricLoad(
                        metric=metric,
                        state=ValuationLoadState.UNAVAILABLE,
                        error=str(error),
                    )
                )
                continue
            components.append(component)
            loads.append(
                ValuationMetricLoad(
                    metric=metric,
                    state=ValuationLoadState.LOADED,
                    latest=component.latest,
                    history_count=component.history_count,
                    percentile=component.percentile,
                    signal=component.signal,
                )
            )

        if not components:
            return ValuationRun(
                as_of=resolved,
                provider=dataset.provider,
                dataset=dataset,
                loads=tuple(loads),
                result=self._unavailable(
                    resolved,
                    "no valuation component had sufficient point-in-time history",
                ),
            )

        available_weight = sum(
            _METRIC_WEIGHTS[component.metric] for component in components
        )
        composite = (
            sum(
                _METRIC_WEIGHTS[component.metric] * component.signal
                for component in components
            )
            / available_weight
        )
        positive_confirmation = sum(
            component.signal >= 0.25 for component in components
        )
        negative_confirmation = sum(
            component.signal <= -0.50 for component in components
        )
        direction = _direction(
            composite,
            positive_confirmation=positive_confirmation,
            negative_confirmation=negative_confirmation,
        )
        score = max(0, min(100, round(50 + 50 * composite)))
        coverage = sum(
            _METRIC_WEIGHTS[component.metric] for component in components
        )
        quality = (
            sum(
                _METRIC_WEIGHTS[component.metric] * component.quality
                for component in components
            )
            / available_weight
        )
        agreement = max(
            0.0,
            1.0
            - min(
                1.0,
                sum(
                    _METRIC_WEIGHTS[component.metric]
                    * abs(component.signal - composite)
                    for component in components
                )
                / available_weight,
            ),
        )
        confidence = max(
            0,
            min(
                100,
                round(
                    100
                    * (0.50 * coverage + 0.30 * quality + 0.20 * agreement)
                ),
            ),
        )
        stale = any(component.stale for component in components)
        if stale:
            data_status = EngineDataStatus.STALE
        elif coverage < 0.999 or len(components) < len(ValuationMetric):
            data_status = EngineDataStatus.INCOMPLETE
        else:
            data_status = EngineDataStatus.CURRENT

        evidence = tuple(
            EngineEvidence(
                identifier=(
                    f"engine-evidence:{self.engine_name}:{dataset.benchmark}:"
                    f"{component.metric.value}:{component.latest.observation_date.isoformat()}"
                ),
                component=component.metric.value,
                indicator=component.metric.value,
                provider=dataset.provider,
                series_identifier=(
                    f"{dataset.source_identifier}:{dataset.source_fingerprint}:"
                    f"{dataset.methodology_version}:{component.metric.value}"
                ),
                observation_date=component.latest.observation_date,
                released_at=component.latest.available_at,
                retrieved_at=component.latest.retrieved_at,
                vintage_date=component.latest.observation_date,
                quality_state=component.latest.quality_state.value,
                signal_score=component.signal,
                weighted_contribution=_clip(
                    _METRIC_WEIGHTS[component.metric] * component.signal
                ),
                explanation=component.explanation,
            )
            for component in components
        )
        risks = self._risks(
            components=components,
            loads=loads,
            data_status=data_status,
        )
        summary, explanation = _language(
            direction,
            composite=composite,
            benchmark=dataset.benchmark,
            positive_confirmation=positive_confirmation,
            negative_confirmation=negative_confirmation,
        )
        result = AnalyticalEngineResult(
            identifier=(
                f"analytical-engine:{self.engine_name}:{resolved.isoformat()}:"
                f"{dataset.source_fingerprint[:16]}"
            ),
            engine=self.engine_name,
            scope=f"{self.scope}: {dataset.benchmark}",
            policy_version=self.policy_version,
            as_of=resolved,
            generated_at=_require_aware(self._clock(), "clock"),
            direction=direction,
            score=score,
            confidence=confidence,
            coverage=coverage,
            data_status=data_status,
            summary=summary,
            explanation=explanation,
            risks=risks,
            transmission_channels=(
                "Valuation changes the margin of safety and the portfolio's sensitivity to earnings or discount-rate disappointments.",
                "Stretched valuation can increase drawdown severity even when economic and credit conditions remain constructive.",
                "Attractive valuation can improve the long-horizon opportunity set, but it does not identify the timing of a market turn.",
            ),
            review_conditions=self._review_conditions(
                components=components,
                data_status=data_status,
            ),
            evidence=evidence,
        )
        return ValuationRun(
            as_of=resolved,
            provider=dataset.provider,
            dataset=dataset,
            loads=tuple(loads),
            result=result,
        )

    def _component(
        self,
        metric: ValuationMetric,
        dataset: ValuationDataset,
        *,
        as_of: datetime,
    ) -> _Component:
        observations = tuple(
            sorted(
                (
                    observation
                    for observation in dataset.observations
                    if observation.metric is metric
                    and observation.available_at <= as_of
                ),
                key=lambda observation: (
                    observation.available_at,
                    observation.observation_date,
                    observation.retrieved_at,
                ),
            )
        )
        if not observations:
            raise ValuationDataError(f"{metric.value} is unavailable")
        latest = observations[-1]
        if metric in _NONPOSITIVE_INVALID and latest.value <= 0:
            raise ValuationDataError(
                f"{metric.value} latest denominator is non-positive; "
                "the metric is excluded rather than interpreted as cheap"
            )
        prior = tuple(
            observation
            for observation in observations[:-1]
            if observation.value > 0 or metric not in _NONPOSITIVE_INVALID
        )
        if len(prior) < self.minimum_history:
            raise ValuationDataError(
                f"{metric.value} has {len(prior)} prior observations; "
                f"at least {self.minimum_history} are required"
            )
        percentile = _percentile(
            latest.value, tuple(item.value for item in prior)
        )
        signal = _clip(2.0 * (percentile - 0.5))
        stale = (
            latest.quality_state is DataQualityState.STALE
            or latest.available_at + self.stale_after < as_of
        )
        quality = _QUALITY_WEIGHT[latest.quality_state]
        if stale:
            quality = min(quality, _QUALITY_WEIGHT[DataQualityState.STALE])
        label = _METRIC_LABELS[metric]
        explanation = (
            f"{label.title()} is {_format_percent(latest.value)} and sits at the "
            f"{round(percentile * 100)}th percentile of {len(prior)} earlier "
            f"point-in-time observations under {dataset.methodology_version}. "
            "Higher yield indicates more valuation support."
        )
        return _Component(
            metric=metric,
            signal=signal,
            percentile=percentile,
            history_count=len(prior),
            latest=latest,
            quality=quality,
            stale=stale,
            explanation=explanation,
        )

    def _risks(
        self,
        *,
        components: list[_Component],
        loads: list[ValuationMetricLoad],
        data_status: EngineDataStatus,
    ) -> tuple[str, ...]:
        risks: list[str] = [
            "Valuation is a long-horizon condition, not a market-timing signal or price target.",
            "A low valuation can reflect deteriorating fundamentals; interpret it with Business Cycle and Credit Cycle evidence.",
        ]
        unavailable = [
            load.metric.value
            for load in loads
            if load.state is ValuationLoadState.UNAVAILABLE
        ]
        if unavailable:
            risks.append(
                "Unavailable valuation components reduced coverage: "
                + ", ".join(unavailable)
                + "."
            )
        positive = [
            component for component in components if component.signal >= 0.25
        ]
        negative = [
            component for component in components if component.signal <= -0.25
        ]
        if positive and negative:
            risks.append(
                "Valuation evidence is internally mixed; attractive and stretched measures coexist."
            )
        if data_status is EngineDataStatus.STALE:
            risks.append(
                "One or more latest valuation observations are stale and should be refreshed before reliance."
            )
        return tuple(dict.fromkeys(risks))

    def _review_conditions(
        self,
        *,
        components: list[_Component],
        data_status: EngineDataStatus,
    ) -> tuple[str, ...]:
        conditions = [
            "Review valuation support when at least three component percentiles cross from one side of historical median to the other.",
            "Review whether falling yields reflect higher prices, weaker fundamentals, or both before changing portfolio risk.",
            "Do not convert this assessment into a return forecast or price target.",
        ]
        if data_status in {EngineDataStatus.STALE, EngineDataStatus.INCOMPLETE}:
            conditions.append(
                "Refresh missing or stale valuation evidence before increasing conviction."
            )
        if any(
            component.metric is ValuationMetric.EQUITY_RISK_PREMIUM
            and component.signal <= -0.50
            for component in components
        ):
            conditions.append(
                "Reassess sensitivity to discount-rate shocks while the equity risk premium remains historically compressed."
            )
        return tuple(dict.fromkeys(conditions))

    def _unavailable(
        self,
        as_of: datetime,
        reason: str,
    ) -> AnalyticalEngineResult:
        return AnalyticalEngineResult(
            identifier=(
                f"analytical-engine:{self.engine_name}:{as_of.isoformat()}:unavailable"
            ),
            engine=self.engine_name,
            scope=self.scope,
            policy_version=self.policy_version,
            as_of=as_of,
            generated_at=_require_aware(self._clock(), "clock"),
            direction=EngineDirection.UNAVAILABLE,
            score=0,
            confidence=0,
            coverage=0.0,
            data_status=EngineDataStatus.UNAVAILABLE,
            summary="Equity-market valuation intelligence is unavailable.",
            explanation=reason.strip()
            or "No defensible valuation evidence was available.",
            risks=(
                "Do not infer that the market is cheap or expensive from missing valuation evidence.",
            ),
            transmission_channels=(
                "Valuation cannot influence portfolio guidance until a point-in-time benchmark history is available.",
            ),
            review_conditions=(
                "Configure an immutable point-in-time valuation source and rerun the engine.",
            ),
            evidence=(),
        )


def build_configured_valuation_engine(
    *,
    clock: Callable[[], datetime] | None = None,
) -> ValuationEngine:
    """Build the configured file-backed engine or an explicit unavailable one."""

    path = os.environ.get("CAPITAL_INTELLIGENCE_VALUATION_FILE")
    provider: ValuationDataProvider
    if path and path.strip():
        provider = JSONValuationProvider(path.strip())
    else:
        provider = UnavailableValuationProvider()
    return ValuationEngine(provider, clock=clock)


def valuation_source_readiness() -> tuple[bool, str]:
    """Report optional source readiness without blocking the core application."""

    path = os.environ.get("CAPITAL_INTELLIGENCE_VALUATION_FILE")
    if not path or not path.strip():
        return (
            True,
            "valuation source is not configured; the engine will publish unavailable without blocking daily intelligence",
        )
    source = Path(path.strip()).expanduser()
    if not source.exists():
        return False, f"configured valuation source does not exist: {source}"
    try:
        provider = JSONValuationProvider(source)
        provider._load()
    except (OSError, ValueError, ValuationDataError) as error:
        return False, f"configured valuation source is invalid: {error}"
    return True, f"valuation source is configured: {source}"


def _direction(
    composite: float,
    *,
    positive_confirmation: int,
    negative_confirmation: int,
) -> EngineDirection:
    if composite <= -0.60 and negative_confirmation >= 4:
        return EngineDirection.STRESSED
    if composite <= -0.15:
        return EngineDirection.CONTRACTING
    if composite >= 0.25 and positive_confirmation >= 3:
        return EngineDirection.EXPANDING
    return EngineDirection.NEUTRAL


def _language(
    direction: EngineDirection,
    *,
    composite: float,
    benchmark: str,
    positive_confirmation: int,
    negative_confirmation: int,
) -> tuple[str, str]:
    if direction is EngineDirection.EXPANDING:
        return (
            f"Valuation support is broadening for {benchmark}.",
            (
                f"{positive_confirmation} independent measures are above their "
                "historical midpoints, indicating a wider margin of safety than "
                "usual. This improves long-horizon support but is not a timing call."
            ),
        )
    if direction is EngineDirection.STRESSED:
        return (
            f"Valuation is broadly stretched for {benchmark}.",
            (
                f"{negative_confirmation} independent measures are deeply below "
                "their historical midpoints. The market may be more sensitive to "
                "earnings disappointment or higher discount rates."
            ),
        )
    if direction is EngineDirection.CONTRACTING:
        return (
            f"Valuation support is contracting for {benchmark}.",
            (
                "The combined yield-based evidence is below its historical midpoint, "
                "suggesting less margin of safety. The conclusion should be interpreted "
                "with economic, credit, and breadth evidence."
            ),
        )
    return (
        f"Valuation is mixed for {benchmark}.",
        (
            "The measures do not provide broad confirmation of either attractive or "
            f"stretched valuation. The composite signal is {composite:+.2f}, so no "
            "standalone portfolio conclusion is warranted."
        ),
    )


def _percentile(value: float, history: tuple[float, ...]) -> float:
    if not history:
        raise ValueError("history cannot be empty")
    below = sum(item < value for item in history)
    equal = sum(item == value for item in history)
    return (below + 0.5 * equal) / len(history)


def _quality_state(value: object) -> DataQualityState:
    try:
        return DataQualityState(str(value).strip().lower())
    except ValueError as error:
        raise ValuationDataError(
            f"unsupported valuation quality_state: {value}"
        ) from error


def _parse_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValuationDataError(f"{field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ValuationDataError(
            f"{field_name} must be an ISO timestamp"
        ) from error
    return _require_aware(parsed, field_name)


def _parse_date(value: object, field_name: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ValuationDataError(f"{field_name} must be an ISO date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as error:
        raise ValuationDataError(f"{field_name} must be an ISO date") from error


def _require_aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _format_percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _clip(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


__all__ = [
    "JSONValuationProvider",
    "UnavailableValuationProvider",
    "ValuationDataError",
    "ValuationDataProvider",
    "ValuationDataset",
    "ValuationEngine",
    "ValuationLoadState",
    "ValuationMetric",
    "ValuationMetricLoad",
    "ValuationObservation",
    "ValuationRun",
    "build_configured_valuation_engine",
    "valuation_source_readiness",
]
