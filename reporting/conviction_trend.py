"""Conviction trends derived from canonical daily intelligence history."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isclose
from pathlib import Path
from urllib.parse import quote


class ConvictionDirection(str, Enum):
    RISING = "rising"
    STEADY = "steady"
    FALLING = "falling"
    UNAVAILABLE = "unavailable"


def _bounded(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0")
    return round(normalized, 6)


@dataclass(frozen=True, slots=True)
class ConvictionTrendPolicy:
    """Versioned conviction weights and material-move threshold."""

    version: str = "conviction-trend.v1"
    evidence_confidence_weight: float = 0.50
    committee_support_weight: float = 0.30
    committee_agreement_weight: float = 0.20
    material_change_points: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version cannot be empty")
        fields = (
            "evidence_confidence_weight",
            "committee_support_weight",
            "committee_agreement_weight",
        )
        for field_name in fields:
            object.__setattr__(
                self,
                field_name,
                _bounded(getattr(self, field_name), field_name=field_name),
            )
        if not isclose(
            sum(getattr(self, field_name) for field_name in fields),
            1.0,
            abs_tol=1e-6,
        ):
            raise ValueError("conviction trend weights must sum to 1.0")
        if isinstance(self.material_change_points, bool) or not isinstance(
            self.material_change_points,
            int,
        ):
            raise TypeError("material_change_points must be an int")
        if not 1 <= self.material_change_points <= 25:
            raise ValueError("material_change_points must be between 1 and 25")


@dataclass(frozen=True, slots=True)
class ConvictionObservation:
    as_of: datetime
    conviction: int
    capital_intelligence_score: int
    evidence_confidence: float
    committee_support: float
    committee_agreement: float

    def __post_init__(self) -> None:
        if not isinstance(self.as_of, datetime):
            raise TypeError("as_of must be a datetime")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        for field_name in ("conviction", "capital_intelligence_score"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an int")
            if not 0 <= value <= 100:
                raise ValueError(f"{field_name} must be between 0 and 100")
        for field_name in (
            "evidence_confidence",
            "committee_support",
            "committee_agreement",
        ):
            object.__setattr__(
                self,
                field_name,
                _bounded(getattr(self, field_name), field_name=field_name),
            )


@dataclass(frozen=True, slots=True)
class ConvictionDriver:
    component: str
    change_points: int

    def __post_init__(self) -> None:
        if not isinstance(self.component, str) or not self.component.strip():
            raise ValueError("component cannot be empty")
        if isinstance(self.change_points, bool) or not isinstance(
            self.change_points,
            int,
        ):
            raise TypeError("change_points must be an int")


@dataclass(frozen=True, slots=True)
class ConvictionTrend:
    """Direction and explanation for confidence over time."""

    as_of: datetime | None
    current: int | None
    previous: int | None
    change_points: int | None
    net_change_points: int | None
    direction: ConvictionDirection
    streak: int
    observations: tuple[ConvictionObservation, ...]
    drivers: tuple[ConvictionDriver, ...]
    capital_intelligence_score: int | None
    score_change_points: int | None
    explanation: str
    policy_version: str

    def __post_init__(self) -> None:
        if self.as_of is not None:
            if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
                raise ValueError("as_of must be timezone-aware")
        if not isinstance(self.direction, ConvictionDirection):
            raise TypeError("direction must be a ConvictionDirection")
        if isinstance(self.streak, bool) or not isinstance(self.streak, int):
            raise TypeError("streak must be an int")
        if self.streak < 0:
            raise ValueError("streak cannot be negative")
        if not isinstance(self.explanation, str) or not self.explanation.strip():
            raise ValueError("explanation cannot be empty")
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("policy_version cannot be empty")


_COMPONENT_LABELS = {
    "evidence_confidence": "evidence confidence",
    "committee_support": "committee support",
    "committee_agreement": "committee agreement",
}


def conviction_observation_from_daily_payload(
    payload: dict[str, object],
    *,
    policy: ConvictionTrendPolicy | None = None,
) -> ConvictionObservation:
    """Extract one conviction observation from a v1 daily payload."""

    if not isinstance(payload, dict):
        raise TypeError("payload must be a dict")
    if payload.get("schema_version") != "daily-capital-intelligence.v1":
        raise ValueError("payload must use daily-capital-intelligence.v1")
    score = payload.get("score")
    if not isinstance(score, dict):
        raise ValueError("daily payload is missing score")
    components = score.get("components")
    if not isinstance(components, dict):
        raise ValueError("daily score is missing components")
    resolved = policy or ConvictionTrendPolicy()
    evidence_confidence = _bounded(
        components.get("evidence_confidence"),
        field_name="evidence_confidence",
    )
    committee_support = _bounded(
        components.get("committee_support", 0.0),
        field_name="committee_support",
    )
    committee_agreement = _bounded(
        components.get("committee_agreement", 0.0),
        field_name="committee_agreement",
    )
    conviction = round(
        100
        * (
            evidence_confidence * resolved.evidence_confidence_weight
            + committee_support * resolved.committee_support_weight
            + committee_agreement * resolved.committee_agreement_weight
        )
    )
    raw_score = score.get("score")
    if isinstance(raw_score, bool) or not isinstance(raw_score, int):
        raise ValueError("daily score must be an int")
    return ConvictionObservation(
        as_of=datetime.fromisoformat(str(payload["as_of"])),
        conviction=conviction,
        capital_intelligence_score=raw_score,
        evidence_confidence=evidence_confidence,
        committee_support=committee_support,
        committee_agreement=committee_agreement,
    )


def build_conviction_trend(
    payloads: tuple[dict[str, object], ...],
    *,
    lookback: int = 7,
    policy: ConvictionTrendPolicy | None = None,
) -> ConvictionTrend:
    """Build a transparent trend from ordered canonical daily snapshots."""

    if not isinstance(payloads, tuple) or not all(
        isinstance(payload, dict) for payload in payloads
    ):
        raise TypeError("payloads must contain dict values")
    if isinstance(lookback, bool) or not isinstance(lookback, int):
        raise TypeError("lookback must be an int")
    if not 2 <= lookback <= 90:
        raise ValueError("lookback must be between 2 and 90")
    resolved = policy or ConvictionTrendPolicy()
    observations_by_time: dict[datetime, ConvictionObservation] = {}
    for payload in payloads:
        observation = conviction_observation_from_daily_payload(
            payload,
            policy=resolved,
        )
        observations_by_time[observation.as_of] = observation
    observations = tuple(
        sorted(observations_by_time.values(), key=lambda item: item.as_of)
    )[-lookback:]
    if not observations:
        return ConvictionTrend(
            as_of=None,
            current=None,
            previous=None,
            change_points=None,
            net_change_points=None,
            direction=ConvictionDirection.UNAVAILABLE,
            streak=0,
            observations=(),
            drivers=(),
            capital_intelligence_score=None,
            score_change_points=None,
            explanation="No conviction history is available yet.",
            policy_version=resolved.version,
        )

    current_observation = observations[-1]
    if len(observations) == 1:
        return ConvictionTrend(
            as_of=current_observation.as_of,
            current=current_observation.conviction,
            previous=None,
            change_points=None,
            net_change_points=None,
            direction=ConvictionDirection.STEADY,
            streak=1,
            observations=observations,
            drivers=(),
            capital_intelligence_score=(
                current_observation.capital_intelligence_score
            ),
            score_change_points=None,
            explanation=(
                "This is the first conviction observation; no prior trend is available."
            ),
            policy_version=resolved.version,
        )

    previous_observation = observations[-2]
    change = current_observation.conviction - previous_observation.conviction
    threshold = resolved.material_change_points
    direction = _direction(change, threshold=threshold)
    net_change = current_observation.conviction - observations[0].conviction
    score_change = (
        current_observation.capital_intelligence_score
        - previous_observation.capital_intelligence_score
    )
    driver_changes = {
        component: round(
            100
            * (
                getattr(current_observation, component)
                - getattr(previous_observation, component)
            )
        )
        for component in _COMPONENT_LABELS
    }
    drivers = tuple(
        ConvictionDriver(
            component=_COMPONENT_LABELS[component],
            change_points=points,
        )
        for component, points in sorted(
            driver_changes.items(),
            key=lambda item: (-abs(item[1]), item[0]),
        )
        if abs(points) >= threshold
    )[:2]
    streak = _direction_streak(observations, threshold=threshold)
    if direction is ConvictionDirection.RISING:
        explanation = f"Conviction rose {change} points from the prior observation."
    elif direction is ConvictionDirection.FALLING:
        explanation = (
            f"Conviction fell {abs(change)} points from the prior observation."
        )
    else:
        explanation = "Conviction is broadly unchanged from the prior observation."
    if drivers:
        driver_text = ", ".join(
            f"{driver.component} {driver.change_points:+d}"
            for driver in drivers
        )
        explanation = f"{explanation} Main drivers: {driver_text}."
    return ConvictionTrend(
        as_of=current_observation.as_of,
        current=current_observation.conviction,
        previous=previous_observation.conviction,
        change_points=change,
        net_change_points=net_change,
        direction=direction,
        streak=streak,
        observations=observations,
        drivers=drivers,
        capital_intelligence_score=(
            current_observation.capital_intelligence_score
        ),
        score_change_points=score_change,
        explanation=explanation,
        policy_version=resolved.version,
    )


def load_daily_payload_history(
    path: str | Path,
    *,
    limit: int = 30,
) -> tuple[dict[str, object], ...]:
    """Read canonical daily payloads without mutating the snapshot store."""

    database = Path(path)
    if not database.exists() or not database.is_file():
        return ()
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an int")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    encoded = quote(str(database.resolve()), safe="/")
    connection = sqlite3.connect(
        f"file:{encoded}?mode=ro",
        uri=True,
        timeout=5.0,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    try:
        rows = connection.execute(
            """
            SELECT payload_json
            FROM daily_intelligence_snapshots
            ORDER BY as_of DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    except sqlite3.Error:
        return ()
    finally:
        connection.close()
    return tuple(
        reversed(
            [json.loads(row["payload_json"]) for row in rows]
        )
    )


