"""Canonical CIO API contracts and isolation of retired personal surfaces."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from api import ApiSettings, create_app
from cio.persistence import CIOJournalEventType, SQLiteCIOJournal
from tests.test_api import _create_portfolio_database


AS_OF = datetime(2026, 7, 26, 17, tzinfo=timezone.utc)


def _briefing(identifier: str, status: str = "current") -> dict[str, object]:
    return {
        "identifier": identifier,
        "as_of": AS_OF.isoformat(),
        "status": status,
        "what_changed": "A qualified use of capital improved relative to cash and holdings.",
        "why_it_matters": "Expected portfolio return improved after costs.",
        "opportunity_or_risk": "QUAL is the strongest available use of capital.",
        "portfolio_decision": "Buy QUAL to an 8% target weight.",
        "confidence": 0.82,
        "evidence_that_changes_conclusion": ["Expected return falls below cash"],
        "material_developments": ["Opportunity edge increased"],
        "candidate_identifier": "candidate:qual",
        "decision_identifier": "decision:qual",
        "construction_status": "feasible",
        "thesis_identifiers": ["thesis:qual"],
        "cycle_identifier": "cycle:qual",
        "code_version": "test-release",
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
        payload = {
            "schema_version": "daily-capital-intelligence.v1",
            "identifier": "legacy-diagnostic:1",
            "as_of": AS_OF.isoformat(),
            "generated_at": AS_OF.isoformat(),
            "status": "current",
            "score": {"score": 75},
        }
        connection.execute(
            "INSERT INTO daily_intelligence_snapshots VALUES (?, ?, ?)",
            (payload["identifier"], payload["as_of"], json.dumps(payload)),
        )
    portfolio_database = tmp_path / "portfolio.db"
    _create_portfolio_database(portfolio_database)
    journal_database = tmp_path / "journal.db"
    journal = SQLiteCIOJournal(journal_database)
    journal.append(
        event_type=CIOJournalEventType.DAILY_CIO_BRIEFING,
        aggregate_identifier="cycle:qual",
        occurred_at=AS_OF,
        payload=_briefing("daily-cio:qual"),
        schema_version="daily-cio-briefing.v1",
        event_identifier="event:daily-cio:qual",
    )
    journal.append(
        event_type=CIOJournalEventType.CIO_DECISION,
        aggregate_identifier="candidate:qual",
        occurred_at=AS_OF,
        payload={"identifier": "decision:qual", "action": "buy"},
        schema_version="cio-decision.v1",
        event_identifier="event:decision:qual",
    )
    journal.append(
        event_type=CIOJournalEventType.PORTFOLIO_CONSTRUCTION,
        aggregate_identifier="construction:qual",
        occurred_at=AS_OF,
        payload={"identifier": "construction:qual", "status": "feasible"},
        schema_version="portfolio-construction.v1",
        event_identifier="event:construction:qual",
    )
    journal.append(
        event_type=CIOJournalEventType.DECISION_EVIDENCE_SNAPSHOT,
        aggregate_identifier="decision:qual",
        occurred_at=AS_OF,
        payload={"identifier": "evidence:qual", "decision_identifier": "decision:qual"},
        schema_version="decision-evidence-snapshot.v1",
        event_identifier="event:evidence:qual",
    )
    journal.append(
        event_type=CIOJournalEventType.THESIS_SNAPSHOT,
        aggregate_identifier="thesis:qual",
        occurred_at=AS_OF,
        payload={"identifier": "thesis:qual", "state": "active"},
        schema_version="living-thesis.v1",
        event_identifier="event:thesis:qual",
    )
    journal.append(
        event_type=CIOJournalEventType.DECISION_EVALUATION,
        aggregate_identifier="decision:qual",
        occurred_at=AS_OF,
        payload={
            "identifier": "evaluation:qual",
            "decision_identifier": "decision:qual",
            "process_verdict": "disciplined",
            "outcome": "value_added",
        },
        schema_version="decision-evaluation.v1",
        event_identifier="event:evaluation:qual",
    )
    settings = ApiSettings(
        snapshot_database=snapshot_database,
        portfolio_database=portfolio_database,
        investor_memory_database=tmp_path / "isolated-memory.db",
        journal_database=journal_database,
        replay_directory=None,
    )
    return TestClient(create_app(settings=settings))


def test_latest_cio_briefing_is_the_primary_read_surface(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get("/v1/cio/latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["identifier"] == "daily-cio:qual"
    assert payload["portfolio_decision"].startswith("Buy QUAL")
    assert payload["confidence"] == 0.82
    assert payload["journal"]["event_type"] == "daily_cio_briefing"
    assert len(payload["journal"]["content_hash"]) == 64


def test_cio_history_and_supporting_audit_surfaces_are_read_only(tmp_path) -> None:
    client = _client(tmp_path)

    history = client.get("/v1/cio/history")
    decision = client.get("/v1/cio/decisions/latest")
    construction = client.get("/v1/cio/construction/latest")
    evidence = client.get("/v1/cio/evidence/latest")
    evaluation = client.get("/v1/cio/evaluations/latest")
    theses = client.get("/v1/cio/theses")

    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert decision.json()["identifier"] == "decision:qual"
    assert construction.json()["status"] == "feasible"
    assert evidence.json()["decision_identifier"] == "decision:qual"
    assert evaluation.json()["process_verdict"] == "disciplined"
    assert theses.json()["items"][0]["identifier"] == "thesis:qual"
    assert client.post("/v1/cio/latest", json={}).status_code == 405


def test_process_endpoint_states_the_complete_governing_loop(tmp_path) -> None:
    payload = _client(tmp_path).get("/v1/cio/process").json()

    rule = payload["governing_rule"]
    assert "all other available uses of capital" in rule
    assert "portfolio level" in rule
    assert "explicit thesis" in rule
    assert "exact evidence available" in rule
    assert payload["authority"]["cio"].startswith("issues the only")


def test_personal_cio_conviction_and_investor_memory_routes_are_isolated(tmp_path) -> None:
    client = _client(tmp_path)

    assert client.get("/v1/conviction/latest").status_code == 404
    assert client.get("/v1/investor-memory/primary").status_code == 404
    assert client.get("/v1/investor-memory/primary/events").status_code == 404

    paths = client.get("/openapi.json").json()["paths"]
    assert "/v1/conviction/latest" not in paths
    assert "/v1/investor-memory/{investor_identifier}" not in paths
    assert "personal CIO" not in json.dumps(client.get("/openapi.json").json())
