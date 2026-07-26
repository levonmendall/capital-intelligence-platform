"""Deterministic point-in-time market-risk intelligence engine."""

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


class RiskDataError(RuntimeError):
    """Raised when a configured risk source is unavailable or invalid."""


class RiskMetric(str, Enum):
    """Risk-pressure measures where a higher value means greater fragility."""

    REALIZED_VOLATILITY = "realized_volatility"
    DOWNSIDE_VOLATILITY = "downside_volatility"
    CROSS_ASSET_CORRELATION = "cross_asset_correlation"
    DRAWDOWN_DEPTH = "drawdown_depth"
    MARKET_CONCENTRATION = "market_concentration"
    LIQUIDITY_STRESS = "liquidity_stress"
    TAIL_LOSS_FREQUENCY = "tail_loss_frequency"


class RiskLoadState(str, Enum):
    """Whether one risk component was usable."""

    LOADED = "loaded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class RiskObservation:
    """One point-in-time observation for a named risk-pressure metric."""

    metric: RiskMetric
    value: float
    observation_date: date
    available_at: datetime
    retrieved_at: datetime
    quality_state: DataQualityState
    source_identifier: str
    scope: str
    methodology_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.metric, RiskMetric):
            raise TypeError("metric must be a RiskMetric")
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
            raise ValueError("risk observations cannot use missing quality")
        for field_name in ("source_identifier", "scope", "methodology_version"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())


