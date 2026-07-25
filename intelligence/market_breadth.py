"""Deterministic point-in-time market-breadth intelligence engine."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from data import (
    BarInterval,
    CanonicalMarketDataProvider,
    DataQualityState,
    MarketDataBatch,
    MarketDataError,
    MarketDataProvenance,
    MarketDataQuery,
    MarketDataType,
    PriceBar,
)
from intelligence.analytical_engine import (
    AnalyticalEngineResult,
    EngineDataStatus,
    EngineDirection,
    EngineEvidence,
)


class MarketBreadthComponent(str, Enum):
    DAILY_PARTICIPATION = "daily_participation"
    TWENTY_DAY_PARTICIPATION = "twenty_day_participation"
    ABOVE_FIFTY_DAY = "above_fifty_day"
    ABOVE_TWO_HUNDRED_DAY = "above_two_hundred_day"
    NEW_HIGHS_MINUS_LOWS = "new_highs_minus_lows"
    EQUAL_WEIGHT_LEADERSHIP = "equal_weight_leadership"


class MarketBreadthLoadState(str, Enum):
    LOADED = "loaded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class BreadthUniverseMember:
    instrument_id: str
    venue: str
    weight: float
    sector: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in ("instrument_id", "venue"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(
                self,
                field_name,
                value.strip().upper() if field_name == "venue" else value.strip(),
            )
        if isinstance(self.weight, bool) or not isinstance(self.weight, (int, float)):
            raise TypeError("weight must be numeric")
        normalized_weight = float(self.weight)
        if not isfinite(normalized_weight) or normalized_weight <= 0:
            raise ValueError("weight must be positive and finite")
        object.__setattr__(self, "weight", normalized_weight)
        if self.sector is not None:
            if not isinstance(self.sector, str) or not self.sector.strip():
                raise ValueError("sector must be a non-empty string or None")
            object.__setattr__(self, "sector", self.sector.strip())
        for field_name in ("effective_from", "effective_to"):
            value = getattr(self, field_name)
            if value is not None:
                _require_aware(value, field_name)
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_from >= self.effective_to
        ):
            raise ValueError("effective_from must be earlier than effective_to")

    def active_at(self, as_of: datetime) -> bool:
        resolved = _require_aware(as_of, "as_of")
        return (
            (self.effective_from is None or self.effective_from <= resolved)
            and (self.effective_to is None or resolved < self.effective_to)
        )


@dataclass(frozen=True, slots=True)
class BreadthUniverseSnapshot:
    identifier: str
    source_identifier: str
    source_fingerprint: str
    provider: str
    as_of: datetime
    observed_at: datetime
    retrieved_at: datetime
    quality_state: DataQualityState
    members: tuple[BreadthUniverseMember, ...]

    def __post_init__(self) -> None:
        for field_name in ("identifier", "source_identifier", "provider"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())
        if (
            not isinstance(self.source_fingerprint, str)
            or len(self.source_fingerprint.strip()) != 64
            or any(ch not in "0123456789abcdefABCDEF" for ch in self.source_fingerprint)
        ):
            raise ValueError("source_fingerprint must be a 64-character SHA-256 hex digest")
        object.__setattr__(self, "source_fingerprint", self.source_fingerprint.lower())
        as_of = _require_aware(self.as_of, "as_of")
        observed_at = _require_aware(self.observed_at, "observed_at")
        retrieved_at = _require_aware(self.retrieved_at, "retrieved_at")
        if observed_at > as_of:
            raise ValueError("universe observed_at cannot be later than as_of")
        if observed_at > retrieved_at:
            raise ValueError("universe observed_at cannot be later than retrieved_at")
        if not isinstance(self.quality_state, DataQualityState):
            raise TypeError("quality_state must be a DataQualityState")
        if self.quality_state is DataQualityState.MISSING:
            raise ValueError("universe quality_state cannot be missing")
        if not isinstance(self.members, tuple) or not self.members:
            raise ValueError("members must be a non-empty tuple")
        if not all(isinstance(member, BreadthUniverseMember) for member in self.members):
            raise TypeError("members must contain BreadthUniverseMember values")
        active = tuple(member for member in self.members if member.active_at(as_of))
        if len(active) != len(self.members):
            raise ValueError("universe snapshot can contain only members active at as_of")
        identifiers = [member.instrument_id for member in self.members]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("universe member instrument identifiers must be unique")


@runtime_checkable
class MarketBreadthDataProvider(CanonicalMarketDataProvider, Protocol):
    """Provider for a point-in-time universe plus canonical daily bars."""

    def fetch_universe(self, *, as_of: datetime) -> BreadthUniverseSnapshot:
        """Return the active investment universe known at the decision time."""


@dataclass(frozen=True, slots=True)
class MarketBreadthMemberLoad:
    member: BreadthUniverseMember
    state: MarketBreadthLoadState
    bars: tuple[PriceBar, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.member, BreadthUniverseMember):
            raise TypeError("member must be a BreadthUniverseMember")
        if not isinstance(self.state, MarketBreadthLoadState):
            raise TypeError("state must be a MarketBreadthLoadState")
        if not all(isinstance(bar, PriceBar) for bar in self.bars):
            raise TypeError("bars must contain PriceBar values")
        if self.state is MarketBreadthLoadState.LOADED:
            if len(self.bars) < 2:
                raise ValueError("loaded members require at least two bars")
            if self.error is not None:
                raise ValueError("loaded members cannot contain an error")
        else:
            if self.bars:
                raise ValueError("unavailable members cannot contain bars")
            if not isinstance(self.error, str) or not self.error.strip():
                raise ValueError("unavailable members require an error")


@dataclass(frozen=True, slots=True)
class MarketBreadthRun:
    as_of: datetime
    provider: str
    universe: BreadthUniverseSnapshot | None
    loads: tuple[MarketBreadthMemberLoad, ...]
    result: AnalyticalEngineResult

    @property
    def loaded_count(self) -> int:
        return sum(load.state is MarketBreadthLoadState.LOADED for load in self.loads)

    @property
    def unavailable_count(self) -> int:
        return len(self.loads) - self.loaded_count


@dataclass(frozen=True, slots=True)
class _ComponentResult:
    component: MarketBreadthComponent
    signal: float
    coverage: float
    quality: float
    observed_at: datetime
    retrieved_at: datetime
    quality_state: DataQualityState
    explanation: str


_COMPONENT_WEIGHTS = {
    MarketBreadthComponent.DAILY_PARTICIPATION: 0.15,
    MarketBreadthComponent.TWENTY_DAY_PARTICIPATION: 0.15,
    MarketBreadthComponent.ABOVE_FIFTY_DAY: 0.20,
    MarketBreadthComponent.ABOVE_TWO_HUNDRED_DAY: 0.20,
    MarketBreadthComponent.NEW_HIGHS_MINUS_LOWS: 0.15,
    MarketBreadthComponent.EQUAL_WEIGHT_LEADERSHIP: 0.15,
}

_QUALITY_WEIGHT = {
    DataQualityState.LIVE: 1.00,
    DataQualityState.FIXTURE: 1.00,
    DataQualityState.CACHED: 0.90,
    DataQualityState.FALLBACK: 0.60,
    DataQualityState.STALE: 0.40,
    DataQualityState.MISSING: 0.00,
}


class UnavailableMarketBreadthProvider:
    """Explicit unavailable provider used until a licensed feed is configured."""

    name = "UNCONFIGURED_MARKET_BREADTH"

    def fetch_universe(self, *, as_of: datetime) -> BreadthUniverseSnapshot:
        _require_aware(as_of, "as_of")
        raise MarketDataError(
            "market breadth source is not configured; set "
            "CAPITAL_INTELLIGENCE_MARKET_BREADTH_FILE to an immutable provider export"
        )

    def fetch(self, query: MarketDataQuery) -> MarketDataBatch:
        del query
        raise MarketDataError("market breadth source is not configured")


class JSONMarketBreadthProvider:
    """Read one immutable point-in-time universe and daily-bar provider export."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self._payload: dict[str, Any] | None = None
        self._fingerprint: str | None = None

    @property
    def name(self) -> str:
        payload = self._load()
        provider = payload.get("provider", "FILE_MARKET_BREADTH")
        return str(provider).strip().upper()

    def _load(self) -> dict[str, Any]:
        if self._payload is None:
            try:
                raw = self.path.read_bytes()
            except OSError as error:
                raise MarketDataError(
                    f"market breadth file is unavailable: {self.path}: {error}"
                ) from error
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise MarketDataError(
                    f"market breadth file is not valid UTF-8 JSON: {self.path}"
                ) from error
            if not isinstance(payload, dict):
                raise MarketDataError("market breadth document must be a JSON object")
            if payload.get("schema_version") != "market-breadth-input.v1":
                raise MarketDataError(
                    "market breadth document must use market-breadth-input.v1"
                )
            self._payload = payload
            self._fingerprint = hashlib.sha256(raw).hexdigest()
        return self._payload

    def fetch_universe(self, *, as_of: datetime) -> BreadthUniverseSnapshot:
        resolved = _require_aware(as_of, "as_of")
        payload = self._load()
        universe = payload.get("universe")
        if not isinstance(universe, dict):
            raise MarketDataError("market breadth document is missing universe")
        snapshot_as_of = _parse_datetime(universe.get("as_of"), "universe.as_of")
        if snapshot_as_of > resolved:
            raise MarketDataError("market breadth universe is from after the decision time")
        members_payload = universe.get("members")
        if not isinstance(members_payload, list) or not members_payload:
            raise MarketDataError("market breadth universe members are unavailable")
        members: list[BreadthUniverseMember] = []
        for item in members_payload:
            if not isinstance(item, dict):
                raise MarketDataError("market breadth universe members must be objects")
            member = BreadthUniverseMember(
                instrument_id=str(item.get("instrument_id", "")),
                venue=str(item.get("venue", "")),
                weight=float(item.get("weight", 0)),
                sector=(None if item.get("sector") is None else str(item["sector"])),
                effective_from=_parse_optional_datetime(item.get("effective_from")),
                effective_to=_parse_optional_datetime(item.get("effective_to")),
            )
            if member.active_at(resolved):
                members.append(member)
        if not members:
            raise MarketDataError("no market breadth universe members were active at as_of")
        return BreadthUniverseSnapshot(
            identifier=str(universe.get("identifier", "configured_universe")),
            source_identifier=str(payload.get("source_identifier", self.path.name)),
            source_fingerprint=str(self._fingerprint),
            provider=self.name,
            as_of=resolved,
            observed_at=_parse_datetime(
                universe.get("observed_at", universe.get("as_of")),
                "universe.observed_at",
            ),
            retrieved_at=_parse_datetime(
                universe.get(
                    "retrieved_at",
                    universe.get("observed_at", universe.get("as_of")),
                ),
                "universe.retrieved_at",
            ),
            quality_state=_quality_state(universe.get("quality_state", "cached")),
            members=tuple(members),
        )

    def fetch(self, query: MarketDataQuery) -> MarketDataBatch:
        if not isinstance(query, MarketDataQuery):
            raise TypeError("query must be a MarketDataQuery")
        if query.data_type is not MarketDataType.BAR or query.interval is not BarInterval.DAY:
            raise MarketDataError("market breadth file supports daily bar queries only")
        payload = self._load()
        records_payload = payload.get("bars")
        if not isinstance(records_payload, list):
            raise MarketDataError("market breadth document is missing bars")
        records: list[PriceBar] = []
        for item in records_payload:
            if not isinstance(item, dict):
                continue
            if str(item.get("instrument_id", "")) != query.instrument_id:
                continue
            venue = str(item.get("venue", "")).upper()
            if query.venue is not None and venue != query.venue:
                continue
            observed_at = _parse_datetime(item.get("observed_at"), "bar.observed_at")
            if observed_at > query.as_of:
                continue
            if query.start_at is not None and observed_at < query.start_at:
                continue
            records.append(
                PriceBar(
                    instrument_id=query.instrument_id,
                    currency=str(item.get("currency", "USD")),
                    interval=BarInterval.DAY,
                    start_at=_parse_datetime(item.get("start_at"), "bar.start_at"),
                    end_at=_parse_datetime(item.get("end_at"), "bar.end_at"),
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item.get("volume", 0)),
                    provenance=MarketDataProvenance(
                        provider=self.name,
                        venue=venue,
                        observed_at=observed_at,
                        retrieved_at=_parse_datetime(
                            item.get("retrieved_at", item.get("observed_at")),
                            "bar.retrieved_at",
                        ),
                        quality_state=_quality_state(
                            item.get("quality_state", "cached")
                        ),
                        provider_record_id=(
                            None
                            if item.get("provider_record_id") is None
                            else str(item["provider_record_id"])
                        ),
                    ),
                )
            )
        ordered = tuple(
            sorted(
                records,
                key=lambda bar: (bar.end_at, bar.provenance.retrieved_at),
            )[-query.limit :]
        )
        return MarketDataBatch(query=query, records=ordered)


