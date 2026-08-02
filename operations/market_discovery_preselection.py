"""Sleeve-balanced, point-in-time preselection for market discovery."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from statistics import fmean
from typing import Any, Mapping, Sequence


class CandidateSleeve(str, Enum):
    QUALITY = "quality"
    VALUE = "value"
    MOMENTUM = "momentum"
    CARRY = "carry"
    DIVERSIFICATION = "diversification"
    IMPROVING_CONDITIONS = "improving_conditions"


SLEEVES = tuple(CandidateSleeve)


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def _score(value: float | None) -> float | None:
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("scores must be between 0 and 1")
    return round(value, 10)


def _tie(as_of: datetime, sleeve: CandidateSleeve, symbol: str) -> float:
    raw = f"{as_of.date()}:{sleeve.value}:{symbol}".encode()
    return int(hashlib.sha256(raw).hexdigest()[:12], 16) / 16**12


@dataclass(frozen=True, slots=True)
class CatalogScreeningSignal:
    symbol: str
    observed_at: datetime
    eligible: bool = True
    liquidity_score: float | None = None
    quality_score: float | None = None
    value_score: float | None = None
    momentum_score: float | None = None
    carry_score: float | None = None
    improving_conditions_score: float | None = None
    indicative_price: float | None = None
    evidence_identifiers: tuple[str, ...] = ()
    exclusion_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        symbol = str(self.symbol).strip().upper()
        if not symbol:
            raise ValueError("symbol cannot be empty")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "observed_at", _aware(self.observed_at))
        for name in (
            "liquidity_score",
            "quality_score",
            "value_score",
            "momentum_score",
            "carry_score",
            "improving_conditions_score",
        ):
            object.__setattr__(self, name, _score(getattr(self, name)))
        if self.indicative_price is not None and float(self.indicative_price) <= 0:
            raise ValueError("indicative_price must be positive")
        if self.indicative_price is not None:
            object.__setattr__(self, "indicative_price", float(self.indicative_price))
        object.__setattr__(
            self,
            "evidence_identifiers",
            tuple(dict.fromkeys(str(item).strip() for item in self.evidence_identifiers if str(item).strip())),
        )
        object.__setattr__(
            self,
            "exclusion_reasons",
            tuple(dict.fromkeys(str(item).strip() for item in self.exclusion_reasons if str(item).strip())),
        )


@dataclass(frozen=True, slots=True)
class PreselectionPlan:
    catalog_count: int
    eligible_count: int
    capacity: int
    selected_symbols: tuple[str, ...]
    shadow_symbols: tuple[str, ...]
    sleeve_rankings: tuple[tuple[str, tuple[str, ...]], ...]
    sleeve_membership: tuple[tuple[str, tuple[str, ...]], ...]
    scores: tuple[tuple[str, tuple[tuple[str, float], ...]], ...]
    factor_coverage: tuple[tuple[str, int], ...]
    exclusions: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_count": self.catalog_count,
            "eligible_count": self.eligible_count,
            "capacity": self.capacity,
            "selected_symbols": list(self.selected_symbols),
            "shadow_symbols": list(self.shadow_symbols),
            "sleeve_rankings": dict(self.sleeve_rankings),
            "sleeve_membership": dict(self.sleeve_membership),
            "scores": {
                symbol: dict(values) for symbol, values in self.scores
            },
            "factor_coverage": dict(self.factor_coverage),
            "exclusions": [list(item) for item in self.exclusions],
        }


@dataclass(frozen=True, slots=True)
class CutoffObservation:
    asset_class: str
    symbol: str
    cohort: str
    observed_at: datetime
    price: float
    sleeves: tuple[str, ...]
    preselection_score: float

    def __post_init__(self) -> None:
        if self.cohort not in {"selected", "below_cutoff"}:
            raise ValueError("invalid cutoff cohort")
        object.__setattr__(self, "observed_at", _aware(self.observed_at))
        if self.price <= 0:
            raise ValueError("price must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_class": self.asset_class,
            "symbol": self.symbol,
            "cohort": self.cohort,
            "observed_at": self.observed_at.isoformat(),
            "price": self.price,
            "sleeves": list(self.sleeves),
            "preselection_score": self.preselection_score,
        }


@dataclass(frozen=True, slots=True)
class CutoffOutcomeEvaluation:
    asset_class: str
    baseline_at: datetime
    evaluated_at: datetime
    selected_count: int
    below_cutoff_count: int
    selected_mean_return: float
    below_cutoff_mean_return: float
    below_minus_selected: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "baseline_at", _aware(self.baseline_at))
        object.__setattr__(self, "evaluated_at", _aware(self.evaluated_at))
        if self.evaluated_at < self.baseline_at:
            raise ValueError("evaluated_at cannot precede baseline_at")
        if self.selected_count < 1 or self.below_cutoff_count < 1:
            raise ValueError("cutoff outcome cohorts cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_class": self.asset_class,
            "baseline_at": self.baseline_at.isoformat(),
            "evaluated_at": self.evaluated_at.isoformat(),
            "selected_count": self.selected_count,
            "below_cutoff_count": self.below_cutoff_count,
            "selected_mean_return": self.selected_mean_return,
            "below_cutoff_mean_return": self.below_cutoff_mean_return,
            "below_minus_selected": self.below_minus_selected,
        }


def default_catalog_screening_signals(
    records: Sequence[object],
    as_of: datetime,
    policy: object | None = None,
) -> Mapping[str, CatalogScreeningSignal]:
    timestamp = _aware(as_of)
    result = {}
    for record in records:
        symbol = str(getattr(record, "symbol", "")).strip().upper()
        required = (
            "provider_symbol",
            "name",
            "venue",
            "currency",
            "instrument_type",
            "source_identifier",
        )
        missing = [name for name in required if not getattr(record, name, None)]
        spread = float(getattr(record, "quote_spread_bps", 250.0))
        expiry = getattr(record, "expiration_at", None)
        lifecycle_ok = expiry is None or _aware(expiry) > timestamp
        liquidity = max(0.0, min(1.0, 1.0 - spread / 250.0))
        result[symbol] = CatalogScreeningSignal(
            symbol=symbol,
            observed_at=timestamp,
            eligible=not missing and lifecycle_ok and 0 < spread <= 250,
            liquidity_score=liquidity,
            quality_score=max(
                0.0, min(1.0, 0.65 * (1 - len(missing) / len(required)) + 0.35 * liquidity)
            ),
            indicative_price=getattr(record, "indicative_price", None),
            evidence_identifiers=(str(getattr(record, "source_identifier", "")),),
            exclusion_reasons=tuple(
                reason
                for condition, reason in (
                    (bool(missing), "catalog_metadata_incomplete"),
                    (not lifecycle_ok, "catalog_lifecycle_expired"),
                    (not 0 < spread <= 250, "catalog_basic_liquidity_failed"),
                )
                if condition
            ),
        )
    return result


def _bucket(record: object) -> tuple[str, str, str, str]:
    return (
        str(getattr(record, "economic_exposure", "unknown")),
        str(getattr(record, "venue", "unknown")),
        str(getattr(record, "country_code", "unknown")),
        str(getattr(record, "currency", "unknown")),
    )


def build_preselection_plan(
    records: Sequence[object],
    signals: Mapping[str, CatalogScreeningSignal],
    *,
    as_of: datetime,
    capacity: int,
    shadow_limit: int,
    freshness_days: int,
    minimum_liquidity_score: float,
) -> PreselectionPlan:
    timestamp = _aware(as_of)
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
        raise ValueError("capacity must be a positive integer")
    if isinstance(shadow_limit, bool) or not isinstance(shadow_limit, int) or shadow_limit < 0:
        raise ValueError("shadow_limit must be a non-negative integer")
    if isinstance(freshness_days, bool) or not isinstance(freshness_days, int) or freshness_days < 0:
        raise ValueError("freshness_days must be a non-negative integer")
    if not 0.0 <= float(minimum_liquidity_score) <= 1.0:
        raise ValueError("minimum_liquidity_score must be between 0 and 1")
    by_symbol = {str(getattr(item, "symbol")).strip().upper(): item for item in records}
    if len(by_symbol) != len(records):
        raise ValueError("preselection records must have unique non-empty symbols")
    normalized_signals = {str(key).strip().upper(): value for key, value in signals.items()}
    eligible, exclusions = [], []
    for symbol, record in by_symbol.items():
        signal = normalized_signals.get(symbol)
        if signal is None:
            exclusions.append((symbol, "catalog_screening_signal_unavailable"))
            continue
        reasons = list(signal.exclusion_reasons)
        age_seconds = (timestamp - signal.observed_at).total_seconds()
        if age_seconds < 0 or age_seconds > freshness_days * 86_400:
            reasons.append("catalog_screening_signal_stale")
        if signal.liquidity_score is None:
            reasons.append("catalog_basic_liquidity_unavailable")
        elif signal.liquidity_score < minimum_liquidity_score:
            reasons.append("catalog_basic_liquidity_failed")
        if not signal.eligible:
            reasons.append("catalog_ineligible")
        if reasons:
            exclusions.extend((symbol, reason) for reason in dict.fromkeys(reasons))
        else:
            eligible.append(record)

    counts = Counter(_bucket(item) for item in eligible)
    scores = {sleeve: {} for sleeve in SLEEVES}
    for record in eligible:
        symbol = str(getattr(record, "symbol")).upper()
        signal = normalized_signals[symbol]
        values = {
            CandidateSleeve.QUALITY: signal.quality_score,
            CandidateSleeve.VALUE: signal.value_score,
            CandidateSleeve.MOMENTUM: signal.momentum_score,
            CandidateSleeve.CARRY: signal.carry_score,
            CandidateSleeve.DIVERSIFICATION: 1.0 / max(1, counts[_bucket(record)]),
            CandidateSleeve.IMPROVING_CONDITIONS: signal.improving_conditions_score,
        }
        for sleeve, value in values.items():
            if value is not None:
                scores[sleeve][symbol] = float(value)

    rankings = {
        sleeve: tuple(
            sorted(
                values,
                key=lambda symbol: (values[symbol], _tie(timestamp, sleeve, symbol), symbol),
                reverse=True,
            )
        )
        for sleeve, values in scores.items()
    }
    selected, seen = [], set()
    cursors = {sleeve: 0 for sleeve in SLEEVES}
    while len(selected) < min(capacity, len(eligible)):
        progressed = False
        for sleeve in SLEEVES:
            ranking, index = rankings[sleeve], cursors[sleeve]
            while index < len(ranking) and ranking[index] in seen:
                index += 1
            cursors[sleeve] = index + 1
            if index < len(ranking):
                symbol = ranking[index]
                selected.append(symbol)
                seen.add(symbol)
                progressed = True
                if len(selected) == capacity:
                    break
        if not progressed:
            break

    aggregate = []
    for record in eligible:
        symbol = str(getattr(record, "symbol")).upper()
        known = [values[symbol] for values in scores.values() if symbol in values]
        aggregate.append((fmean(known) if known else 0.0, _tie(timestamp, CandidateSleeve.QUALITY, symbol), symbol))
    aggregate.sort(reverse=True)
    for _, _, symbol in aggregate:
        if len(selected) >= capacity:
            break
        if symbol not in seen:
            selected.append(symbol)
            seen.add(symbol)
    shadow = tuple(symbol for _, _, symbol in aggregate if symbol not in seen)[:shadow_limit]
    measured = tuple(selected) + shadow
    membership = tuple(
        (
            symbol,
            tuple(sleeve.value for sleeve in SLEEVES if symbol in scores[sleeve]),
        )
        for symbol in measured
    )
    score_rows = tuple(
        (
            symbol,
            tuple(
                (sleeve.value, round(scores[sleeve][symbol], 10))
                for sleeve in SLEEVES
                if symbol in scores[sleeve]
            ),
        )
        for symbol in measured
    )
    return PreselectionPlan(
        catalog_count=len(records),
        eligible_count=len(eligible),
        capacity=capacity,
        selected_symbols=tuple(selected),
        shadow_symbols=shadow,
        sleeve_rankings=tuple((sleeve.value, rankings[sleeve]) for sleeve in SLEEVES),
        sleeve_membership=membership,
        scores=score_rows,
        factor_coverage=tuple(
            (sleeve.value, len(scores[sleeve])) for sleeve in SLEEVES
        ),
        exclusions=tuple(exclusions),
    )


def build_cutoff_observations(
    plan: PreselectionPlan,
    *,
    asset_class: str,
    signals: Mapping[str, CatalogScreeningSignal],
    selected_prices: Mapping[str, float],
) -> tuple[CutoffObservation, ...]:
    memberships, score_map = dict(plan.sleeve_membership), dict(plan.scores)
    normalized_signals = {str(key).strip().upper(): value for key, value in signals.items()}
    result = []
    for cohort, symbols in (
        ("selected", plan.selected_symbols),
        ("below_cutoff", plan.shadow_symbols),
    ):
        for symbol in symbols:
            signal = normalized_signals.get(symbol)
            price = selected_prices.get(symbol) or (
                None if signal is None else signal.indicative_price
            )
            if signal is None or price is None:
                continue
            values = [value for _, value in score_map.get(symbol, ())]
            result.append(
                CutoffObservation(
                    asset_class=asset_class,
                    symbol=symbol,
                    cohort=cohort,
                    observed_at=signal.observed_at,
                    price=float(price),
                    sleeves=memberships.get(symbol, ()),
                    preselection_score=round(fmean(values) if values else 0.0, 10),
                )
            )
    return tuple(result)


def evaluate_cutoff_outcomes(
    prior_observations: Sequence[CutoffObservation],
    *,
    asset_class: str,
    current_prices: Mapping[str, float],
    as_of: datetime,
    minimum_age_days: int = 1,
) -> tuple[CutoffOutcomeEvaluation, ...]:
    timestamp = _aware(as_of)
    grouped = {}
    for item in prior_observations:
        if item.asset_class != asset_class or (timestamp - item.observed_at).days < minimum_age_days:
            continue
        current = current_prices.get(item.symbol)
        if current is None or current <= 0:
            continue
        grouped.setdefault(item.observed_at, {"selected": [], "below_cutoff": []})[
            item.cohort
        ].append(float(current) / item.price - 1)
    result = []
    for baseline, cohorts in sorted(grouped.items()):
        if not cohorts["selected"] or not cohorts["below_cutoff"]:
            continue
        selected_mean = fmean(cohorts["selected"])
        below_mean = fmean(cohorts["below_cutoff"])
        result.append(
            CutoffOutcomeEvaluation(
                asset_class=asset_class,
                baseline_at=baseline,
                evaluated_at=timestamp,
                selected_count=len(cohorts["selected"]),
                below_cutoff_count=len(cohorts["below_cutoff"]),
                selected_mean_return=round(selected_mean, 10),
                below_cutoff_mean_return=round(below_mean, 10),
                below_minus_selected=round(below_mean - selected_mean, 10),
            )
        )
    return tuple(result)


__all__ = [
    "CandidateSleeve",
    "CatalogScreeningSignal",
    "CutoffObservation",
    "CutoffOutcomeEvaluation",
    "PreselectionPlan",
    "build_cutoff_observations",
    "build_preselection_plan",
    "default_catalog_screening_signals",
    "evaluate_cutoff_outcomes",
]
