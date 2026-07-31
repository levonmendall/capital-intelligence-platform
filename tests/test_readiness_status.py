"""Readiness statuses must remain independent and evidence-backed."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from api import ApiSettings, create_app
from api.readiness_status import ReadinessStatusRepository
from governance import (
    OperationalReadinessSnapshot,
    ProductTestReadiness,
    ProductTestReadinessReport,
    SQLiteProductTestReadinessStore,
    SQLiteReadinessEvidenceStore,
)

UTC = timezone.utc
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _operational_store(path: Path) -> None:
    SQLiteReadinessEvidenceStore(path).append_operational(
        OperationalReadinessSnapshot(
            identifier="operational:1",
            baseline_identifier="baseline:1",
            observed_at=NOW,
            knowledge_cutoff=NOW,
            process_version="process:1",
            code_version="commit:1",
            unresolved_critical_incidents=0,
            data_integrity_failures=0,
            reconciliation_failures=0,
            source_identifiers=("daily-operation:1", "slo:1", "resilience:1"),
        )
    )


def _paper_test_store(path: Path) -> None:
    SQLiteProductTestReadinessStore(path).append(
        ProductTestReadinessReport(
            identifier="paper-readiness:1",
            assessed_at=NOW,
            state=ProductTestReadiness.BLOCKED,
            baseline_identifier="baseline:1",
            process_version="process:1",
            blockers=("resilience_campaign",),
            development_items=("multi-day burn-in remains open",),
            evidence_identifiers=("operational:1",),
        )
    )


def test_persisted_operational_and_paper_test_readiness_are_independent(
    tmp_path: Path,
) -> None:
    operational_path = tmp_path / "operational.db"
    paper_path = tmp_path / "paper.db"
    _operational_store(operational_path)
    _paper_test_store(paper_path)
    repository = ReadinessStatusRepository(
        readiness_evidence_path=operational_path,
        product_test_readiness_path=paper_path,
    )

    operational = repository.latest_operational()
    paper_test = repository.latest_paper_test()

    assert operational["state"] == "ready"
    assert operational["ready"] is True
    assert paper_test["state"] == "blocked"
    assert paper_test["ready"] is False
    assert paper_test["real_money_authorized"] is False
    assert paper_test["performance_claims_permitted"] is False


def test_detailed_readiness_is_private_when_authentication_is_disabled(tmp_path: Path) -> None:
    operational_path = tmp_path / "operational.db"
    paper_path = tmp_path / "paper.db"
    _operational_store(operational_path)
    _paper_test_store(paper_path)
    screening = tmp_path / "screening.db"
    with sqlite3.connect(screening) as connection:
        connection.execute("CREATE TABLE screening_state (identifier TEXT)")
    backup_directory = tmp_path / "backups"
    backup_directory.mkdir()
    settings = ApiSettings(
        snapshot_database=tmp_path / "legacy.db",
        portfolio_database=tmp_path / "portfolio.db",
        journal_database=tmp_path / "journal.db",
        full_universe_screening_database=screening,
        environment_database=tmp_path / "environment.db",
        readiness_evidence_database=operational_path,
        product_test_readiness_database=paper_path,
        require_canonical_environment=False,
        replay_directory=None,
    )
    client = TestClient(create_app(settings=settings))

    response = client.get("/v1/readiness/status")

    assert response.status_code == 403


def test_dependency_readiness_excludes_retired_components(tmp_path: Path) -> None:
    screening = tmp_path / "screening.db"
    with sqlite3.connect(screening) as connection:
        connection.execute("CREATE TABLE screening_state (identifier TEXT)")
    settings = ApiSettings(
        snapshot_database=tmp_path / "legacy.db",
        portfolio_database=tmp_path / "portfolio.db",
        journal_database=tmp_path / "journal.db",
        full_universe_screening_database=screening,
        environment_database=tmp_path / "environment.db",
        require_canonical_environment=False,
        replay_directory=None,
    )
    client = TestClient(create_app(settings=settings))

    response = client.get("/ready")

    assert response.status_code == 503
    components = response.json()["components"]
    assert "canonical_environment" in components
    assert "full_universe_screening" in components
    assert "analytical_engines" not in components
    assert "weighted_synthesis" not in components
    assert "daily_snapshots" not in components
    assert "operational_slos" not in components