class MarketBreadthEngine:
    """Measure participation inside one explicit point-in-time equity universe."""

    engine_name = "market_breadth"
    scope = "Configured point-in-time equity-universe market participation"
    policy_version = "market-breadth-policy.v1"

    def __init__(
        self,
        provider: MarketBreadthDataProvider,
        *,
        minimum_universe_size: int = 5,
        stale_after: timedelta = timedelta(days=5),
        universe_stale_after: timedelta = timedelta(days=35),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not hasattr(provider, "fetch_universe") or not hasattr(provider, "fetch"):
            raise TypeError("provider must expose fetch_universe and fetch")
        if isinstance(minimum_universe_size, bool) or not isinstance(
            minimum_universe_size, int
        ):
            raise TypeError("minimum_universe_size must be an int")
        if minimum_universe_size < 3:
            raise ValueError("minimum_universe_size must be at least 3")
        if not isinstance(stale_after, timedelta) or stale_after <= timedelta(0):
            raise ValueError("stale_after must be a positive timedelta")
        if (
            not isinstance(universe_stale_after, timedelta)
            or universe_stale_after <= timedelta(0)
        ):
            raise ValueError("universe_stale_after must be a positive timedelta")
        self.provider = provider
        self.minimum_universe_size = minimum_universe_size
        self.stale_after = stale_after
        self.universe_stale_after = universe_stale_after
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self, *, as_of: datetime) -> MarketBreadthRun:
        resolved = _require_aware(as_of, "as_of")
        try:
            universe = self.provider.fetch_universe(as_of=resolved)
        except (MarketDataError, OSError, ValueError) as error:
            result = self._unavailable(resolved, str(error))
            return MarketBreadthRun(
                as_of=resolved,
                provider=getattr(self.provider, "name", "market_breadth"),
                universe=None,
                loads=(),
                result=result,
            )
        if len(universe.members) < self.minimum_universe_size:
            reason = (
                f"universe {universe.identifier} contains {len(universe.members)} members; "
                f"at least {self.minimum_universe_size} are required"
            )
            return MarketBreadthRun(
                as_of=resolved,
                provider=universe.provider,
                universe=universe,
                loads=(),
                result=self._unavailable(resolved, reason),
            )

        loads: list[MarketBreadthMemberLoad] = []
        start_at = resolved - timedelta(days=550)
        for member in universe.members:
            query = MarketDataQuery(
                instrument_id=member.instrument_id,
                data_type=MarketDataType.BAR,
                as_of=resolved,
                start_at=start_at,
                venue=member.venue,
                interval=BarInterval.DAY,
                limit=400,
            )
            try:
                batch = self.provider.fetch(query)
                bars = _deduplicate_bars(tuple(batch.records), resolved)
                if len(bars) < 2:
                    raise MarketDataError("fewer than two point-in-time daily bars")
            except (MarketDataError, OSError, ValueError) as error:
                loads.append(
                    MarketBreadthMemberLoad(
                        member=member,
                        state=MarketBreadthLoadState.UNAVAILABLE,
                        error=str(error),
                    )
                )
                continue
            loads.append(
                MarketBreadthMemberLoad(
                    member=member,
                    state=MarketBreadthLoadState.LOADED,
                    bars=bars,
                )
            )

        loaded = tuple(
            load for load in loads if load.state is MarketBreadthLoadState.LOADED
        )
        if len(loaded) < self.minimum_universe_size:
            result = self._unavailable(
                resolved,
                f"only {len(loaded)} universe members had usable point-in-time bars",
            )
            return MarketBreadthRun(
                as_of=resolved,
                provider=universe.provider,
                universe=universe,
                loads=tuple(loads),
                result=result,
            )

        components = tuple(
            item
            for item in (
                self._participation_component(
                    MarketBreadthComponent.DAILY_PARTICIPATION,
                    loaded,
                    universe,
                    periods=1,
                ),
                self._participation_component(
                    MarketBreadthComponent.TWENTY_DAY_PARTICIPATION,
                    loaded,
                    universe,
                    periods=20,
                ),
                self._moving_average_component(
                    MarketBreadthComponent.ABOVE_FIFTY_DAY,
                    loaded,
                    universe,
                    window=50,
                ),
                self._moving_average_component(
                    MarketBreadthComponent.ABOVE_TWO_HUNDRED_DAY,
                    loaded,
                    universe,
                    window=200,
                ),
                self._new_high_low_component(loaded, universe),
                self._leadership_component(loaded, universe),
            )
            if item is not None
        )
        if not components:
            result = self._unavailable(
                resolved,
                "no breadth component had sufficient constituent history",
            )
            return MarketBreadthRun(
                as_of=resolved,
                provider=universe.provider,
                universe=universe,
                loads=tuple(loads),
                result=result,
            )

        evidence = tuple(
            EngineEvidence(
                identifier=(
                    f"engine-evidence:{self.engine_name}:{universe.identifier}:"
                    f"{component.component.value}:{component.observed_at.date().isoformat()}"
                ),
                component=component.component.value,
                indicator=component.component.value,
                provider=universe.provider,
                series_identifier=(
                    f"{universe.source_identifier}:{universe.source_fingerprint}:"
                    f"{component.component.value}"
                ),
                observation_date=component.observed_at.date(),
                released_at=component.observed_at,
                retrieved_at=max(component.retrieved_at, component.observed_at),
                vintage_date=component.observed_at.date(),
                quality_state=component.quality_state.value,
                signal_score=component.signal,
                weighted_contribution=_clip(
                    _COMPONENT_WEIGHTS[component.component] * component.signal
                ),
                explanation=component.explanation,
            )
            for component in components
        )
        available_weight = sum(
            _COMPONENT_WEIGHTS[item.component] for item in components
        )
        composite = sum(
            _COMPONENT_WEIGHTS[item.component] * item.signal for item in components
        ) / available_weight
        score = max(0, min(100, round(50 + 50 * composite)))
        coverage = sum(
            _COMPONENT_WEIGHTS[item.component] * item.coverage
            for item in components
        )
        coverage = min(1.0, coverage)
        component_quality = sum(
            _COMPONENT_WEIGHTS[item.component] * item.quality
            for item in components
        ) / available_weight
        universe_quality = _QUALITY_WEIGHT[universe.quality_state]
        quality = 0.85 * component_quality + 0.15 * universe_quality
        agreement = max(
            0.0,
            1.0
            - min(
                1.0,
                sum(
                    _COMPONENT_WEIGHTS[item.component]
                    * abs(item.signal - composite)
                    for item in components
                )
                / available_weight,
            ),
        )
        sample_strength = min(1.0, len(loaded) / 20.0)
        confidence = round(
            100
            * (
                0.50 * coverage
                + 0.25 * quality
                + 0.15 * agreement
                + 0.10 * sample_strength
            )
        )
        stale_weight = sum(
            load.member.weight
            for load in loaded
            if _bar_is_stale(load.bars[-1], resolved, self.stale_after)
        )
        loaded_member_weight = sum(load.member.weight for load in loaded)
        stale_share = (
            stale_weight / loaded_member_weight if loaded_member_weight else 1.0
        )
        universe_stale = (
            universe.quality_state is DataQualityState.STALE
            or universe.observed_at + self.universe_stale_after < resolved
        )
        if stale_share >= 0.50 or universe_stale:
            status = EngineDataStatus.STALE
        elif coverage < 0.999 or len(loaded) < len(universe.members):
            status = EngineDataStatus.INCOMPLETE
        else:
            status = EngineDataStatus.CURRENT

        by_component = {item.component: item for item in components}
        direction = _direction(score, by_component, available_weight)
        risks = self._risks(
            direction=direction,
            universe=universe,
            loads=tuple(loads),
            components=by_component,
            coverage=coverage,
            stale_share=stale_share,
            universe_stale=universe_stale,
        )
        summary = {
            EngineDirection.EXPANDING: (
                f"Market participation is broadening across {universe.identifier}."
            ),
            EngineDirection.NEUTRAL: (
                f"Market breadth is mixed or narrowly led across {universe.identifier}."
            ),
            EngineDirection.CONTRACTING: (
                f"Market participation is weakening across {universe.identifier}."
            ),
            EngineDirection.STRESSED: (
                f"Market breadth shows broad internal stress across {universe.identifier}."
            ),
        }[direction]
        strongest = sorted(
            components, key=lambda item: item.signal, reverse=True
        )[:2]
        weakest = sorted(components, key=lambda item: item.signal)[:2]
        explanation = (
            f"{summary} Supportive components are "
            + ", ".join(
                item.component.value.replace("_", " ") for item in strongest
            )
            + "; weaker components are "
            + ", ".join(
                item.component.value.replace("_", " ") for item in weakest
            )
            + f". Weighted constituent coverage is {coverage:.0%}; confidence is {confidence}%."
        )
        result = AnalyticalEngineResult(
            identifier=f"analytical-engine:{self.engine_name}:{resolved.isoformat()}",
            engine=self.engine_name,
            scope=f"{self.scope}: {universe.identifier}",
            policy_version=self.policy_version,
            as_of=resolved,
            generated_at=resolved,
            direction=direction,
            score=score,
            confidence=confidence,
            coverage=round(coverage, 6),
            data_status=status,
            summary=summary,
            explanation=explanation,
            risks=risks,
            transmission_channels=_transmission(direction),
            review_conditions=(
                "Reassess if the market-breadth score crosses 45 or 60.",
                "Escalate review if fewer than 30% of covered constituents remain above their 200-day average and new lows materially exceed new highs.",
                "Reduce confidence when weighted constituent coverage falls below 80%.",
                "Review concentration if capitalization-weighted returns materially outpace equal-weight returns while participation weakens.",
            ),
            evidence=evidence,
        )
        return MarketBreadthRun(
            as_of=resolved,
            provider=universe.provider,
            universe=universe,
            loads=tuple(loads),
            result=result,
        )

    def run_current(self) -> MarketBreadthRun:
        now = self._clock()
        _require_aware(now, "clock")
        return self.run(as_of=now)

    def _unavailable(self, as_of: datetime, reason: str) -> AnalyticalEngineResult:
        return AnalyticalEngineResult(
            identifier=f"analytical-engine:{self.engine_name}:{as_of.isoformat()}",
            engine=self.engine_name,
            scope=self.scope,
            policy_version=self.policy_version,
            as_of=as_of,
            generated_at=as_of,
            direction=EngineDirection.UNAVAILABLE,
            score=50,
            confidence=0,
            coverage=0.0,
            data_status=EngineDataStatus.UNAVAILABLE,
            summary="Market-breadth evidence is unavailable.",
            explanation=(
                "The engine could not form a defensible point-in-time cross-sectional "
                f"breadth conclusion: {reason}."
            ),
            risks=(reason,),
            transmission_channels=_transmission(EngineDirection.UNAVAILABLE),
            review_conditions=(
                "Configure and retain an immutable point-in-time universe and constituent daily-bar source before relying on market breadth.",
            ),
            evidence=(),
        )

    def _participation_component(
        self,
        component: MarketBreadthComponent,
        loads: tuple[MarketBreadthMemberLoad, ...],
        universe: BreadthUniverseSnapshot,
        *,
        periods: int,
    ) -> _ComponentResult | None:
        eligible: list[tuple[MarketBreadthMemberLoad, float]] = []
        for load in loads:
            if len(load.bars) <= periods:
                continue
            latest = load.bars[-1].close
            baseline = load.bars[-1 - periods].close
            if baseline == 0:
                continue
            eligible.append((load, latest / baseline - 1.0))
        if len(eligible) < self.minimum_universe_size:
            return None
        advances = sum(change > 0 for _, change in eligible)
        declines = sum(change < 0 for _, change in eligible)
        denominator = advances + declines
        ratio = 0.5 if denominator == 0 else advances / denominator
        signal = _clip((ratio - 0.5) / 0.30)
        label = "one-day" if periods == 1 else f"{periods}-session"
        return self._component_from_members(
            component,
            eligible,
            universe,
            signal,
            f"{advances} of {denominator} moving constituents advanced over the {label} horizon ({ratio:.0%}).",
        )

    def _moving_average_component(
        self,
        component: MarketBreadthComponent,
        loads: tuple[MarketBreadthMemberLoad, ...],
        universe: BreadthUniverseSnapshot,
        *,
        window: int,
    ) -> _ComponentResult | None:
        eligible: list[tuple[MarketBreadthMemberLoad, float]] = []
        for load in loads:
            if len(load.bars) < window:
                continue
            closes = [bar.close for bar in load.bars[-window:]]
            average = sum(closes) / len(closes)
            eligible.append((load, 1.0 if closes[-1] > average else -1.0))
        if len(eligible) < self.minimum_universe_size:
            return None
        above = sum(value > 0 for _, value in eligible)
        ratio = above / len(eligible)
        signal = _clip((ratio - 0.5) / 0.30)
        return self._component_from_members(
            component,
            eligible,
            universe,
            signal,
            f"{above} of {len(eligible)} covered constituents ({ratio:.0%}) closed above their {window}-session average.",
        )

    def _new_high_low_component(
        self,
        loads: tuple[MarketBreadthMemberLoad, ...],
        universe: BreadthUniverseSnapshot,
    ) -> _ComponentResult | None:
        eligible: list[tuple[MarketBreadthMemberLoad, float]] = []
        highs = 0
        lows = 0
        for load in loads:
            if len(load.bars) < 252:
                continue
            previous = [bar.close for bar in load.bars[-252:-1]]
            latest = load.bars[-1].close
            value = 0.0
            if latest >= max(previous):
                highs += 1
                value = 1.0
            elif latest <= min(previous):
                lows += 1
                value = -1.0
            eligible.append((load, value))
        if len(eligible) < self.minimum_universe_size:
            return None
        net = (highs - lows) / len(eligible)
        signal = _clip(net / 0.20)
        return self._component_from_members(
            MarketBreadthComponent.NEW_HIGHS_MINUS_LOWS,
            eligible,
            universe,
            signal,
            f"The covered universe recorded {highs} new 52-week highs and {lows} new 52-week lows; net breadth was {net:+.0%}.",
        )

    def _leadership_component(
        self,
        loads: tuple[MarketBreadthMemberLoad, ...],
        universe: BreadthUniverseSnapshot,
    ) -> _ComponentResult | None:
        eligible: list[tuple[MarketBreadthMemberLoad, float]] = []
        for load in loads:
            if len(load.bars) < 21 or load.bars[-21].close == 0:
                continue
            eligible.append(
                (load, load.bars[-1].close / load.bars[-21].close - 1.0)
            )
        if len(eligible) < self.minimum_universe_size:
            return None
        equal_return = sum(value for _, value in eligible) / len(eligible)
        total_weight = sum(load.member.weight for load, _ in eligible)
        cap_return = sum(
            load.member.weight * value for load, value in eligible
        ) / total_weight
        divergence = equal_return - cap_return
        signal = _clip(divergence / 0.03)
        return self._component_from_members(
            MarketBreadthComponent.EQUAL_WEIGHT_LEADERSHIP,
            eligible,
            universe,
            signal,
            f"Equal-weight 20-session return was {equal_return:+.2%} versus {cap_return:+.2%} for capitalization-weighted leadership; the breadth gap was {divergence:+.2%}.",
        )

    def _component_from_members(
        self,
        component: MarketBreadthComponent,
        eligible: list[tuple[MarketBreadthMemberLoad, float]],
        universe: BreadthUniverseSnapshot,
        signal: float,
        explanation: str,
    ) -> _ComponentResult:
        total_universe_weight = sum(member.weight for member in universe.members)
        eligible_weight = sum(load.member.weight for load, _ in eligible)
        coverage = min(1.0, eligible_weight / total_universe_weight)
        latest_bars = [load.bars[-1] for load, _ in eligible]
        weighted_quality = sum(
            load.member.weight
            * _QUALITY_WEIGHT[load.bars[-1].provenance.quality_state]
            for load, _ in eligible
        ) / eligible_weight
        quality_state = _aggregate_quality(latest_bars)
        return _ComponentResult(
            component=component,
            signal=signal,
            coverage=coverage,
            quality=weighted_quality,
            observed_at=max(bar.provenance.observed_at for bar in latest_bars),
            retrieved_at=max(bar.provenance.retrieved_at for bar in latest_bars),
            quality_state=quality_state,
            explanation=explanation,
        )

    def _risks(
        self,
        *,
        direction: EngineDirection,
        universe: BreadthUniverseSnapshot,
        loads: tuple[MarketBreadthMemberLoad, ...],
        components: dict[MarketBreadthComponent, _ComponentResult],
        coverage: float,
        stale_share: float,
        universe_stale: bool,
    ) -> tuple[str, ...]:
        risks = [
            f"{load.member.instrument_id}: {load.error}"
            for load in loads
            if load.state is MarketBreadthLoadState.UNAVAILABLE
        ][:10]
        if len(components) < 4:
            risks.append(
                f"Only {len(components)} of {len(_COMPONENT_WEIGHTS)} breadth components were available; the direction is constrained by incomplete history."
            )
        if coverage < 0.80:
            risks.append(
                f"Weighted breadth coverage is only {coverage:.0%}; missing constituents can distort participation."
            )
        if stale_share >= 0.50:
            risks.append(
                "At least half of loaded constituent weight is stale at the decision time."
            )
        if universe_stale:
            risks.append(
                "The point-in-time universe snapshot is stale; membership changes may not be reflected."
            )
        if len(universe.members) < 20:
            risks.append(
                f"The configured universe contains only {len(universe.members)} members, which limits cross-sectional confidence."
            )
        leadership = components.get(MarketBreadthComponent.EQUAL_WEIGHT_LEADERSHIP)
        participation = components.get(
            MarketBreadthComponent.TWENTY_DAY_PARTICIPATION
        )
        if leadership is not None and leadership.signal <= -0.50:
            risks.append(
                "Capitalization-weighted leadership materially exceeds equal-weight participation, indicating concentration beneath headline index performance."
            )
        positive = sum(item.signal > 0.20 for item in components.values())
        negative = sum(item.signal < -0.20 for item in components.values())
        if positive and negative:
            risks.append(
                "Breadth components disagree, so the composite should not be treated as a uniform market signal."
            )
        if (
            direction is EngineDirection.EXPANDING
            and participation is not None
            and participation.signal < 0
        ):
            risks.append(
                "The composite is positive even though medium-horizon participation remains weak."
            )
        return tuple(risks)


