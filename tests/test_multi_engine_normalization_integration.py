"""Integration tests for normalization scheduling and read-only API."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import ApiSettings, create_app
from intelligence.analytical_engine import EngineDirection
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.normalization import EXPECTED_ENGINE_ORDER, MultiEngineNormalizer
from intelligence.normalization_store import SQLiteNormalizationStore
from tests.test_multi_engine_normalization import AS_OF, _result


def test_normalization_api_is_read_only_and_returns_latest_bundle(tmp_path) -> None:
    snapshot_database = tmp_path / "daily.db"
    analytical_database = tmp_path / "analytical_engines.db"
    store = SQLiteNormalizationStore(analytical_database)
    bundle = MultiEngineNormalizer().normalize(
        tuple(_result(engine) for engine in EXPECTED_ENGINE_ORDER),
        as_of=AS_OF,
    )
    store.append(bundle)
    settings = ApiSettings(
        snapshot_database=snapshot_database,
        portfolio_database=tmp_path / "portfolio.db",
        investor_memory_database=tmp_path / "memory.db",
        identity_database=tmp_path / "identity.db",
        journal_database=tmp_path / "journal.db",
        replay_directory=None,
        authentication_required=False,
    )
    client = TestClient(create_app(settings=settings))

    latest = client.get("/v1/normalization/latest")
    history = client.get("/v1/normalization/history?limit=10")

    assert latest.status_code == 200
    assert latest.json()["policy_version"] == "multi-engine-normalization.v1"
    assert latest.json()["aggregation_status"] == "not_performed"
    assert latest.json()["market_stance"] is None
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert client.post("/v1/normalization/latest").status_code == 405


def test_normalization_api_returns_404_before_first_bundle(tmp_path) -> None:
    settings = ApiSettings(
        snapshot_database=tmp_path / "daily.db",
        portfolio_database=tmp_path / "portfolio.db",
        investor_memory_database=tmp_path / "memory.db",
        identity_database=tmp_path / "identity.db",
        journal_database=tmp_path / "journal.db",
        replay_directory=None,
        authentication_required=False,
    )
    client = TestClient(create_app(settings=settings))

    assert client.get("/v1/normalization/latest").status_code == 404
    history = client.get("/v1/normalization/history")
    assert history.status_code == 200
    assert history.json()["total"] == 0
