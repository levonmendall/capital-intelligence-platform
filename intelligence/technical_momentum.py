"""Deterministic point-in-time technical and momentum intelligence engine."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from math import isfinite, sqrt
from pathlib import Path
from statistics import pstdev
from typing import Any, Callable, Protocol, runtime_checkable

from data import BarInterval, DataQualityState, MarketDataError, MarketDataProvenance, PriceBar
from intelligence.analytical_engine import (
    AnalyticalEngineResult,
    EngineDataStatus,
    EngineDirection,
    EngineEvidence,
)


class TechnicalMomentumDataError(RuntimeError):
    """Raised when technical and momentum evidence is unavailable or invalid."""


class TechnicalMomentumComponent(str, Enum):
    ONE_MONTH_MOMENTUM = "one_month_momentum"
    THREE_MONTH_MOMENTUM = "three_month_momentum"
    SIX_MONTH_MOMENTUM = "six_month_momentum"
    TWELVE_MONTH_MOMENTUM = "twelve_month_momentum"
    TREND_ALIGNMENT = "trend_alignment"
    VOLATILITY_PRESSURE = "volatility_pressure"
    DRAWDOWN_STATE = "drawdown_state"


class TechnicalMomentumLoadState(str, Enum):
    LOADED = "loaded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class TechnicalMomentumDataset:
    provider: str
    source_identifier: str
    source_fingerprint: str
    benchmark: str
    instrument_id: str
    venue: str
    currency: str
    methodology_version: str
    retrieved_at: datetime
    bars: tuple[PriceBar, ...]

    def __post_init__(self) -> None:
        for field in (
            "provider", "source_identifier", "benchmark", "instrument_id",
            "venue", "currency", "methodology_version",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a non-empty string")
            object.__setattr__(
                self,
                field,
                value.strip().upper() if field in {"provider", "venue", "currency"} else value.strip(),
            )
        fingerprint = self.source_fingerprint.strip().lower()
        if len(fingerprint) != 64 or any(ch not in "0123456789abcdef" for ch in fingerprint):
            raise ValueError("source_fingerprint must be a SHA-256 hex digest")
        object.__setattr__(self, "source_fingerprint", fingerprint)
        retrieved = _aware(self.retrieved_at, "retrieved_at")
        if not isinstance(self.bars, tuple) or not self.bars:
            raise ValueError("bars must be a non-empty tuple")
        if not all(isinstance(bar, PriceBar) for bar in self.bars):
            raise TypeError("bars must contain PriceBar values")
        seen: set[tuple[datetime, datetime, str | None]] = set()
        for bar in self.bars:
            if bar.instrument_id != self.instrument_id:
                raise ValueError("all bars must use the dataset instrument_id")
            if bar.currency.upper() != self.currency or bar.provenance.venue.upper() != self.venue:
                raise ValueError("bar currency and venue must match the dataset")
            if bar.interval is not BarInterval.DAY:
                raise ValueError("technical and momentum bars must be daily")
            if bar.provenance.retrieved_at > retrieved:
                raise ValueError("bar retrieved_at cannot exceed dataset retrieved_at")
            identity = (bar.end_at, bar.provenance.retrieved_at, bar.provenance.provider_record_id)
            if identity in seen:
                raise ValueError("technical and momentum bars cannot contain duplicates")
            seen.add(identity)


@runtime_checkable
class TechnicalMomentumDataProvider(Protocol):
    @property
    def name(self) -> str: ...
    def fetch(self, *, as_of: datetime) -> TechnicalMomentumDataset: ...


@dataclass(frozen=True, slots=True)
class TechnicalMomentumComponentLoad:
    component: TechnicalMomentumComponent
    state: TechnicalMomentumLoadState
    value: float | None = None
    signal: float | None = None
    observed_at: datetime | None = None
    retrieved_at: datetime | None = None
    quality_state: DataQualityState | None = None
    explanation: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.component, TechnicalMomentumComponent):
            raise TypeError("component must be a TechnicalMomentumComponent")
        if not isinstance(self.state, TechnicalMomentumLoadState):
            raise TypeError("state must be a TechnicalMomentumLoadState")
        if self.state is TechnicalMomentumLoadState.LOADED:
            if self.value is None or self.signal is None:
                raise ValueError("loaded components require value and signal")
            if not isfinite(float(self.value)) or not -1.0 <= float(self.signal) <= 1.0:
                raise ValueError("loaded component values are invalid")
            _aware(self.observed_at, "observed_at")
            _aware(self.retrieved_at, "retrieved_at")
            if self.observed_at > self.retrieved_at:
                raise ValueError("observed_at cannot be later than retrieved_at")
            if not isinstance(self.quality_state, DataQualityState):
                raise ValueError("loaded components require quality_state")
            if not isinstance(self.explanation, str) or not self.explanation.strip():
                raise ValueError("loaded components require an explanation")
            if self.error is not None:
                raise ValueError("loaded components cannot contain an error")
        elif not isinstance(self.error, str) or not self.error.strip():
            raise ValueError("unavailable components require an error")


@dataclass(frozen=True, slots=True)
class TechnicalMomentumRun:
    as_of: datetime
    provider: str
    dataset: TechnicalMomentumDataset | None
    loads: tuple[TechnicalMomentumComponentLoad, ...]
    result: AnalyticalEngineResult

    @property
    def loaded_count(self) -> int:
        return sum(load.state is TechnicalMomentumLoadState.LOADED for load in self.loads)

    @property
    def unavailable_count(self) -> int:
        return len(self.loads) - self.loaded_count


_WEIGHTS = {
    TechnicalMomentumComponent.ONE_MONTH_MOMENTUM: 0.12,
    TechnicalMomentumComponent.THREE_MONTH_MOMENTUM: 0.16,
    TechnicalMomentumComponent.SIX_MONTH_MOMENTUM: 0.16,
    TechnicalMomentumComponent.TWELVE_MONTH_MOMENTUM: 0.16,
    TechnicalMomentumComponent.TREND_ALIGNMENT: 0.16,
    TechnicalMomentumComponent.VOLATILITY_PRESSURE: 0.12,
    TechnicalMomentumComponent.DRAWDOWN_STATE: 0.12,
}
_QUALITY = {
    DataQualityState.LIVE: 1.00,
    DataQualityState.FIXTURE: 1.00,
    DataQualityState.CACHED: 0.90,
    DataQualityState.FALLBACK: 0.60,
    DataQualityState.STALE: 0.40,
    DataQualityState.MISSING: 0.00,
}
_LABELS = {
    TechnicalMomentumComponent.ONE_MONTH_MOMENTUM: "one-month momentum",
    TechnicalMomentumComponent.THREE_MONTH_MOMENTUM: "three-month momentum",
    TechnicalMomentumComponent.SIX_MONTH_MOMENTUM: "six-month momentum",
    TechnicalMomentumComponent.TWELVE_MONTH_MOMENTUM: "twelve-month momentum",
    TechnicalMomentumComponent.TREND_ALIGNMENT: "trend alignment",
    TechnicalMomentumComponent.VOLATILITY_PRESSURE: "volatility pressure",
    TechnicalMomentumComponent.DRAWDOWN_STATE: "drawdown state",
}


class UnavailableTechnicalMomentumProvider:
    name = "UNCONFIGURED_TECHNICAL_MOMENTUM"

    def fetch(self, *, as_of: datetime) -> TechnicalMomentumDataset:
        _aware(as_of, "as_of")
        raise TechnicalMomentumDataError(
            "technical and momentum source is not configured; set "
            "CAPITAL_INTELLIGENCE_TECHNICAL_MOMENTUM_FILE to an immutable provider export"
        )


class JSONTechnicalMomentumProvider:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self._payload: dict[str, Any] | None = None
        self._fingerprint: str | None = None

    @property
    def name(self) -> str:
        return str(self._load().get("provider", "FILE_TECHNICAL_MOMENTUM")).strip().upper()

    def _load(self) -> dict[str, Any]:
        if self._payload is not None:
            return self._payload
        try:
            raw = self.path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except OSError as error:
            raise TechnicalMomentumDataError(
                f"technical and momentum file is unavailable: {self.path}: {error}"
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TechnicalMomentumDataError(
                f"technical and momentum file is not valid UTF-8 JSON: {self.path}"
            ) from error
        if not isinstance(payload, dict) or payload.get("schema_version") != "technical-momentum-input.v1":
            raise TechnicalMomentumDataError(
                "technical and momentum document must use technical-momentum-input.v1"
            )
        self._payload = payload
        self._fingerprint = hashlib.sha256(raw).hexdigest()
        return payload

    def fetch(self, *, as_of: datetime) -> TechnicalMomentumDataset:
        resolved = _aware(as_of, "as_of")
        payload = self._load()
        required = ("benchmark", "instrument_id", "venue", "currency", "methodology_version")
        missing = [name for name in required if not str(payload.get(name, "")).strip()]
        if missing:
            raise TechnicalMomentumDataError(
                "technical and momentum document is missing: " + ", ".join(sorted(missing))
            )
        raw_bars = payload.get("bars")
        if not isinstance(raw_bars, list):
            raise TechnicalMomentumDataError("technical and momentum document is missing bars")
        instrument = str(payload["instrument_id"]).strip()
        venue = str(payload["venue"]).strip().upper()
        currency = str(payload["currency"]).strip().upper()
        bars: list[PriceBar] = []
        for item in raw_bars:
            if not isinstance(item, dict):
                continue
            end = _dt(item.get("end_at"), "bar.end_at")
            observed = _dt(item.get("observed_at", item.get("end_at")), "bar.observed_at")
            if end > resolved or observed > resolved:
                continue
            bars.append(
                PriceBar(
                    instrument_id=instrument,
                    currency=currency,
                    interval=BarInterval.DAY,
                    start_at=_dt(item.get("start_at"), "bar.start_at"),
                    end_at=end,
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item.get("volume", 0)),
                    provenance=MarketDataProvenance(
                        provider=self.name,
                        venue=venue,
                        observed_at=observed,
                        retrieved_at=_dt(
                            item.get("retrieved_at", item.get("observed_at", item.get("end_at"))),
                            "bar.retrieved_at",
                        ),
                        quality_state=_quality(item.get("quality_state", "cached")),
                        provider_record_id=(
                            None if item.get("provider_record_id") is None
                            else str(item["provider_record_id"])
                        ),
                    ),
                )
            )
        ordered = _dedupe(tuple(bars), resolved)
        if not ordered:
            raise TechnicalMomentumDataError(
                "technical and momentum document has no bars available at as_of"
            )
        retrieved = _dt(
            payload.get("retrieved_at", max(bar.provenance.retrieved_at for bar in ordered).isoformat()),
            "retrieved_at",
        )
        return TechnicalMomentumDataset(
            provider=self.name,
            source_identifier=str(payload.get("source_identifier", self.path.name)),
            source_fingerprint=str(self._fingerprint),
            benchmark=str(payload["benchmark"]),
            instrument_id=instrument,
            venue=venue,
            currency=currency,
            methodology_version=str(payload["methodology_version"]),
            retrieved_at=max(retrieved, max(bar.provenance.retrieved_at for bar in ordered)),
            bars=ordered,
        )


class TechnicalMomentumEngine:
    engine_name = "technical_momentum"
    scope = "Configured point-in-time benchmark technical and momentum conditions"
    policy_version = "technical-momentum-policy.v1"

    def __init__(
        self,
        provider: TechnicalMomentumDataProvider,
        *,
        stale_after: timedelta = timedelta(days=5),
        minimum_history: int = 21,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not hasattr(provider, "fetch"):
            raise TypeError("provider must expose fetch")
        if not isinstance(stale_after, timedelta) or stale_after <= timedelta(0):
            raise ValueError("stale_after must be a positive timedelta")
        if isinstance(minimum_history, bool) or not isinstance(minimum_history, int):
            raise TypeError("minimum_history must be an int")
        if minimum_history < 21:
            raise ValueError("minimum_history must be at least 21")
        self.provider = provider
        self.stale_after = stale_after
        self.minimum_history = minimum_history
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self, *, as_of: datetime) -> TechnicalMomentumRun:
        resolved = _aware(as_of, "as_of")
        try:
            dataset = self.provider.fetch(as_of=resolved)
        except (MarketDataError, TechnicalMomentumDataError, OSError, ValueError) as error:
            return TechnicalMomentumRun(
                resolved,
                getattr(self.provider, "name", "technical_momentum"),
                None,
                (),
                self._unavailable(resolved, str(error)),
            )
        bars = _dedupe(dataset.bars, resolved)
        if len(bars) < self.minimum_history:
            reason = (
                f"only {len(bars)} point-in-time daily bars are available; "
                f"at least {self.minimum_history} are required"
            )
            return TechnicalMomentumRun(
                resolved, dataset.provider, dataset, (), self._unavailable(resolved, reason)
            )
        loads = (
            self._momentum(TechnicalMomentumComponent.ONE_MONTH_MOMENTUM, bars, 20, 0.08),
            self._momentum(TechnicalMomentumComponent.THREE_MONTH_MOMENTUM, bars, 63, 0.15),
            self._momentum(TechnicalMomentumComponent.SIX_MONTH_MOMENTUM, bars, 126, 0.25),
            self._momentum(TechnicalMomentumComponent.TWELVE_MONTH_MOMENTUM, bars, 252, 0.40),
            self._trend(bars),
            self._volatility(bars),
            self._drawdown(bars),
        )
        loaded = tuple(load for load in loads if load.state is TechnicalMomentumLoadState.LOADED)
        if not loaded:
            return TechnicalMomentumRun(
                resolved,
                dataset.provider,
                dataset,
                loads,
                self._unavailable(resolved, "no technical component had sufficient history"),
            )
        weight = sum(_WEIGHTS[load.component] for load in loaded)
        composite = sum(_WEIGHTS[load.component] * float(load.signal) for load in loaded) / weight
        coverage = min(1.0, weight)
        quality = sum(
            _WEIGHTS[load.component] * _QUALITY[load.quality_state] for load in loaded
        ) / weight
        disagreement = sum(
            _WEIGHTS[load.component] * abs(float(load.signal) - composite)
            for load in loaded
        ) / weight
        agreement = max(0.0, 1.0 - min(1.0, disagreement))
        score = max(0, min(100, round(50 + 50 * composite)))
        confidence = max(
            0,
            min(100, round(100 * coverage * quality * (0.55 + 0.45 * agreement))),
        )
        by_component = {load.component: load for load in loaded}
        direction = self._direction(composite, by_component)
        status = self._status(resolved, bars, coverage, loaded)
        evidence = tuple(
            EngineEvidence(
                identifier=(
                    f"engine-evidence:{self.engine_name}:{dataset.benchmark}:"
                    f"{load.component.value}:{load.observed_at.date().isoformat()}"
                ),
                component=load.component.value,
                indicator=load.component.value,
                provider=dataset.provider,
                series_identifier=(
                    f"{dataset.source_identifier}:{dataset.source_fingerprint}:"
                    f"{dataset.instrument_id}:{dataset.methodology_version}:{load.component.value}"
                ),
                observation_date=load.observed_at.date(),
                released_at=load.observed_at,
                retrieved_at=max(load.retrieved_at, load.observed_at),
                vintage_date=load.observed_at.date(),
                quality_state=load.quality_state.value,
                signal_score=float(load.signal),
                weighted_contribution=_clip(_WEIGHTS[load.component] * float(load.signal)),
                explanation=load.explanation,
            )
            for load in loaded
        )
        result = AnalyticalEngineResult(
            identifier=(
                f"analytical-engine:{self.engine_name}:{resolved.isoformat()}:"
                f"{dataset.source_fingerprint[:16]}"
            ),
            engine=self.engine_name,
            scope=self.scope,
            policy_version=self.policy_version,
            as_of=resolved,
            generated_at=_aware(self._clock(), "clock"),
            direction=direction,
            score=score,
            confidence=confidence,
            coverage=coverage,
            data_status=status,
            summary=self._summary(direction, dataset.benchmark),
            explanation=(
                f"{dataset.benchmark} technical support scored {score}/100 using "
                f"{len(loaded)} of {len(_WEIGHTS)} versioned components. "
                "The assessment measures observed price persistence and downside "
                "pressure; it is not a forecast or trading signal."
            ),
            risks=self._risks(direction, coverage, status, by_component, loads),
            transmission_channels=(
                "Persistent trends can support risk assets, while weakening momentum "
                "and deeper drawdowns can amplify portfolio volatility and behavioral pressure.",
                "High realized volatility can make otherwise positive momentum less "
                "dependable and can increase the cost of changing exposure.",
                "Technical conditions describe the market path, not intrinsic value, "
                "expected return, or the suitability of a transaction.",
            ),
            review_conditions=(
                "Review when medium- and long-horizon momentum reverse together.",
                "Review when the benchmark crosses its 200-session trend while "
                "drawdown pressure is increasing.",
                "Refresh when the configured history, methodology, or source fingerprint changes.",
            ),
            evidence=evidence,
        )
        return TechnicalMomentumRun(resolved, dataset.provider, dataset, loads, result)

    def _momentum(
        self,
        component: TechnicalMomentumComponent,
        bars: tuple[PriceBar, ...],
        sessions: int,
        scale: float,
    ) -> TechnicalMomentumComponentLoad:
        if len(bars) <= sessions:
            return self._missing(component, f"{sessions + 1} daily bars are required")
        latest, previous = bars[-1], bars[-1 - sessions]
        if previous.close <= 0:
            return self._missing(component, "comparison price is non-positive")
        value = latest.close / previous.close - 1.0
        return self._loaded(
            component,
            value,
            _clip(value / scale),
            latest,
            f"{_LABELS[component]} was {value:.1%} over {sessions} sessions; "
            f"the versioned scale is {scale:.0%}.",
        )

    def _trend(self, bars: tuple[PriceBar, ...]) -> TechnicalMomentumComponentLoad:
        component = TechnicalMomentumComponent.TREND_ALIGNMENT
        if len(bars) < 200:
            return self._missing(component, "200 daily bars are required")
        latest = bars[-1]
        closes = [bar.close for bar in bars]
        ma50, ma200 = sum(closes[-50:]) / 50, sum(closes[-200:]) / 200
        if ma50 <= 0 or ma200 <= 0:
            return self._missing(component, "moving averages must be positive")
        distances = (
            _clip((latest.close / ma50 - 1.0) / 0.08),
            _clip((latest.close / ma200 - 1.0) / 0.15),
            _clip((ma50 / ma200 - 1.0) / 0.10),
        )
        value = latest.close / ma200 - 1.0
        return self._loaded(
            component,
            value,
            _clip(sum(distances) / 3),
            latest,
            f"Price was {latest.close / ma50 - 1.0:.1%} versus the 50-session "
            f"average and {value:.1%} versus the 200-session average; the "
            f"50-session average was {ma50 / ma200 - 1.0:.1%} versus the 200-session average.",
        )

    def _volatility(self, bars: tuple[PriceBar, ...]) -> TechnicalMomentumComponentLoad:
        component = TechnicalMomentumComponent.VOLATILITY_PRESSURE
        if len(bars) < 80:
            return self._missing(component, "at least 80 daily bars are required")
        closes = [bar.close for bar in bars]
        returns = [
            closes[index] / closes[index - 1] - 1.0
            for index in range(1, len(closes))
            if closes[index - 1] > 0
        ]
        current = _ann_vol(returns[-20:])
        history = [
            _ann_vol(returns[end - 20:end])
            for end in range(40, len(returns) - 20)
            if len(returns[end - 20:end]) == 20
        ]
        if len(history) < 20:
            return self._missing(component, "at least 20 prior volatility windows are required")
        percentile = sum(value <= current for value in history) / len(history)
        return self._loaded(
            component,
            current,
            _clip(1.0 - 2.0 * percentile),
            bars[-1],
            f"20-session annualized realized volatility was {current:.1%}, at the "
            f"{percentile:.0%} percentile of the available point-in-time history.",
        )

    def _drawdown(self, bars: tuple[PriceBar, ...]) -> TechnicalMomentumComponentLoad:
        component = TechnicalMomentumComponent.DRAWDOWN_STATE
        if len(bars) < 252:
            return self._missing(component, "252 daily bars are required")
        latest = bars[-1]
        peak = max(bar.close for bar in bars[-252:])
        if peak <= 0:
            return self._missing(component, "rolling peak price is non-positive")
        value = latest.close / peak - 1.0
        return self._loaded(
            component,
            value,
            _clip(1.0 + value / 0.15),
            latest,
            f"The benchmark was {abs(value):.1%} below its highest close in the "
            "available 252-session window.",
        )

    @staticmethod
    def _loaded(
        component: TechnicalMomentumComponent,
        value: float,
        signal: float,
        bar: PriceBar,
        explanation: str,
    ) -> TechnicalMomentumComponentLoad:
        return TechnicalMomentumComponentLoad(
            component=component,
            state=TechnicalMomentumLoadState.LOADED,
            value=value,
            signal=_clip(signal),
            observed_at=bar.provenance.observed_at,
            retrieved_at=bar.provenance.retrieved_at,
            quality_state=bar.provenance.quality_state,
            explanation=explanation,
        )

    @staticmethod
    def _missing(
        component: TechnicalMomentumComponent,
        reason: str,
    ) -> TechnicalMomentumComponentLoad:
        return TechnicalMomentumComponentLoad(
            component=component,
            state=TechnicalMomentumLoadState.UNAVAILABLE,
            error=reason,
        )

    @staticmethod
    def _direction(
        composite: float,
        items: dict[TechnicalMomentumComponent, TechnicalMomentumComponentLoad],
    ) -> EngineDirection:
        signals = {key: float(value.signal) for key, value in items.items()}
        positives = sum(value >= 0.25 for value in signals.values())
        negatives = sum(value <= -0.25 for value in signals.values())
        trend = signals.get(TechnicalMomentumComponent.TREND_ALIGNMENT, 0.0)
        drawdown = signals.get(TechnicalMomentumComponent.DRAWDOWN_STATE, 0.0)
        long_confirm = any(
            signals.get(component, -1.0) >= 0.20
            for component in (
                TechnicalMomentumComponent.SIX_MONTH_MOMENTUM,
                TechnicalMomentumComponent.TWELVE_MONTH_MOMENTUM,
            )
        )
        negative_momentum = sum(
            signals.get(component, 0.0) <= -0.25
            for component in (
                TechnicalMomentumComponent.THREE_MONTH_MOMENTUM,
                TechnicalMomentumComponent.SIX_MONTH_MOMENTUM,
                TechnicalMomentumComponent.TWELVE_MONTH_MOMENTUM,
            )
        )
        if composite >= 0.32 and positives >= 4 and trend >= 0.15 and long_confirm and drawdown > -0.35:
            return EngineDirection.EXPANDING
        if composite <= -0.45 and negatives >= 4 and trend <= -0.35 and drawdown <= -0.40:
            return EngineDirection.STRESSED
        if composite <= -0.18 or (trend <= -0.25 and negative_momentum >= 2):
            return EngineDirection.CONTRACTING
        return EngineDirection.NEUTRAL

    def _status(
        self,
        as_of: datetime,
        bars: tuple[PriceBar, ...],
        coverage: float,
        loaded: tuple[TechnicalMomentumComponentLoad, ...],
    ) -> EngineDataStatus:
        latest = bars[-1]
        if (
            as_of - latest.provenance.observed_at > self.stale_after
            or latest.provenance.quality_state is DataQualityState.STALE
            or any(load.quality_state is DataQualityState.STALE for load in loaded)
        ):
            return EngineDataStatus.STALE
        return EngineDataStatus.INCOMPLETE if coverage < 0.999 else EngineDataStatus.CURRENT

    @staticmethod
    def _risks(
        direction: EngineDirection,
        coverage: float,
        status: EngineDataStatus,
        items: dict[TechnicalMomentumComponent, TechnicalMomentumComponentLoad],
        loads: tuple[TechnicalMomentumComponentLoad, ...],
    ) -> tuple[str, ...]:
        risks: list[str] = []
        if coverage < 0.999:
            unavailable = [
                _LABELS[load.component]
                for load in loads
                if load.state is TechnicalMomentumLoadState.UNAVAILABLE
            ]
            risks.append(
                "Technical coverage is incomplete; unavailable components: "
                + ", ".join(unavailable) + "."
            )
        if status is EngineDataStatus.STALE:
            risks.append("The latest price evidence is stale and should not influence current action.")
        short = items.get(TechnicalMomentumComponent.ONE_MONTH_MOMENTUM)
        long = items.get(TechnicalMomentumComponent.TWELVE_MONTH_MOMENTUM)
        if short and long and float(short.signal) * float(long.signal) < -0.10:
            risks.append(
                "Short- and long-horizon momentum disagree, so the apparent trend "
                "may be a rebound or an early reversal."
            )
        volatility = items.get(TechnicalMomentumComponent.VOLATILITY_PRESSURE)
        if volatility and float(volatility.signal) <= -0.35:
            risks.append(
                "Realized volatility is elevated relative to its own history, "
                "which can make trend persistence less dependable."
            )
        drawdown = items.get(TechnicalMomentumComponent.DRAWDOWN_STATE)
        if drawdown and float(drawdown.signal) <= -0.40:
            risks.append(
                "The benchmark remains in a material drawdown, increasing "
                "path-dependency and behavioral risk."
            )
        if direction is EngineDirection.EXPANDING:
            risks.append(
                "Positive technical support can reverse without a change in "
                "fundamental value or long-term objectives."
            )
        if not risks:
            risks.append(
                "Technical evidence is path-dependent and must be interpreted "
                "with valuation, macro, risk, and investor-objective context."
            )
        return tuple(risks)

    @staticmethod
    def _summary(direction: EngineDirection, benchmark: str) -> str:
        return {
            EngineDirection.EXPANDING: f"{benchmark} technical support is broad and persistent.",
            EngineDirection.NEUTRAL: f"{benchmark} technical evidence is mixed or transitional.",
            EngineDirection.CONTRACTING: f"{benchmark} momentum and trend support are weakening.",
            EngineDirection.STRESSED: f"{benchmark} shows a confirmed technical breakdown.",
            EngineDirection.UNAVAILABLE: f"{benchmark} technical evidence is unavailable.",
        }[direction]

    def _unavailable(self, as_of: datetime, reason: str) -> AnalyticalEngineResult:
        return AnalyticalEngineResult(
            identifier=f"analytical-engine:{self.engine_name}:{as_of.isoformat()}:unavailable",
            engine=self.engine_name,
            scope=self.scope,
            policy_version=self.policy_version,
            as_of=as_of,
            generated_at=_aware(self._clock(), "clock"),
            direction=EngineDirection.UNAVAILABLE,
            score=0,
            confidence=0,
            coverage=0.0,
            data_status=EngineDataStatus.UNAVAILABLE,
            summary="Technical and momentum intelligence is unavailable.",
            explanation=f"{reason}. No fallback price history or synthetic signal was used.",
            risks=("Technical evidence is unavailable and must not influence action.",),
            transmission_channels=("No technical transmission conclusion is available.",),
            review_conditions=("Configure a point-in-time benchmark price history and rerun.",),
            evidence=(),
        )


def build_configured_technical_momentum_engine(
    *,
    clock: Callable[[], datetime] | None = None,
) -> TechnicalMomentumEngine:
    source = os.environ.get("CAPITAL_INTELLIGENCE_TECHNICAL_MOMENTUM_FILE")
    provider: TechnicalMomentumDataProvider = (
        JSONTechnicalMomentumProvider(source)
        if source and source.strip()
        else UnavailableTechnicalMomentumProvider()
    )
    return TechnicalMomentumEngine(provider, clock=clock)


def technical_momentum_source_readiness() -> tuple[bool, str]:
    source = os.environ.get("CAPITAL_INTELLIGENCE_TECHNICAL_MOMENTUM_FILE")
    if not source or not source.strip():
        return (
            True,
            "technical and momentum source is not configured; the engine will "
            "publish unavailable without blocking the core daily intelligence path",
        )
    path = Path(source).expanduser()
    if not path.is_file() or not os.access(path, os.R_OK):
        return False, f"configured technical and momentum source is unavailable: {path}"
    try:
        JSONTechnicalMomentumProvider(path)._load()
    except (OSError, ValueError, TechnicalMomentumDataError) as error:
        return False, f"configured technical and momentum source is invalid: {error}"
    return True, f"technical and momentum source is readable: {path}"


def _dedupe(bars: tuple[PriceBar, ...], as_of: datetime) -> tuple[PriceBar, ...]:
    resolved = _aware(as_of, "as_of")
    selected: dict[datetime, PriceBar] = {}
    for bar in bars:
        if (
            bar.end_at > resolved
            or bar.provenance.observed_at > resolved
            or bar.provenance.quality_state is DataQualityState.MISSING
        ):
            continue
        previous = selected.get(bar.end_at)
        if previous is None or bar.provenance.retrieved_at > previous.provenance.retrieved_at:
            selected[bar.end_at] = bar
    return tuple(selected[key] for key in sorted(selected))


def _ann_vol(values: list[float]) -> float:
    return 0.0 if len(values) < 2 else pstdev(values) * sqrt(252.0)


def _quality(value: object) -> DataQualityState:
    try:
        return DataQualityState(str(value).strip().lower())
    except ValueError as error:
        raise TechnicalMomentumDataError(f"unsupported data quality state: {value}") from error


def _dt(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise TechnicalMomentumDataError(f"{field} must be an ISO timestamp")
    try:
        return _aware(datetime.fromisoformat(value.strip().replace("Z", "+00:00")), field)
    except ValueError as error:
        raise TechnicalMomentumDataError(f"{field} must be an ISO timestamp") from error


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _clip(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


__all__ = [
    "JSONTechnicalMomentumProvider",
    "TechnicalMomentumComponent",
    "TechnicalMomentumComponentLoad",
    "TechnicalMomentumDataError",
    "TechnicalMomentumDataProvider",
    "TechnicalMomentumDataset",
    "TechnicalMomentumEngine",
    "TechnicalMomentumLoadState",
    "TechnicalMomentumRun",
    "UnavailableTechnicalMomentumProvider",
    "build_configured_technical_momentum_engine",
    "technical_momentum_source_readiness",
]
