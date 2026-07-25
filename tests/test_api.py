"""Contract tests for the read-only production API boundary."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from api import ApiSettings, create_app


def _snapshot_payload(
    *,
    identifier: str,
    as_of: str,
    decision_identifier: str,
    score: int,
    status: str = "current",
    replay_identifiers: tuple[str, ...] = (),
) -> dict:
    return {
        "schema_version": "daily-capital-intelligence.v1",
        "identifier": identifier,
        "as_of": as_of,
        "generated_at": as_of,
        "status": status,
        "score": {
            "schema_version": "capital-intelligence-score.v1",
            "identifier": f"score:{identifier}",
            "as_of": as_of,
            "score": score,
            "label": "Strong",
            "environment": "Constructive",
            "risk": "Moderate",
            "committee": "6–0 Favor Risk Assets",
            "portfolio_impact": "Consider holding more diversified risk assets.",
            "considerations": ["Review emerging markets."],
            "policy_version": "capital-intelligence-score.v1",
            "components": {"evidence_confidence": 0.9},
            "sources": {
                "regime_run": f"run:{as_of}",
                "decision": decision_identifier,
            },
        },
        "score_delta": None,
        "environment": {
            "schema_version": "market-environment-brief.v1",
            "as_of": as_of,
            "regime": "Goldilocks",
            "headline": "Constructive conditions remain the working view",
            "summary": "Liquidity is supportive and inflation is contained.",
            "portfolio": {
                "direction": "increase_risk",
                "impact": "Review whether the portfolio can take more risk.",
                "affected_exposures": ["diversified risk assets"],
            },
            "confidence": 0.9,
            "data_status": "Complete",
            "changed_materially": False,
            "alert_level": "silent",
            "should_alert": False,
            "review_conditions": [],
        },
        "decision_card": {
            "schema_version": "cio-decision-card.v1",
            "identifier": f"card:{decision_identifier}",
            "as_of": as_of,
            "headline": "Portfolio action approved",
            "decision": "Consider holding more diversified risk assets.",
            "why_now": "Goldilocks conditions support this view.",
            "regime": "Goldilocks",
            "evidence_confidence": 0.9,
            "data_status": "Complete",
            "committee_outcome": "approve",
            "portfolio": {
                "direction": "increase_risk",
                "explanation": "Review whether the portfolio can take more risk.",
                "affected_exposures": ["diversified risk assets"],
                "fit": None,
            },
            "key_evidence": [],
            "key_risks": [],
            "watch_conditions": [],
            "alert_level": "silent",
            "should_alert": False,
            "review_at": None,
        },
        "change": None,
        "change_summary": "No material change.",
        "changed_materially": False,
        "should_alert": False,
        "decision_replays": list(replay_identifiers),
        "sources": {
            "regime_run": f"run:{as_of}",
            "decision": decision_identifier,
        },
    }


def _create_snapshot_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE daily_intelligence_snapshots (
                identifier TEXT PRIMARY KEY,
                as_of TEXT NOT NULL UNIQUE,
                generated_at TEXT NOT NULL,
                score INTEGER NOT NULL,
                score_delta INTEGER,
                status TEXT NOT NULL,
                environment TEXT NOT NULL,
                risk TEXT NOT NULL,
                committee TEXT NOT NULL,
                portfolio_impact TEXT NOT NULL,
                changed_materially INTEGER NOT NULL,
                should_alert INTEGER NOT NULL,
                replay_identifiers_json TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            """
        )
        payloads = (
            _snapshot_payload(
                identifier="daily:2026-01-27",
                as_of="2026-01-27T12:00:00+00:00",
                decision_identifier="decision:1",
                score=78,
            ),
            _snapshot_payload(
                identifier="daily:2026-01-28",
                as_of="2026-01-28T12:00:00+00:00",
                decision_identifier="decision:2",
                score=82,
                status="stale",
                replay_identifiers=("decision-replay:2",),
            ),
        )
        for index, payload in enumerate(payloads):
            connection.execute(
                """
                INSERT INTO daily_intelligence_snapshots (
                    identifier, as_of, generated_at, score, score_delta,
                    status, environment, risk, committee, portfolio_impact,
                    changed_materially, should_alert,
                    replay_identifiers_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["identifier"],
                    payload["as_of"],
                    payload["generated_at"],
                    payload["score"]["score"],
                    None if index == 0 else 4,
                    payload["status"],
                    payload["score"]["environment"],
                    payload["score"]["risk"],
                    payload["score"]["committee"],
                    payload["score"]["portfolio_impact"],
                    0,
                    0,
                    json.dumps(payload["decision_replays"]),
                    json.dumps(payload, sort_keys=True),
                ),
            )


def _create_portfolio_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE mandates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                risk TEXT NOT NULL,
                starting_capital REAL NOT NULL,
                cash REAL NOT NULL,
                nav REAL NOT NULL
            );
            CREATE TABLE holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mandate_code TEXT NOT NULL,
                symbol TEXT NOT NULL,
                quantity REAL NOT NULL,
                average_cost REAL NOT NULL,
                current_price REAL NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                mandate_code TEXT NOT NULL,
                side TEXT NOT NULL,
                symbol TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                gross_amount REAL NOT NULL,
                rationale TEXT NOT NULL
            );
            CREATE TABLE portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                mandate_code TEXT NOT NULL,
                cash REAL NOT NULL,
                holdings_value REAL NOT NULL,
                nav REAL NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO mandates (
                code, name, risk, starting_capital, cash, nav
            ) VALUES ('GROWTH', 'Growth Mandate', 'moderate', 100000, 20000, 105000)
            """
        )
        connection.execute(
            """
            INSERT INTO holdings (
                mandate_code, symbol, quantity, average_cost,
                current_price, updated_at
            ) VALUES ('GROWTH', 'SPY', 100, 500, 510, '2026-01-28T12:00:00Z')
            """
        )


