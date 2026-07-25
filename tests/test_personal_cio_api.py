"""API contract tests for personal CIO read surfaces."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from api import ApiSettings, create_app
from personalization import (
    InvestorBehaviorTag,
    InvestorDecisionAction,
    InvestorMemoryEvent,
    InvestorMemoryEventType,
    InvestorRiskLevel,
    SQLiteInvestorMemoryStore,
)
from tests.test_api import _create_portfolio_database


def _payload(as_of: str, score: int, evidence: float) -> dict:
    return {
        "schema_version": "daily-capital-intelligence.v1",
        "identifier": f"daily:{as_of}",
        "as_of": as_of,
        "generated_at": as_of,
        "status": "current",
        "score": {
            "score": score,
            "components": {
                "evidence_confidence": evidence,
                "committee_support": evidence,
                "committee_agreement": evidence,
            },
        },
    }


def _client(tmp_path) -> TestClient:
    snapshot_database = tmp_path / "daily.db"
    with sqlite3.connect(snapshot_database) as connection:
        connection.execute(
            """
            CREATE TABLE daily_intelligence_snapshots (
                identifier TEXT PRIMARY KEY,
                as_of TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL
            )
            """
        )
        for payload in (
            _payload("2026-01-27T12:00:00+00:00", 76, 0.72),
            _payload("2026-01-28T12:00:00+00:00", 82, 0.84),
        ):
            connection.execute(
                "INSERT INTO daily_intelligence_snapshots VALUES (?, ?, ?)",
                (
                    payload["identifier"],
                    payload["as_of"],
                    json.dumps(payload),
                ),
            )
    portfolio_database = tmp_path / "portfolio.db"
    _create_portfolio_database(portfolio_database)
    memory_database = tmp_path / "memory.db"
    memory = SQLiteInvestorMemoryStore(memory_database)
    memory.append(
        InvestorMemoryEvent(
            identifier="memory:1",
            investor_identifier="primary",
            recorded_at=datetime(2026, 1, 28, 13, tzinfo=timezone.utc),
            event_type=InvestorMemoryEventType.RISK_PREFERENCE,
            summary="Moderate risk preference.",
            risk_level=InvestorRiskLevel.MODERATE,
        )
    )
    for index in (2, 3):
        memory.append(
            InvestorMemoryEvent(
                identifier=f"memory:{index}",
                investor_identifier="primary",
                recorded_at=datetime(2026, 1, 28, 13 + index, tzinfo=timezone.utc),
                event_type=InvestorMemoryEventType.MISTAKE,
                summary="Delayed the decision.",
                action=InvestorDecisionAction.DELAYED,
                behavior_tags=(InvestorBehaviorTag.DELAYED_ACTION,),
                lesson="Use the agreed decision window.",
            )
        )
    settings = ApiSettings(
        snapshot_database=snapshot_database,
        portfolio_database=portfolio_database,
        investor_memory_database=memory_database,
        journal_database=tmp_path / "journal.db",
        replay_directory=None,
    )
    return TestClient(create_app(settings=settings))


def test_conviction_endpoint_returns_directional_history(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get("/v1/conviction/latest", params={"lookback": 7})

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "conviction-trend.v1"
    assert payload["direction"] == "rising"
    assert payload["capital_intelligence_score"] == 82
    assert len(payload["history"]) == 2


def test_investor_memory_endpoints_are_read_only_and_explicit(tmp_path) -> None:
    client = _client(tmp_path)

    profile = client.get("/v1/investor-memory/primary")
    events = client.get("/v1/investor-memory/primary/events")

    assert profile.status_code == 200
    payload = profile.json()
    assert payload["preferred_risk_level"] == "moderate"
    assert payload["recurring_mistakes"][0]["code"] == "delayed_action"
    assert payload["memory_is_explicit"] is True
    assert events.status_code == 200
    assert events.json()["total"] == 3
    assert client.post("/v1/investor-memory/primary", json={}).status_code == 405


def test_missing_investor_memory_returns_an_empty_profile(tmp_path) -> None:
    snapshot_database = tmp_path / "daily.db"
    with sqlite3.connect(snapshot_database) as connection:
        connection.execute(
            """
            CREATE TABLE daily_intelligence_snapshots (
                identifier TEXT PRIMARY KEY,
                as_of TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL
            )
            """
        )
    portfolio_database = tmp_path / "portfolio.db"
    _create_portfolio_database(portfolio_database)
    settings = ApiSettings(
        snapshot_database=snapshot_database,
        portfolio_database=portfolio_database,
        investor_memory_database=tmp_path / "missing-memory.db",
        journal_database=tmp_path / "journal.db",
        replay_directory=None,
    )
    client = TestClient(create_app(settings=settings))

    response = client.get("/v1/investor-memory/new-investor")

    assert response.status_code == 200
    assert response.json()["total_events"] == 0
    assert response.json()["preferred_risk_level"] is None


def test_conviction_lookback_is_bounded(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get("/v1/conviction/latest", params={"lookback": 31})

    assert response.status_code == 422
