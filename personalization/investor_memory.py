"""Append-only investor memory for personal CIO behavior and lessons."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from urllib.parse import quote


class InvestorMemoryEventType(str, Enum):
    """Explicitly recorded investor-memory event categories."""

    DECISION_ACTION = "decision_action"
    RISK_PREFERENCE = "risk_preference"
    LESSON = "lesson"
    MISTAKE = "mistake"


class InvestorDecisionAction(str, Enum):
    """How the investor responded to a governed recommendation."""

    FOLLOWED = "followed"
    MODIFIED = "modified"
    DELAYED = "delayed"
    DECLINED = "declined"
    REVERSED = "reversed"
    NO_ACTION = "no_action"


class InvestorRiskLevel(str, Enum):
    """Investor-declared comfort with portfolio risk."""

    LOW = "low"
    MODERATE = "moderate"
    ELEVATED = "elevated"
    HIGH = "high"


class InvestorBehaviorTag(str, Enum):
    """User- or reviewer-recorded behavior patterns."""

    PERFORMANCE_CHASING = "performance_chasing"
    DELAYED_ACTION = "delayed_action"
    OVERSIZED_MOVE = "oversized_move"
    PREMATURE_EXIT = "premature_exit"
    IGNORED_RISK_REDUCTION = "ignored_risk_reduction"
    FREQUENT_OVERRIDE = "frequent_override"
    DISCIPLINED_PATIENCE = "disciplined_patience"
    FOLLOWED_PROCESS = "followed_process"
    APPROPRIATE_SIZING = "appropriate_sizing"


_PATTERN_LABELS = {
    InvestorBehaviorTag.PERFORMANCE_CHASING: "Chasing recent performance",
    InvestorBehaviorTag.DELAYED_ACTION: "Delaying portfolio decisions",
    InvestorBehaviorTag.OVERSIZED_MOVE: "Making changes larger than planned",
    InvestorBehaviorTag.PREMATURE_EXIT: "Exiting before the thesis resolved",
    InvestorBehaviorTag.IGNORED_RISK_REDUCTION: "Ignoring risk-reduction guidance",
    InvestorBehaviorTag.FREQUENT_OVERRIDE: "Frequently overriding the committee",
    InvestorBehaviorTag.DISCIPLINED_PATIENCE: "Allowing the process time to work",
    InvestorBehaviorTag.FOLLOWED_PROCESS: "Following the agreed decision process",
    InvestorBehaviorTag.APPROPRIATE_SIZING: "Keeping changes within planned size",
}


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _optional_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name=field_name)


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class InvestorMemoryEvent:
    """One immutable fact explicitly recorded about investor behavior."""

    identifier: str
    investor_identifier: str
    recorded_at: datetime
    event_type: InvestorMemoryEventType
    summary: str
    source_decision_identifier: str | None = None
    action: InvestorDecisionAction | None = None
    risk_level: InvestorRiskLevel | None = None
    behavior_tags: tuple[InvestorBehaviorTag, ...] = ()
    lesson: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("identifier", "investor_identifier", "summary"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.recorded_at, field_name="recorded_at")
        if not isinstance(self.event_type, InvestorMemoryEventType):
            raise TypeError("event_type must be an InvestorMemoryEventType")
        object.__setattr__(
            self,
            "source_decision_identifier",
            _optional_text(
                self.source_decision_identifier,
                field_name="source_decision_identifier",
            ),
        )
        object.__setattr__(
            self,
            "lesson",
            _optional_text(self.lesson, field_name="lesson"),
        )
        if self.action is not None and not isinstance(
            self.action,
            InvestorDecisionAction,
        ):
            raise TypeError("action must be an InvestorDecisionAction or None")
        if self.risk_level is not None and not isinstance(
            self.risk_level,
            InvestorRiskLevel,
        ):
            raise TypeError("risk_level must be an InvestorRiskLevel or None")
        if not isinstance(self.behavior_tags, tuple) or not all(
            isinstance(tag, InvestorBehaviorTag) for tag in self.behavior_tags
        ):
            raise TypeError(
                "behavior_tags must contain InvestorBehaviorTag values"
            )
        if len(self.behavior_tags) != len(set(self.behavior_tags)):
            raise ValueError("behavior_tags cannot contain duplicates")
        if (
            self.event_type is InvestorMemoryEventType.DECISION_ACTION
            and self.action is None
        ):
            raise ValueError("decision_action events require action")
        if (
            self.event_type is InvestorMemoryEventType.RISK_PREFERENCE
            and self.risk_level is None
        ):
            raise ValueError("risk_preference events require risk_level")
        if self.event_type is InvestorMemoryEventType.LESSON and self.lesson is None:
            raise ValueError("lesson events require lesson")
        if self.event_type is InvestorMemoryEventType.MISTAKE:
            if not self.behavior_tags:
                raise ValueError("mistake events require behavior_tags")
            if self.lesson is None:
                raise ValueError("mistake events require lesson")


@dataclass(frozen=True, slots=True)
class InvestorPattern:
    """A repeated, evidence-counted investor behavior pattern."""

    code: str
    label: str
    count: int
    recorded_as_mistake: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "code",
            _required_text(self.code, field_name="code"),
        )
        object.__setattr__(
            self,
            "label",
            _required_text(self.label, field_name="label"),
        )
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise TypeError("count must be an int")
        if self.count < 1:
            raise ValueError("count must be positive")
        if not isinstance(self.recorded_as_mistake, bool):
            raise TypeError("recorded_as_mistake must be a bool")


@dataclass(frozen=True, slots=True)
class InvestorActionTendency:
    action: InvestorDecisionAction
    count: int

    def __post_init__(self) -> None:
        if not isinstance(self.action, InvestorDecisionAction):
            raise TypeError("action must be an InvestorDecisionAction")
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise TypeError("count must be an int")
        if self.count < 1:
            raise ValueError("count must be positive")


@dataclass(frozen=True, slots=True)
class InvestorMemoryProfile:
    """Transparent summary built only from recorded investor-memory facts."""

    investor_identifier: str
    as_of: datetime | None
    total_events: int
    preferred_risk_level: InvestorRiskLevel | None
    recurring_patterns: tuple[InvestorPattern, ...]
    recurring_mistakes: tuple[InvestorPattern, ...]
    lessons: tuple[str, ...]
    action_tendencies: tuple[InvestorActionTendency, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "investor_identifier",
            _required_text(
                self.investor_identifier,
                field_name="investor_identifier",
            ),
        )
        if self.as_of is not None:
            _aware(self.as_of, field_name="as_of")
        if isinstance(self.total_events, bool) or not isinstance(
            self.total_events,
            int,
        ):
            raise TypeError("total_events must be an int")
        if self.total_events < 0:
            raise ValueError("total_events cannot be negative")
        if self.preferred_risk_level is not None and not isinstance(
            self.preferred_risk_level,
            InvestorRiskLevel,
        ):
            raise TypeError(
                "preferred_risk_level must be an InvestorRiskLevel or None"
            )


class SQLiteInvestorMemoryStore:
    """Append-only investor memory with an optional read-only mode."""

    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = bool(read_only)
        if self.path.exists() and self.path.is_dir():
            raise ValueError("investor memory path must be a file")
        if self.read_only:
            if not self.path.exists() or not self.path.is_file():
                raise FileNotFoundError(f"investor memory is unavailable: {self.path}")
        else:
            self.initialize()

    def initialize(self) -> None:
        if self.read_only:
            raise PermissionError("read-only investor memory cannot initialize")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS investor_memory_events (
                    identifier TEXT PRIMARY KEY,
                    investor_identifier TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    source_decision_identifier TEXT,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS investor_memory_investor_time
                ON investor_memory_events (
                    investor_identifier,
                    recorded_at DESC
                );

                CREATE TRIGGER IF NOT EXISTS investor_memory_prevent_update
                BEFORE UPDATE ON investor_memory_events
                BEGIN
                    SELECT RAISE(ABORT, 'investor memory is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS investor_memory_prevent_delete
                BEFORE DELETE ON investor_memory_events
                BEGIN
                    SELECT RAISE(ABORT, 'investor memory is append-only');
                END;
                """
            )

    def append(self, event: InvestorMemoryEvent) -> InvestorMemoryEvent:
        if self.read_only:
            raise PermissionError("read-only investor memory cannot append")
        if not isinstance(event, InvestorMemoryEvent):
            raise TypeError("event must be an InvestorMemoryEvent")
        payload = json.dumps(
            investor_memory_event_to_dict(event),
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT payload_json
                FROM investor_memory_events
                WHERE identifier = ?
                """,
                (event.identifier,),
            ).fetchone()
            if existing is not None:
                if existing["payload_json"] != payload:
                    raise ValueError(
                        "investor memory identifier already exists with different content"
                    )
                return event
            connection.execute(
                """
                INSERT INTO investor_memory_events (
                    identifier,
                    investor_identifier,
                    recorded_at,
                    event_type,
                    source_decision_identifier,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.identifier,
                    event.investor_identifier,
                    event.recorded_at.isoformat(),
                    event.event_type.value,
                    event.source_decision_identifier,
                    payload,
                ),
            )
        return event

    def events(
        self,
        investor_identifier: str,
        *,
        limit: int = 200,
    ) -> tuple[InvestorMemoryEvent, ...]:
        investor = _required_text(
            investor_identifier,
            field_name="investor_identifier",
        )
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an int")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM investor_memory_events
                WHERE investor_identifier = ?
                ORDER BY recorded_at DESC, identifier DESC
                LIMIT ?
                """,
                (investor, limit),
            ).fetchall()
        return tuple(
            investor_memory_event_from_dict(json.loads(row["payload_json"]))
            for row in rows
        )

    def profile(
        self,
        investor_identifier: str,
        *,
        recurring_threshold: int = 2,
        lesson_limit: int = 5,
    ) -> InvestorMemoryProfile:
        if isinstance(recurring_threshold, bool) or not isinstance(
            recurring_threshold,
            int,
        ):
            raise TypeError("recurring_threshold must be an int")
        if recurring_threshold < 2:
            raise ValueError("recurring_threshold must be at least 2")
        if isinstance(lesson_limit, bool) or not isinstance(lesson_limit, int):
            raise TypeError("lesson_limit must be an int")
        if lesson_limit < 1:
            raise ValueError("lesson_limit must be positive")
        events = self.events(investor_identifier, limit=1000)
        return build_investor_memory_profile(
            investor_identifier,
            events,
            recurring_threshold=recurring_threshold,
            lesson_limit=lesson_limit,
        )

    def count(self, investor_identifier: str | None = None) -> int:
        query = "SELECT COUNT(*) AS count FROM investor_memory_events"
        parameters: tuple[object, ...] = ()
        if investor_identifier is not None:
            query += " WHERE investor_identifier = ?"
            parameters = (
                _required_text(
                    investor_identifier,
                    field_name="investor_identifier",
                ),
            )
        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        return int(row["count"])

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            encoded = quote(str(self.path.resolve()), safe="/")
            connection = sqlite3.connect(
                f"file:{encoded}?mode=ro",
                uri=True,
                timeout=5.0,
            )
            connection.execute("PRAGMA query_only = ON")
        else:
            connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def build_investor_memory_profile(
    investor_identifier: str,
    events: tuple[InvestorMemoryEvent, ...],
    *,
    recurring_threshold: int = 2,
    lesson_limit: int = 5,
) -> InvestorMemoryProfile:
    """Aggregate explicit records without inferring unrecorded preferences."""

    investor = _required_text(
        investor_identifier,
        field_name="investor_identifier",
    )
    if not isinstance(events, tuple) or not all(
        isinstance(event, InvestorMemoryEvent) for event in events
    ):
        raise TypeError("events must contain InvestorMemoryEvent values")
    relevant = tuple(
        event for event in events if event.investor_identifier == investor
    )
    ordered = tuple(
        sorted(
            relevant,
            key=lambda event: (event.recorded_at, event.identifier),
            reverse=True,
        )
    )
    preferred_risk_level = next(
        (
            event.risk_level
            for event in ordered
            if event.event_type is InvestorMemoryEventType.RISK_PREFERENCE
            and event.risk_level is not None
        ),
        None,
    )
    all_tags = Counter(
        tag
        for event in ordered
        for tag in event.behavior_tags
    )
    mistake_tags = Counter(
        tag
        for event in ordered
        if event.event_type is InvestorMemoryEventType.MISTAKE
        for tag in event.behavior_tags
    )

    def patterns(counter: Counter[InvestorBehaviorTag]) -> tuple[InvestorPattern, ...]:
        return tuple(
            InvestorPattern(
                code=tag.value,
                label=_PATTERN_LABELS[tag],
                count=count,
                recorded_as_mistake=mistake_tags[tag] >= recurring_threshold,
            )
            for tag, count in sorted(
                counter.items(),
                key=lambda item: (-item[1], item[0].value),
            )
            if count >= recurring_threshold
        )

    lessons: list[str] = []
    seen_lessons: set[str] = set()
    for event in ordered:
        if event.lesson is None or event.lesson in seen_lessons:
            continue
        lessons.append(event.lesson)
        seen_lessons.add(event.lesson)
        if len(lessons) >= lesson_limit:
            break

    actions = Counter(
        event.action
        for event in ordered
        if event.action is not None
    )
    tendencies = tuple(
        InvestorActionTendency(action=action, count=count)
        for action, count in sorted(
            actions.items(),
            key=lambda item: (-item[1], item[0].value),
        )
    )
    return InvestorMemoryProfile(
        investor_identifier=investor,
        as_of=ordered[0].recorded_at if ordered else None,
        total_events=len(ordered),
        preferred_risk_level=preferred_risk_level,
        recurring_patterns=patterns(all_tags),
        recurring_mistakes=patterns(mistake_tags),
        lessons=tuple(lessons),
        action_tendencies=tendencies,
    )


def investor_memory_event_to_dict(event: InvestorMemoryEvent) -> dict[str, object]:
    if not isinstance(event, InvestorMemoryEvent):
        raise TypeError("event must be an InvestorMemoryEvent")
    return {
        "schema_version": "investor-memory-event.v1",
        "identifier": event.identifier,
        "investor_identifier": event.investor_identifier,
        "recorded_at": event.recorded_at.isoformat(),
        "event_type": event.event_type.value,
        "summary": event.summary,
        "source_decision_identifier": event.source_decision_identifier,
        "action": event.action.value if event.action is not None else None,
        "risk_level": (
            event.risk_level.value if event.risk_level is not None else None
        ),
        "behavior_tags": [tag.value for tag in event.behavior_tags],
        "lesson": event.lesson,
    }


def investor_memory_event_from_dict(
    payload: dict[str, object],
) -> InvestorMemoryEvent:
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dict")
    return InvestorMemoryEvent(
        identifier=str(payload["identifier"]),
        investor_identifier=str(payload["investor_identifier"]),
        recorded_at=datetime.fromisoformat(str(payload["recorded_at"])),
        event_type=InvestorMemoryEventType(str(payload["event_type"])),
        summary=str(payload["summary"]),
        source_decision_identifier=(
            None
            if payload.get("source_decision_identifier") is None
            else str(payload["source_decision_identifier"])
        ),
        action=(
            None
            if payload.get("action") is None
            else InvestorDecisionAction(str(payload["action"]))
        ),
        risk_level=(
            None
            if payload.get("risk_level") is None
            else InvestorRiskLevel(str(payload["risk_level"]))
        ),
        behavior_tags=tuple(
            InvestorBehaviorTag(str(value))
            for value in payload.get("behavior_tags", [])
        ),
        lesson=(
            None if payload.get("lesson") is None else str(payload["lesson"])
        ),
    )


def investor_memory_profile_to_dict(
    profile: InvestorMemoryProfile,
) -> dict[str, object]:
    if not isinstance(profile, InvestorMemoryProfile):
        raise TypeError("profile must be an InvestorMemoryProfile")
    return {
        "schema_version": "investor-memory.v1",
        "investor_identifier": profile.investor_identifier,
        "as_of": profile.as_of.isoformat() if profile.as_of else None,
        "total_events": profile.total_events,
        "preferred_risk_level": (
            profile.preferred_risk_level.value
            if profile.preferred_risk_level is not None
            else None
        ),
        "recurring_patterns": [
            {
                "code": pattern.code,
                "label": pattern.label,
                "count": pattern.count,
                "recorded_as_mistake": pattern.recorded_as_mistake,
            }
            for pattern in profile.recurring_patterns
        ],
        "recurring_mistakes": [
            {
                "code": pattern.code,
                "label": pattern.label,
                "count": pattern.count,
                "recorded_as_mistake": True,
            }
            for pattern in profile.recurring_mistakes
        ],
        "lessons": list(profile.lessons),
        "action_tendencies": [
            {
                "action": tendency.action.value,
                "count": tendency.count,
            }
            for tendency in profile.action_tendencies
        ],
        "memory_is_explicit": True,
    }


__all__ = [
    "InvestorActionTendency",
    "InvestorBehaviorTag",
    "InvestorDecisionAction",
    "InvestorMemoryEvent",
    "InvestorMemoryEventType",
    "InvestorMemoryProfile",
    "InvestorPattern",
    "InvestorRiskLevel",
    "SQLiteInvestorMemoryStore",
    "build_investor_memory_profile",
    "investor_memory_event_from_dict",
    "investor_memory_event_to_dict",
    "investor_memory_profile_to_dict",
]