@dataclass(frozen=True, slots=True)
class RiskDataset:
    """Immutable risk history for one scope and methodology."""

    provider: str
    source_identifier: str
    source_fingerprint: str
    scope: str
    methodology_version: str
    retrieved_at: datetime
    observations: tuple[RiskObservation, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "provider",
            "source_identifier",
            "scope",
            "methodology_version",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            normalized = value.strip().upper() if field_name == "provider" else value.strip()
            object.__setattr__(self, field_name, normalized)
        fingerprint = self.source_fingerprint.strip().lower()
        if (
            len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise ValueError(
                "source_fingerprint must be a 64-character SHA-256 hex digest"
            )
        object.__setattr__(self, "source_fingerprint", fingerprint)
        retrieved_at = _require_aware(self.retrieved_at, "retrieved_at")
        if not isinstance(self.observations, tuple) or not self.observations:
            raise ValueError("observations must be a non-empty tuple")
        if not all(isinstance(item, RiskObservation) for item in self.observations):
            raise TypeError("observations must contain RiskObservation values")
        for item in self.observations:
            if item.scope != self.scope:
                raise ValueError("all observations must use the dataset scope")
            if item.methodology_version != self.methodology_version:
                raise ValueError(
                    "all observations must use the dataset methodology version"
                )
            if item.retrieved_at > retrieved_at:
                raise ValueError(
                    "observation retrieved_at cannot exceed dataset retrieved_at"
                )
        identities = [
            (item.metric, item.observation_date, item.available_at)
            for item in self.observations
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("risk observations cannot contain duplicates")


@runtime_checkable
class RiskDataProvider(Protocol):
    """Provider for one immutable point-in-time risk history."""

    @property
    def name(self) -> str:
        """Stable provider identifier."""

    def fetch(self, *, as_of: datetime) -> RiskDataset:
        """Return risk evidence available at the decision timestamp."""


@dataclass(frozen=True, slots=True)
class RiskMetricLoad:
    """One scored or unavailable risk component."""

    metric: RiskMetric
    state: RiskLoadState
    latest: RiskObservation | None = None
    history_count: int = 0
    percentile: float | None = None
    signal: float | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.metric, RiskMetric):
            raise TypeError("metric must be a RiskMetric")
        if not isinstance(self.state, RiskLoadState):
            raise TypeError("state must be a RiskLoadState")
        if isinstance(self.history_count, bool) or not isinstance(self.history_count, int):
            raise TypeError("history_count must be an int")
        if self.history_count < 0:
            raise ValueError("history_count cannot be negative")
        if self.state is RiskLoadState.LOADED:
            if not isinstance(self.latest, RiskObservation):
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
class RiskRun:
    """Detailed risk execution plus the shared analytical result."""

    as_of: datetime
    provider: str
    dataset: RiskDataset | None
    loads: tuple[RiskMetricLoad, ...]
    result: AnalyticalEngineResult

    @property
    def loaded_count(self) -> int:
        return sum(load.state is RiskLoadState.LOADED for load in self.loads)

    @property
    def unavailable_count(self) -> int:
        return len(self.loads) - self.loaded_count


@dataclass(frozen=True, slots=True)
class _Component:
    metric: RiskMetric
    signal: float
    percentile: float
    history_count: int
    latest: RiskObservation
    quality: float
    stale: bool
    explanation: str


_METRIC_WEIGHTS = {
    RiskMetric.REALIZED_VOLATILITY: 0.18,
    RiskMetric.DOWNSIDE_VOLATILITY: 0.18,
    RiskMetric.CROSS_ASSET_CORRELATION: 0.14,
    RiskMetric.DRAWDOWN_DEPTH: 0.16,
    RiskMetric.MARKET_CONCENTRATION: 0.12,
    RiskMetric.LIQUIDITY_STRESS: 0.13,
    RiskMetric.TAIL_LOSS_FREQUENCY: 0.09,
}

_QUALITY_WEIGHT = {
    DataQualityState.LIVE: 1.00,
    DataQualityState.FIXTURE: 1.00,
    DataQualityState.CACHED: 0.90,
    DataQualityState.FALLBACK: 0.60,
    DataQualityState.STALE: 0.40,
    DataQualityState.MISSING: 0.00,
}

_METRIC_LABELS = {
    RiskMetric.REALIZED_VOLATILITY: "realized volatility",
    RiskMetric.DOWNSIDE_VOLATILITY: "downside volatility",
    RiskMetric.CROSS_ASSET_CORRELATION: "cross-asset correlation",
    RiskMetric.DRAWDOWN_DEPTH: "drawdown depth",
    RiskMetric.MARKET_CONCENTRATION: "market concentration",
    RiskMetric.LIQUIDITY_STRESS: "liquidity stress",
    RiskMetric.TAIL_LOSS_FREQUENCY: "tail-loss frequency",
}

_MARKET_RISK_METRICS = {
    RiskMetric.REALIZED_VOLATILITY,
    RiskMetric.DOWNSIDE_VOLATILITY,
    RiskMetric.DRAWDOWN_DEPTH,
    RiskMetric.TAIL_LOSS_FREQUENCY,
}

_FRAGILITY_METRICS = {
    RiskMetric.CROSS_ASSET_CORRELATION,
    RiskMetric.MARKET_CONCENTRATION,
    RiskMetric.LIQUIDITY_STRESS,
}


class UnavailableRiskProvider:
    """Explicit unavailable provider until a licensed source is configured."""

    name = "UNCONFIGURED_RISK"

    def fetch(self, *, as_of: datetime) -> RiskDataset:
        _require_aware(as_of, "as_of")
        raise RiskDataError(
            "risk source is not configured; set CAPITAL_INTELLIGENCE_RISK_FILE "
            "to an immutable provider export"
        )


class JSONRiskProvider:
    """Read one immutable market-risk history export."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self._payload: dict[str, Any] | None = None
        self._fingerprint: str | None = None

    @property
    def name(self) -> str:
        payload = self._load()
        return str(payload.get("provider", "FILE_RISK")).strip().upper()

    def _load(self) -> dict[str, Any]:
        if self._payload is None:
            try:
                raw = self.path.read_bytes()
            except OSError as error:
                raise RiskDataError(
                    f"risk file is unavailable: {self.path}: {error}"
                ) from error
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RiskDataError(
                    f"risk file is not valid UTF-8 JSON: {self.path}"
                ) from error
            if not isinstance(payload, dict):
                raise RiskDataError("risk document must be a JSON object")
            if payload.get("schema_version") != "risk-input.v1":
                raise RiskDataError("risk document must use risk-input.v1")
            self._payload = payload
            self._fingerprint = hashlib.sha256(raw).hexdigest()
        return self._payload

    def fetch(self, *, as_of: datetime) -> RiskDataset:
        resolved = _require_aware(as_of, "as_of")
        payload = self._load()
        scope = str(payload.get("scope", "")).strip()
        methodology_version = str(payload.get("methodology_version", "")).strip()
        if not scope or not methodology_version:
            raise RiskDataError(
                "risk document requires scope and methodology_version"
            )
        items = payload.get("observations")
        if not isinstance(items, list):
            raise RiskDataError("risk document is missing observations")
        observations: list[RiskObservation] = []
        for item in items:
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
                RiskObservation(
                    metric=RiskMetric(str(item.get("metric", ""))),
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
                    scope=scope,
                    methodology_version=methodology_version,
                )
            )
        if not observations:
            raise RiskDataError(
                "risk document has no observations available at the decision time"
            )
        dataset_retrieved = _parse_datetime(
            payload.get(
                "retrieved_at",
                max(item.retrieved_at for item in observations).isoformat(),
            ),
            "retrieved_at",
        )
        return RiskDataset(
            provider=self.name,
            source_identifier=str(
                payload.get("source_identifier", self.path.name)
            ),
            source_fingerprint=str(self._fingerprint),
            scope=scope,
            methodology_version=methodology_version,
            retrieved_at=dataset_retrieved,
            observations=tuple(observations),
        )


class RiskEngine:
    """Measure broad market-risk pressure without forecasting a loss amount."""

    engine_name = "risk"
    scope = "Configured point-in-time market-risk and fragility conditions"
    policy_version = "risk-policy.v1"

    def __init__(
        self,
        provider: RiskDataProvider,
        *,
        minimum_history: int = 12,
        minimum_components: int = 3,
        stale_after: timedelta = timedelta(days=45),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(provider, RiskDataProvider):
            raise TypeError("provider must implement RiskDataProvider")
        if isinstance(minimum_history, bool) or not isinstance(minimum_history, int):
            raise TypeError("minimum_history must be an int")
        if minimum_history < 5:
            raise ValueError("minimum_history must be at least 5")
        if isinstance(minimum_components, bool) or not isinstance(
            minimum_components, int
        ):
            raise TypeError("minimum_components must be an int")
        if not 2 <= minimum_components <= len(RiskMetric):
            raise ValueError("minimum_components is outside the supported range")
        if not isinstance(stale_after, timedelta) or stale_after <= timedelta(0):
            raise ValueError("stale_after must be a positive timedelta")
        self.provider = provider
        self.minimum_history = minimum_history
        self.minimum_components = minimum_components
        self.stale_after = stale_after
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self, *, as_of: datetime) -> RiskRun:
        resolved = _require_aware(as_of, "as_of")
        try:
            dataset = self.provider.fetch(as_of=resolved)
        except (RiskDataError, OSError, ValueError, TypeError) as error:
            result = self._unavailable(resolved, str(error))
            return RiskRun(
                as_of=resolved,
                provider=getattr(self.provider, "name", "risk"),
                dataset=None,
                loads=(),
                result=result,
            )

        loads: list[RiskMetricLoad] = []
        components: list[_Component] = []
        for metric in RiskMetric:
            eligible = tuple(
                sorted(
                    (
                        item
                        for item in dataset.observations
                        if item.metric is metric and item.available_at <= resolved
                    ),
                    key=lambda item: (
                        item.observation_date,
                        item.available_at,
                        item.retrieved_at,
                    ),
                )
            )
            if not eligible:
                loads.append(
                    RiskMetricLoad(
                        metric=metric,
                        state=RiskLoadState.UNAVAILABLE,
                        error="no point-in-time observation was available",
                    )
                )
                continue
            latest = eligible[-1]
            history = tuple(
                item
                for item in eligible[:-1]
                if item.observation_date < latest.observation_date
            )
            if len(history) < self.minimum_history:
                loads.append(
                    RiskMetricLoad(
                        metric=metric,
                        state=RiskLoadState.UNAVAILABLE,
                        history_count=len(history),
                        error=(
                            f"only {len(history)} prior observations were available; "
                            f"{self.minimum_history} are required"
                        ),
                    )
                )
                continue
            percentile = _percentile(latest.value, tuple(item.value for item in history))
            signal = _clip(1.0 - 2.0 * percentile)
            stale = (
                resolved
                - datetime.combine(
                    latest.observation_date,
                    datetime.min.time(),
                    tzinfo=timezone.utc,
                )
                > self.stale_after
                or latest.quality_state is DataQualityState.STALE
            )
            explanation = (
                f"{_METRIC_LABELS[metric].capitalize()} is at the "
                f"{round(percentile * 100)}th percentile of its prior "
                f"point-in-time history; higher percentiles mean greater risk pressure."
            )
            component = _Component(
                metric=metric,
                signal=signal,
                percentile=percentile,
                history_count=len(history),
                latest=latest,
                quality=_QUALITY_WEIGHT[latest.quality_state],
                stale=stale,
                explanation=explanation,
            )
            components.append(component)
            loads.append(
                RiskMetricLoad(
                    metric=metric,
                    state=RiskLoadState.LOADED,
                    latest=latest,
                    history_count=len(history),
                    percentile=percentile,
                    signal=signal,
                )
            )

        if len(components) < self.minimum_components:
            reason = (
                f"only {len(components)} risk components had sufficient "
                "point-in-time history"
            )
            return RiskRun(
                as_of=resolved,
                provider=dataset.provider,
                dataset=dataset,
                loads=tuple(loads),
                result=self._unavailable(resolved, reason),
            )

        available_weight = sum(_METRIC_WEIGHTS[item.metric] for item in components)
        composite = (
            sum(
                _METRIC_WEIGHTS[item.metric] * item.signal for item in components
            )
            / available_weight
        )
        coverage = sum(_METRIC_WEIGHTS[item.metric] for item in components)
        quality = (
            sum(
                _METRIC_WEIGHTS[item.metric] * item.quality for item in components
            )
            / available_weight
        )
        disagreement = (
            sum(
                _METRIC_WEIGHTS[item.metric] * abs(item.signal - composite)
                for item in components
            )
            / available_weight
        )
        agreement = max(0.0, 1.0 - min(1.0, disagreement / 1.25))
        confidence = max(
            0,
            min(100, round(100 * coverage * (0.65 * quality + 0.35 * agreement))),
        )
        score = max(0, min(100, round(50 + 50 * composite)))
        direction = self._direction(composite, components)
        data_status = self._data_status(components, coverage)
        evidence = tuple(
            EngineEvidence(
                identifier=(
                    f"engine-evidence:{self.engine_name}:{dataset.scope}:"
                    f"{item.metric.value}:{item.latest.observation_date.isoformat()}"
                ),
                component=item.metric.value,
                indicator=item.metric.value,
                provider=dataset.provider,
                series_identifier=(
                    f"{dataset.source_identifier}:{dataset.source_fingerprint}:"
                    f"{item.metric.value}"
                ),
                observation_date=item.latest.observation_date,
                released_at=item.latest.available_at,
                retrieved_at=max(item.latest.retrieved_at, item.latest.available_at),
                vintage_date=item.latest.observation_date,
                quality_state=item.latest.quality_state.value,
                signal_score=item.signal,
                weighted_contribution=_clip(
                    _METRIC_WEIGHTS[item.metric] * item.signal
                ),
                explanation=item.explanation,
            )
            for item in components
        )
        result = AnalyticalEngineResult(
            identifier=(
                f"engine-result:{self.engine_name}:{resolved.isoformat()}:"
                f"{self.policy_version}"
            ),
            engine=self.engine_name,
            scope=f"{self.scope}: {dataset.scope}",
            policy_version=self.policy_version,
            as_of=resolved,
            generated_at=_require_aware(self._clock(), "generated_at"),
            direction=direction,
            score=score,
            confidence=confidence,
            coverage=round(coverage, 6),
            data_status=data_status,
            summary=self._summary(direction, score),
            explanation=self._explanation(direction, components),
            risks=self._risks(components, loads, data_status),
            transmission_channels=self._transmission_channels(components),
            review_conditions=self._review_conditions(direction, data_status),
            evidence=evidence,
        )
        return RiskRun(
            as_of=resolved,
            provider=dataset.provider,
            dataset=dataset,
            loads=tuple(loads),
            result=result,
        )

    def _direction(
        self,
        composite: float,
        components: list[_Component],
    ) -> EngineDirection:
        positive = sum(item.signal >= 0.25 for item in components)
        severe = sum(item.signal <= -0.50 for item in components)
        market_stress = sum(
            item.signal <= -0.45
            for item in components
            if item.metric in _MARKET_RISK_METRICS
        )
        fragility_stress = sum(
            item.signal <= -0.45
            for item in components
            if item.metric in _FRAGILITY_METRICS
        )
        if (
            composite <= -0.48
            and severe >= 4
            and market_stress >= 2
            and fragility_stress >= 2
        ):
            return EngineDirection.STRESSED
        if composite <= -0.18:
            return EngineDirection.CONTRACTING
        if composite >= 0.22 and positive >= 3 and severe == 0:
            return EngineDirection.EXPANDING
        return EngineDirection.NEUTRAL

    def _data_status(
        self,
        components: list[_Component],
        coverage: float,
    ) -> EngineDataStatus:
        if all(item.stale for item in components):
            return EngineDataStatus.STALE
        if coverage < 0.999999 or any(item.stale for item in components):
            return EngineDataStatus.INCOMPLETE
        return EngineDataStatus.CURRENT

    @staticmethod
    def _summary(direction: EngineDirection, score: int) -> str:
        if direction is EngineDirection.EXPANDING:
            return f"Risk pressure is easing broadly (support score {score})."
        if direction is EngineDirection.STRESSED:
            return f"Risk pressure is broadly stressed (support score {score})."
        if direction is EngineDirection.CONTRACTING:
            return f"Risk pressure is rising (support score {score})."
        return f"Risk conditions are mixed or transitional (support score {score})."

    @staticmethod
    def _explanation(
        direction: EngineDirection,
        components: list[_Component],
    ) -> str:
        ordered = sorted(components, key=lambda item: item.signal)
        weakest = ", ".join(_METRIC_LABELS[item.metric] for item in ordered[:2])
        strongest = ", ".join(
            _METRIC_LABELS[item.metric] for item in reversed(ordered[-2:])
        )
        if direction is EngineDirection.STRESSED:
            return (
                "Stress is confirmed across both realized market behavior and "
                f"structural fragility. The weakest evidence is {weakest}."
            )
        if direction is EngineDirection.CONTRACTING:
            return (
                f"Risk pressure is increasing, led by {weakest}, but the evidence "
                "does not yet meet the cross-channel stress threshold."
            )
        if direction is EngineDirection.EXPANDING:
            return (
                f"Risk pressure is easing across several independent measures, "
                f"with the strongest support from {strongest}."
            )
        return (
            f"Risk evidence is mixed: the weakest signals are {weakest}, while "
            f"the strongest support comes from {strongest}."
        )

    @staticmethod
    def _risks(
        components: list[_Component],
        loads: list[RiskMetricLoad],
        data_status: EngineDataStatus,
    ) -> tuple[str, ...]:
        risks: list[str] = []
        missing = [
            _METRIC_LABELS[item.metric]
            for item in loads
            if item.state is RiskLoadState.UNAVAILABLE
        ]
        if missing:
            risks.append(
                "Risk coverage is incomplete because these components were "
                f"unavailable: {', '.join(missing)}."
            )
        if any(item.stale for item in components):
            risks.append("One or more risk observations are stale.")
        if any(
            item.signal <= -0.50
            for item in components
            if item.metric is RiskMetric.CROSS_ASSET_CORRELATION
        ):
            risks.append(
                "Rising cross-asset correlation may reduce diversification when it is most needed."
            )
        if any(
            item.signal <= -0.50
            for item in components
            if item.metric is RiskMetric.MARKET_CONCENTRATION
        ):
            risks.append(
                "High market concentration increases dependence on a smaller set of return drivers."
            )
        if any(
            item.signal <= -0.50
            for item in components
            if item.metric is RiskMetric.LIQUIDITY_STRESS
        ):
            risks.append(
                "Liquidity stress can widen spreads and make portfolio changes more costly."
            )
        positive = any(item.signal >= 0.35 for item in components)
        negative = any(item.signal <= -0.35 for item in components)
        if positive and negative:
            risks.append(
                "Risk components disagree, so the aggregate conclusion should not be treated as uniform."
            )
        if data_status is EngineDataStatus.INCOMPLETE:
            risks.append(
                "Incomplete evidence lowers confidence and should not be replaced with assumptions."
            )
        risks.append(
            "This assessment describes risk pressure; it is not a forecast of a loss amount or probability."
        )
        return tuple(dict.fromkeys(risks))

    @staticmethod
    def _transmission_channels(
        components: list[_Component],
    ) -> tuple[str, ...]:
        channels = [
            "Higher volatility and deeper drawdowns can increase portfolio value swings and behavioral pressure.",
            "Rising correlations and concentration can make apparent diversification less effective during stress.",
            "Liquidity pressure can widen transaction costs and reduce the ability to rebalance efficiently.",
        ]
        if not any(
            item.metric is RiskMetric.LIQUIDITY_STRESS for item in components
        ):
            channels.pop()
        return tuple(channels)

    @staticmethod
    def _review_conditions(
        direction: EngineDirection,
        data_status: EngineDataStatus,
    ) -> tuple[str, ...]:
        conditions = [
            "Review the assessment if risk pressure crosses into a confirmed stressed state.",
            "Review whether correlation, concentration, and liquidity stress are deteriorating together.",
            "Compare risk pressure with the investor's recorded drawdown tolerance and liquidity needs.",
        ]
        if direction is EngineDirection.STRESSED:
            conditions.append(
                "Reassess portfolio resilience if confirmed risk stress persists across consecutive observations."
            )
        if data_status is not EngineDataStatus.CURRENT:
            conditions.append(
                "Refresh incomplete or stale risk evidence before relying on its direction."
            )
        return tuple(conditions)

    def _unavailable(self, as_of: datetime, reason: str) -> AnalyticalEngineResult:
        return AnalyticalEngineResult(
            identifier=(
                f"engine-result:{self.engine_name}:{as_of.isoformat()}:"
                f"{self.policy_version}"
            ),
            engine=self.engine_name,
            scope=self.scope,
            policy_version=self.policy_version,
            as_of=as_of,
            generated_at=_require_aware(self._clock(), "generated_at"),
            direction=EngineDirection.UNAVAILABLE,
            score=0,
            confidence=0,
            coverage=0.0,
            data_status=EngineDataStatus.UNAVAILABLE,
            summary="Risk intelligence is unavailable.",
            explanation=reason.strip() or "No risk evidence was available.",
            risks=(
                "Unavailable risk evidence must not be replaced with synthetic values.",
            ),
            transmission_channels=(),
            review_conditions=(
                "Configure or restore the point-in-time risk source before relying on this engine.",
            ),
            evidence=(),
        )


def build_configured_risk_engine(
    *,
    clock: Callable[[], datetime] | None = None,
) -> RiskEngine:
    """Build the configured engine or an explicit unavailable provider."""

    source = os.environ.get("CAPITAL_INTELLIGENCE_RISK_FILE")
    provider: RiskDataProvider
    if source and source.strip():
        provider = JSONRiskProvider(source)
    else:
        provider = UnavailableRiskProvider()
    return RiskEngine(provider, clock=clock)


def risk_source_readiness() -> tuple[bool, str]:
    """Report optional source readiness without blocking the core platform."""

    source = os.environ.get("CAPITAL_INTELLIGENCE_RISK_FILE")
    if not source or not source.strip():
        return (
            True,
            "risk source is not configured; the engine will publish unavailable "
            "without blocking the core daily intelligence path",
        )
    path = Path(source).expanduser()
    ready = path.is_file() and os.access(path, os.R_OK)
    detail = (
        f"risk source is readable: {path}"
        if ready
        else f"configured risk source is unavailable: {path}"
    )
    return ready, detail


def _percentile(value: float, history: tuple[float, ...]) -> float:
    if not history:
        raise ValueError("history cannot be empty")
    below = sum(item < value for item in history)
    equal = sum(item == value for item in history)
    return max(0.0, min(1.0, (below + 0.5 * equal) / len(history)))


def _quality_state(value: object) -> DataQualityState:
    try:
        return DataQualityState(str(value).lower())
    except ValueError as error:
        raise RiskDataError(f"unsupported quality_state: {value}") from error


def _parse_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RiskDataError(f"{field_name} must be an ISO-8601 datetime string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RiskDataError(f"{field_name} is not a valid datetime") from error
    return _require_aware(parsed, field_name)


def _parse_date(value: object, field_name: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise RiskDataError(f"{field_name} must be an ISO-8601 date string")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise RiskDataError(f"{field_name} is not a valid date") from error


def _require_aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _clip(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


__all__ = [
    "JSONRiskProvider",
    "RiskDataError",
    "RiskDataset",
    "RiskEngine",
    "RiskLoadState",
    "RiskMetric",
    "RiskMetricLoad",
    "RiskObservation",
    "RiskRun",
    "UnavailableRiskProvider",
    "build_configured_risk_engine",
    "risk_source_readiness",
]