def _client(tmp_path: Path) -> TestClient:
    snapshot_database = tmp_path / "daily.db"
    portfolio_database = tmp_path / "portfolio.db"
    replay_directory = tmp_path / "replays"
    replay_directory.mkdir()
    _create_snapshot_database(snapshot_database)
    _create_portfolio_database(portfolio_database)
    replay = {
        "schema_version": "decision-replay.v1",
        "identifier": "decision-replay:2",
        "decision_identifier": "decision:2",
        "created_at": "2026-04-28T12:00:00+00:00",
        "timeline": [],
        "point_in_time_sources": ["decision:2"],
        "relative_return": 0.042,
        "lesson": "Liquidity improved before consensus.",
        "hindsight_is_separate": True,
    }
    (replay_directory / "decision-2.json").write_text(
        json.dumps(replay),
        encoding="utf-8",
    )
    settings = ApiSettings(
        snapshot_database=snapshot_database,
        portfolio_database=portfolio_database,
        journal_database=tmp_path / "journal.db",
        replay_directory=replay_directory,
        history_default_limit=30,
        history_max_limit=100,
    )
    return TestClient(create_app(settings=settings))


def test_health_and_readiness_distinguish_process_from_dependencies(tmp_path) -> None:
    client = _client(tmp_path)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    readiness = client.get("/ready")
    assert readiness.status_code == 200
    assert readiness.json()["ready"] is True
    assert readiness.json()["components"]["daily_snapshots"]["ready"] is True
    assert readiness.json()["components"]["institutional_journal"]["required"] is False