def build_configured_market_breadth_engine(
    *,
    provider: MarketBreadthDataProvider | None = None,
    data_file: str | Path | None = None,
    clock: Callable[[], datetime] | None = None,
) -> MarketBreadthEngine:
    resolved_provider = provider
    if resolved_provider is None:
        configured = data_file or os.environ.get(
            "CAPITAL_INTELLIGENCE_MARKET_BREADTH_FILE"
        )
        resolved_provider = (
            JSONMarketBreadthProvider(configured)
            if configured
            else UnavailableMarketBreadthProvider()
        )
    return MarketBreadthEngine(resolved_provider, clock=clock)


def _direction(
    score: int,
    components: dict[MarketBreadthComponent, _ComponentResult],
    available_weight: float,
) -> EngineDirection:
    advance = components.get(MarketBreadthComponent.DAILY_PARTICIPATION)
    long_trend = components.get(MarketBreadthComponent.ABOVE_TWO_HUNDRED_DAY)
    highs_lows = components.get(MarketBreadthComponent.NEW_HIGHS_MINUS_LOWS)
    leadership = components.get(MarketBreadthComponent.EQUAL_WEIGHT_LEADERSHIP)
    medium = components.get(MarketBreadthComponent.TWENTY_DAY_PARTICIPATION)
    broad_breakdown = (
        advance is not None
        and long_trend is not None
        and highs_lows is not None
        and advance.signal <= -0.50
        and long_trend.signal <= -0.75
        and highs_lows.signal <= -0.50
    )
    if score <= 25 or broad_breakdown:
        return EngineDirection.STRESSED
    if available_weight < 0.50:
        return EngineDirection.NEUTRAL
    if score < 45:
        return EngineDirection.CONTRACTING
    if score <= 60:
        return EngineDirection.NEUTRAL
    narrow_guard = (
        leadership is not None
        and medium is not None
        and leadership.signal <= -0.50
        and medium.signal <= 0
    )
    if narrow_guard:
        return EngineDirection.NEUTRAL
    return EngineDirection.EXPANDING


