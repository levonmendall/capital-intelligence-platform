"""Integration tests for normalization scheduling and read-only API."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import ApiSettings, create_app
from intelligence.analytical_engine import EngineDirection
from intelligence.engine_cycle import AnalyticalEngineCycleExecutor
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.normalization import EXPECTED_ENGINE_ORDER, MultiEngineNormalizer
from intelligence.normalization_store import SQLiteNormalizationStore
from tests.test_multi_engine_normalization import AS_OF, _result


class _CanonicalExecutor:
    def __init__(self) -> None:
        self.calls = []

    def run(self, *, as_of):
        self.calls.append(as_of)
        return {"snapshot_identifier": "daily:1"}


class _Engine:
    def __init__(self, engine_name: str) -> None:
        self.engine_name = engine_name
        self.calls = []

    def run(self, *, as_of):
        self.calls.append(as_of)
        direction = (
            EngineDirection.CONTRACTING
            if self.engine_name == "credit_cycle"
            else EngineDirection.EXPANDING
        )
        return SimpleNamespace(
            result=_result(
                self.engine_name,
                direction=direction,
                as_of=as_of,
            )
        )


def test_cycle_persists_raw_results_and_normalization_without_changing_contract(
    tmp_path,
) -> None:
    path = tmp_path / "analytical_engines.db"
    raw_store = SQLiteAnalyticalEngineStore(path)
    normalization_store = SQLiteNormalizationStore(path)
    canonical = _CanonicalExecutor()
    engines = tuple(_Engine(engine) for engine in EXPECTED_ENGINE_ORDER)
    executor = AnalyticalEngineCycleExecutor(
        canonical,
        engines,
        raw_store,
        normalizer=MultiEngineNormalizer(),
        normalization_store=normalization_store,
    )

    result = executor.run(as_of=AS_OF)

    assert result == {"snapshot_identifier": "daily:1"}
    assert canonical.calls == [AS_OF]
    assert all(engine.calls == [AS_OF] for engine in engines)
    assert all(raw_store.latest(engine) is not None for engine in EXPECTED_ENGINE_ORDER)
    bundle = normalization_store.latest()
    assert bundle is not None
    assert bundle.available_engine_count == 7
    assert bundle.to_dict()["weights_applied"] is False
    credit = next(
        item for item in bundle.assessments if item.engine == "credit_cycle"
    )
    assert credit.source_direction is EngineDirection.CONTRACTING


def test_cycle_requires_normalizer_and_store_together(tmp_path) -> None:
    raw_store = SQLiteAnalyticalEngineStore(tmp_path / "analytical_engines.db")
    canonical = _CanonicalExecutor()
    engines = (_Engine("global_liquidity"),)

    with pytest.raises(ValueError, match="provided together"):
        AnalyticalEngineCycleExecutor(
            canonical,
            engines,
            raw_store,
            normalizer=MultiEngineNormalizer(),
        )
    with pytest.raises(ValueError, match="provided together"):
        AnalyticalEngineCycleExecutor(
            canonical,
            engines,
            raw_store,
            normalization_store=SQLiteNormalizationStore(
                tmp_path / "other.db"
            ),
        )


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