def test_latest_preserves_the_existing_schema_and_honest_status(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get("/v1/daily/latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "daily-capital-intelligence.v1"
    assert payload["score"]["score"] == 82
    assert payload["status"] == "stale"
    assert payload["sources"]["decision"] == "decision:2"


def test_history_is_bounded_and_paginated(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get("/v1/daily/history", params={"limit": 1, "offset": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["items"][0]["identifier"] == "daily:2026-01-27"

    too_large = client.get("/v1/daily/history", params={"limit": 101})
    assert too_large.status_code == 422


def test_environment_and_decision_share_canonical_sources(tmp_path) -> None:
    client = _client(tmp_path)

    environment = client.get("/v1/environment/latest")
    decision = client.get("/v1/decisions/decision:2")

    assert environment.status_code == 200
    assert decision.status_code == 200
    assert environment.json()["sources"] == decision.json()["sources"]
    assert decision.json()["decision_card"]["identifier"] == "card:decision:2"
    assert client.get("/v1/decisions/unknown").status_code == 404


def test_replays_expose_references_and_read_only_artifacts(tmp_path) -> None:
    client = _client(tmp_path)

    listing = client.get("/v1/replays")
    assert listing.status_code == 200
    assert listing.json()["items"] == [
        {
            "identifier": "decision-replay:2",
            "available": True,
            "created_at": "2026-04-28T12:00:00+00:00",
            "relative_return": 0.042,
            "lesson": "Liquidity improved before consensus.",
        }
    ]

    replay = client.get("/v1/replays/decision-replay:2")
    assert replay.status_code == 200
    assert replay.json()["hindsight_is_separate"] is True
    assert client.get("/v1/replays/missing").status_code == 404


def test_portfolio_routes_are_read_only(tmp_path) -> None:
    client = _client(tmp_path)

    listing = client.get("/v1/portfolios")
    assert listing.status_code == 200
    assert listing.json()["items"][0]["code"] == "GROWTH"

    portfolio = client.get("/v1/portfolios/growth")
    assert portfolio.status_code == 200
    assert portfolio.json()["total_return"] == 0.05
    assert portfolio.json()["holdings"][0]["symbol"] == "SPY"

    assert client.post("/v1/portfolios", json={}).status_code == 405
    assert client.delete("/v1/portfolios/GROWTH").status_code == 405


def test_missing_required_store_returns_503_without_affecting_health(tmp_path) -> None:
    portfolio_database = tmp_path / "portfolio.db"
    _create_portfolio_database(portfolio_database)
    settings = ApiSettings(
        snapshot_database=tmp_path / "missing.db",
        portfolio_database=portfolio_database,
        journal_database=tmp_path / "journal.db",
        replay_directory=None,
    )
    client = TestClient(create_app(settings=settings))

    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 503
    latest = client.get("/v1/daily/latest")
    assert latest.status_code == 503


def test_openapi_contract_is_deterministic_and_has_no_mutation_routes(tmp_path) -> None:
    client = _client(tmp_path)

    first = client.get("/openapi.json")
    second = client.get("/openapi.json")

    assert first.status_code == 200
    assert first.json() == second.json()
    paths = first.json()["paths"]
    for path, operations in paths.items():
        assert not ({"post", "put", "patch", "delete"} & set(operations)), path


def test_conflicting_replay_identifiers_return_409(tmp_path) -> None:
    snapshot_database = tmp_path / "daily.db"
    portfolio_database = tmp_path / "portfolio.db"
    replay_directory = tmp_path / "replays"
    replay_directory.mkdir()
    _create_snapshot_database(snapshot_database)
    _create_portfolio_database(portfolio_database)
    first = {
        "identifier": "decision-replay:duplicate",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    second = {
        "identifier": "decision-replay:duplicate",
        "created_at": "2026-01-02T00:00:00+00:00",
    }
    (replay_directory / "first.json").write_text(
        json.dumps(first),
        encoding="utf-8",
    )
    (replay_directory / "second.json").write_text(
        json.dumps(second),
        encoding="utf-8",
    )
    settings = ApiSettings(
        snapshot_database=snapshot_database,
        portfolio_database=portfolio_database,
        journal_database=tmp_path / "journal.db",
        replay_directory=replay_directory,
    )
    client = TestClient(create_app(settings=settings))

    response = client.get("/v1/replays")
    assert response.status_code == 409
    assert "conflicting replay identifier" in response.json()["detail"]