def build_conviction_trend_from_store(
    path: str | Path,
    *,
    lookback: int = 7,
    policy: ConvictionTrendPolicy | None = None,
) -> ConvictionTrend:
    payloads = load_daily_payload_history(path, limit=max(lookback, 2))
    return build_conviction_trend(
        payloads,
        lookback=lookback,
        policy=policy,
    )


def conviction_trend_to_dict(trend: ConvictionTrend) -> dict[str, object]:
    if not isinstance(trend, ConvictionTrend):
        raise TypeError("trend must be a ConvictionTrend")
    return {
        "schema_version": "conviction-trend.v1",
        "as_of": trend.as_of.isoformat() if trend.as_of else None,
        "current": trend.current,
        "previous": trend.previous,
        "change_points": trend.change_points,
        "net_change_points": trend.net_change_points,
        "direction": trend.direction.value,
        "streak": trend.streak,
        "capital_intelligence_score": trend.capital_intelligence_score,
        "score_change_points": trend.score_change_points,
        "drivers": [
            {
                "component": driver.component,
                "change_points": driver.change_points,
            }
            for driver in trend.drivers
        ],
        "history": [
            {
                "as_of": observation.as_of.isoformat(),
                "conviction": observation.conviction,
                "capital_intelligence_score": (
                    observation.capital_intelligence_score
                ),
            }
            for observation in trend.observations
        ],
        "explanation": trend.explanation,
        "policy_version": trend.policy_version,
    }


def _direction(change: int, *, threshold: int) -> ConvictionDirection:
    if change >= threshold:
        return ConvictionDirection.RISING
    if change <= -threshold:
        return ConvictionDirection.FALLING
    return ConvictionDirection.STEADY


def _direction_streak(
    observations: tuple[ConvictionObservation, ...],
    *,
    threshold: int,
) -> int:
    if len(observations) < 2:
        return len(observations)
    latest = _direction(
        observations[-1].conviction - observations[-2].conviction,
        threshold=threshold,
    )
    streak = 1
    for index in range(len(observations) - 2, 0, -1):
        direction = _direction(
            observations[index].conviction
            - observations[index - 1].conviction,
            threshold=threshold,
        )
        if direction is not latest:
            break
        streak += 1
    return streak


__all__ = [
    "ConvictionDirection",
    "ConvictionDriver",
    "ConvictionObservation",
    "ConvictionTrend",
    "ConvictionTrendPolicy",
    "build_conviction_trend",
    "build_conviction_trend_from_store",
    "conviction_observation_from_daily_payload",
    "conviction_trend_to_dict",
    "load_daily_payload_history",
]