def _transmission(direction: EngineDirection) -> tuple[str, ...]:
    if direction is EngineDirection.EXPANDING:
        return (
            "Broad participation can make equity gains more resilient and reduce dependence on a small group of index leaders.",
            "Diversified equity exposure generally benefits more when advances extend across sectors and capitalization tiers.",
        )
    if direction is EngineDirection.CONTRACTING:
        return (
            "Narrowing participation can hide fragility beneath headline index strength and increases concentration risk.",
            "Cyclical, smaller-company, and lower-quality equity exposures may weaken before capitalization-weighted indexes fully reflect the change.",
        )
    if direction is EngineDirection.STRESSED:
        return (
            "Broad internal deterioration raises drawdown and concentration risk across equity portfolios.",
            "Portfolio liquidity, diversification, and risk-budget discipline become more important when most constituents are breaking down together.",
        )
    if direction is EngineDirection.UNAVAILABLE:
        return (
            "No market-breadth portfolio conclusion is available because a point-in-time universe and constituent bar source is not available.",
        )
    return (
        "Mixed or narrowly led breadth does not provide a strong standalone portfolio signal.",
        "Headline index performance should be interpreted cautiously when constituent participation is uneven.",
    )


def _deduplicate_bars(
    bars: tuple[PriceBar, ...], as_of: datetime
) -> tuple[PriceBar, ...]:
    latest_by_end: dict[datetime, PriceBar] = {}
    for bar in bars:
        if bar.provenance.observed_at > as_of or bar.end_at > as_of:
            continue
        current = latest_by_end.get(bar.end_at)
        if (
            current is None
            or current.provenance.retrieved_at < bar.provenance.retrieved_at
        ):
            latest_by_end[bar.end_at] = bar
    return tuple(sorted(latest_by_end.values(), key=lambda item: item.end_at))


