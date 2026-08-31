from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from operations.shadow_opportunity_ledger import (
    record_capability_blocked_opportunities,
)


def test_records_research_only_and_suspended_transitions_without_authority(tmp_path):
    database = tmp_path / "shadow.db"
    observed_at = datetime(2026, 8, 30, 17, 0, tzinfo=timezone.utc)
    transitions = (
        {
            "instrument_identifier": "instrument:a",
            "action": "research_only",
            "certification_identifier": None,
            "blockers": ["execution_model"],
        },
        {
            "instrument_identifier": "instrument:b",
            "action": "suspended",
            "certification_identifier": "cert:b",
            "blockers": ["liquidity"],
        },
        {
            "instrument_identifier": "instrument:c",
            "action": "certified",
            "certification_identifier": "cert:c",
            "blockers": [],
        },
    )

    recorded = record_capability_blocked_opportunities(
        database_path=database,
        publication_identifier="universe:1",
        screening_cycle_identifier="screening:1",
        observed_at=observed_at,
        transitions=transitions,
    )

    assert {item.instrument_identifier for item in recorded} == {
        "instrument:a",
        "instrument:b",
    }
    assert all(item.canonical_execution_authority is False for item in recorded)
    assert all(item.real_money_authorized is False for item in recorded)

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT instrument_identifier,
                   paper_only,
                   canonical_execution_authority,
                   real_money_authorized
            FROM shadow_opportunity_observations
            ORDER BY instrument_identifier
            """
        ).fetchall()

    assert rows == [
        ("instrument:a", 1, 0, 0),
        ("instrument:b", 1, 0, 0),
    ]


def test_shadow_observation_is_idempotent_for_same_capability_boundary(tmp_path):
    database = tmp_path / "shadow.db"
    observed_at = datetime(2026, 8, 30, 17, 0, tzinfo=timezone.utc)
    transition = {
        "instrument_identifier": "instrument:a",
        "action": "research_only",
        "certification_identifier": None,
        "blockers": ["custody_settlement"],
    }

    first = record_capability_blocked_opportunities(
        database_path=database,
        publication_identifier="universe:1",
        screening_cycle_identifier="screening:1",
        observed_at=observed_at,
        transitions=(transition,),
    )
    second = record_capability_blocked_opportunities(
        database_path=database,
        publication_identifier="universe:1",
        screening_cycle_identifier="screening:1",
        observed_at=observed_at,
        transitions=(transition,),
    )

    assert len(first) == 1
    assert second == ()
