"""Append-only learning ledger for qualified opportunities lacking paper capability.

This ledger is deliberately non-authoritative. It records qualified instruments that
reach the production capability boundary but cannot create or increase canonical paper
exposure because required capability proof is missing or suspended. Recording a row
never creates a CIO action, construction intent, paper order, fill, portfolio mutation,
or real-money authority.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "shadow-opportunity-ledger.v1"
_NON_EXECUTABLE_ACTIONS = frozenset({"research_only", "suspended"})


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("observed_at must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _text(value: object) -> str:
    return str(value or "").strip()


def _transition_payload(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        payload = converter()
        if isinstance(payload, Mapping):
            return dict(payload)
    raise TypeError("shadow transition must expose a mapping payload")


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )


@dataclass(frozen=True, slots=True)
class ShadowOpportunityObservation:
    identifier: str
    observed_at: datetime
    publication_identifier: str
    screening_cycle_identifier: str
    instrument_identifier: str
    capability_action: str
    blockers: tuple[str, ...]
    transition_payload: Mapping[str, Any]
    paper_only: bool = True
    canonical_execution_authority: bool = False
    real_money_authorized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "identifier": self.identifier,
            "observed_at": self.observed_at.isoformat(),
            "publication_identifier": self.publication_identifier,
            "screening_cycle_identifier": self.screening_cycle_identifier,
            "instrument_identifier": self.instrument_identifier,
            "capability_action": self.capability_action,
            "blockers": list(self.blockers),
            "transition_payload": dict(self.transition_payload),
            "paper_only": True,
            "canonical_execution_authority": False,
            "real_money_authorized": False,
        }


class SQLiteShadowOpportunityLedger:
    """Persist immutable capability-blocked opportunity observations."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS shadow_opportunity_observations (
                    identifier TEXT PRIMARY KEY,
                    observed_at TEXT NOT NULL,
                    publication_identifier TEXT NOT NULL,
                    screening_cycle_identifier TEXT NOT NULL,
                    instrument_identifier TEXT NOT NULL,
                    capability_action TEXT NOT NULL,
                    blockers_json TEXT NOT NULL,
                    transition_json TEXT NOT NULL,
                    paper_only INTEGER NOT NULL CHECK (paper_only = 1),
                    canonical_execution_authority INTEGER NOT NULL
                        CHECK (canonical_execution_authority = 0),
                    real_money_authorized INTEGER NOT NULL
                        CHECK (real_money_authorized = 0)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_shadow_opportunity_observed_at
                ON shadow_opportunity_observations(observed_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_shadow_opportunity_instrument
                ON shadow_opportunity_observations(instrument_identifier, observed_at)
                """
            )

    def append(self, observation: ShadowOpportunityObservation) -> bool:
        if not isinstance(observation, ShadowOpportunityObservation):
            raise TypeError("observation must be ShadowOpportunityObservation")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO shadow_opportunity_observations (
                    identifier,
                    observed_at,
                    publication_identifier,
                    screening_cycle_identifier,
                    instrument_identifier,
                    capability_action,
                    blockers_json,
                    transition_json,
                    paper_only,
                    canonical_execution_authority,
                    real_money_authorized
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 0)
                """,
                (
                    observation.identifier,
                    observation.observed_at.isoformat(),
                    observation.publication_identifier,
                    observation.screening_cycle_identifier,
                    observation.instrument_identifier,
                    observation.capability_action,
                    _canonical_json({"blockers": list(observation.blockers)}),
                    _canonical_json(observation.transition_payload),
                ),
            )
            return cursor.rowcount == 1


def record_capability_blocked_opportunities(
    *,
    database_path: str | Path,
    publication_identifier: str,
    screening_cycle_identifier: str,
    observed_at: datetime,
    transitions: Sequence[object],
) -> tuple[ShadowOpportunityObservation, ...]:
    """Record qualified candidates that cannot currently obtain paper authority."""

    timestamp = _aware(observed_at)
    publication = _text(publication_identifier)
    screening_cycle = _text(screening_cycle_identifier)
    if not publication or not screening_cycle:
        raise ValueError("publication and screening cycle identifiers are required")
    ledger = SQLiteShadowOpportunityLedger(database_path)
    recorded: list[ShadowOpportunityObservation] = []
    for raw_transition in transitions:
        payload = _transition_payload(raw_transition)
        action = _text(payload.get("action")).lower()
        if action not in _NON_EXECUTABLE_ACTIONS:
            continue
        instrument_identifier = _text(payload.get("instrument_identifier"))
        if not instrument_identifier:
            continue
        blockers = tuple(
            dict.fromkeys(
                _text(item)
                for item in (payload.get("blockers", ()) or ())
                if _text(item)
            )
        )
        identity_material = {
            "publication_identifier": publication,
            "screening_cycle_identifier": screening_cycle,
            "instrument_identifier": instrument_identifier,
            "capability_action": action,
            "blockers": blockers,
        }
        digest = hashlib.sha256(
            _canonical_json(identity_material).encode("utf-8")
        ).hexdigest()
        observation = ShadowOpportunityObservation(
            identifier=f"shadow-opportunity:{digest}",
            observed_at=timestamp,
            publication_identifier=publication,
            screening_cycle_identifier=screening_cycle,
            instrument_identifier=instrument_identifier,
            capability_action=action,
            blockers=blockers,
            transition_payload=payload,
        )
        if ledger.append(observation):
            recorded.append(observation)
    return tuple(recorded)


__all__ = [
    "SCHEMA_VERSION",
    "SQLiteShadowOpportunityLedger",
    "ShadowOpportunityObservation",
    "record_capability_blocked_opportunities",
]