def _bar_is_stale(
    bar: PriceBar, as_of: datetime, stale_after: timedelta
) -> bool:
    return (
        bar.provenance.quality_state is DataQualityState.STALE
        or bar.end_at + stale_after < as_of
    )


def _aggregate_quality(bars: list[PriceBar]) -> DataQualityState:
    states = {bar.provenance.quality_state for bar in bars}
    for state in (
        DataQualityState.MISSING,
        DataQualityState.STALE,
        DataQualityState.FALLBACK,
        DataQualityState.CACHED,
        DataQualityState.FIXTURE,
        DataQualityState.LIVE,
    ):
        if state in states:
            return state
    return DataQualityState.MISSING


def _quality_state(value: object) -> DataQualityState:
    if isinstance(value, DataQualityState):
        return value
    try:
        return DataQualityState(str(value).strip().lower())
    except ValueError as error:
        raise MarketDataError(
            f"unknown market breadth quality_state: {value}"
        ) from error


def _parse_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise MarketDataError(f"{field_name} must be an ISO-8601 datetime")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise MarketDataError(
            f"{field_name} must be an ISO-8601 datetime"
        ) from error
    return _require_aware(parsed, field_name)


def _parse_optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value, "membership datetime")


def _require_aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _clip(value: float) -> float:
    return max(-1.0, min(1.0, value))


__all__ = [
    "BreadthUniverseMember",
    "BreadthUniverseSnapshot",
    "JSONMarketBreadthProvider",
    "MarketBreadthComponent",
    "MarketBreadthDataProvider",
    "MarketBreadthEngine",
    "MarketBreadthLoadState",
    "MarketBreadthMemberLoad",
    "MarketBreadthRun",
    "UnavailableMarketBreadthProvider",
    "build_configured_market_breadth_engine",
]
