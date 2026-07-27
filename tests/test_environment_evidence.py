"""Point-in-time Environment evidence and API-boundary tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import ApiSettings, create_app
from application import (
    CertifiedDecisionEnvironmentSnapshot,
    EnvironmentEvidenceError,
    SQLiteEnvironmentEvidenceStore,
    SubsequentEnvironmentObservation,
)

UTC = timezone.utc
AS_OF = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
CUTOFF = AS_OF - timedelta(minutes=5)


def _snapshot() -> CertifiedDecisionEnvironmentSnapshot:
    return CertifiedDecisionEnvironmentSnapshot(
        identifier="environment:decision:1",
        decision_identifier="decision:1",
        context_identifier="context:1",
        screening_publication_identifier="screening-publication:1",
        as_of=AS_OF,
        knowledge_cutoff=CUTOFF,
        published_at=AS_OF + timedelta(seconds=1),
        environment={
            "headline": "Growth is slowing while liquidity remains adequate.",
            "summary": "The certified decision-time evidence is mixed.",
            "portfolio_relevance": "Favor selective exposures over broad risk expansion.",
            "forecasts": ["forecast:global-growth:1"],
        },
        evidence_identifiers=(
            "evidence:growth:1",
            "evidence:liquidity:1",
            "forecast:global-growth:1",
        ),
        source_versions=(("macro_vintage", "2026-07-27T11:55Z"),),
        model_versions=(("environment_summary", "v1"),),
        code_version="commit:test",
        process_version="process:test-v1",
    )


def _observation(
    *,
    observed_at: datetime = AS_OF + timedelta(minutes=30),
    available_at: datetime = AS_OF + timedelta(hours=1),
    evidence_identifier: str = "evidence:later:1",
) -> SubsequentEnvironmentObservation:
    return SubsequentEnvironmentObservation(
        identifier="environment-observation:1",
        snapshot_identifier="environment:decision:1",
        observed_at=observed_at,
        available_at=available_at,
        category="market-development",
        summary="A later policy statement changed rate expectations.",
        source_identifier="central-bank:statement:1",
        evidence_identifier=evidence_identifier,
        material=True,
        payload={"rate_path_change_bps": -25},
    )


def test_environment_store_keeps_later_observations_outside_decision_snapshot(
    tmp_path: Path,
) -> None:
    store = SQLiteEnvironmentEvidenceStore(tmp_path / "environment.db")
    snapshot = _snapshot()
    observation = _observation()

    assert store.append_snapshot(snapshot) == 1
    assert store.append_observation(observation) == 2
    view = store.latest_view()

    assert view is not None
    assert view["decision_time_certified"] is True
    assert view["knowledge_cutoff"] == CUTOFF.isoformat()
    assert view["environment"] == snapshot.environment
    assert view["subsequent_observation_count"] == 1
    assert view["subsequent_observations"][0]["decision_time_certified"] is False
    assert "evidence:later:1" not in view["evidence_identifiers"]
    assert store.verify_integrity()


def test_observation_available_at_cutoff_cannot_be_reclassified_as_later(
    tmp_path: Path,
) -> None:
    store = SQLiteEnvironmentEvidenceStore(tmp_path / "environment.db")
    store.append_snapshot(_snapshot())

    with pytest.raises(EnvironmentEvidenceError, match="belongs in the certified"):
        store.append_observation(
            _observation(observed_at=CUTOFF, available_at=CUTOFF)
        )


def test_later_observation_cannot_reuse_decision_evidence_identifier(
    tmp_path: Path,
) -> None:
    store = SQLiteEnvironmentEvidenceStore(tmp_path / "environment.db")
    store.append_snapshot(_snapshot())

    with pytest.raises(EnvironmentEvidenceError, match="reuse"):
        store.append_observation(
            _observation(evidence_identifier="evidence:growth:1")
        )


def test_environment_history_is_append_only(tmp_path: Path) -> None:
    store = SQLiteEnvironmentEvidenceStore(tmp_path / "environment.db")
    store.append_snapshot(_snapshot())
    store.append_observation(_observation())

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM canonical_environment_events")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE canonical_environment_events SET payload_json='{}'"
            )


def test_api_serves_certified_snapshot_and_separate_later_developments(
    tmp_path: Path,
) -> None:
    environment_database = tmp_path / "environment.db"
    store = SQLiteEnvironmentEvidenceStore(environment_database)
    store.append_snapshot(_snapshot())
    store.append_observation(_observation())
    settings = ApiSettings(
        snapshot_database=tmp_path / "legacy-snapshot.db",
        portfolio_database=tmp_path / "portfolio.db",
        journal_database=tmp_path / "journal.db",
        full_universe_screening_database=tmp_path / "screening.db",
        environment_database=environment_database,
        require_canonical_environment=True,
        replay_directory=None,
    )
    client = TestClient(create_app(settings=settings))

    response = client.get("/v1/environment/latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["snapshot_identifier"] == "environment:decision:1"
    assert payload["decision_time_certified"] is True
    assert payload["subsequent_developments_are_decision_evidence"] is False
    assert payload["environment"] == _snapshot().environment
    assert payload["subsequent_observation_count"] == 1
    assert payload["subsequent_observations"][0]["summary"].startswith(
        "A later policy statement"
    )


def test_production_environment_route_fails_closed_without_certified_snapshot(
    tmp_path: Path,
) -> None:
    settings = ApiSettings(
        snapshot_database=tmp_path / "legacy-snapshot.db",
        portfolio_database=tmp_path / "portfolio.db",
        journal_database=tmp_path / "journal.db",
        full_universe_screening_database=tmp_path / "screening.db",
        environment_database=tmp_path / "missing-environment.db",
        require_canonical_environment=True,
        replay_directory=None,
    )
    client = TestClient(create_app(settings=settings))

    response = client.get("/v1/environment/latest")

    assert response.status_code == 503
    assert "required but unavailable" in response.json()["detail"]
