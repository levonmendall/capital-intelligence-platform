"""Integration tests for business-cycle scheduling, API, and CIO context."""

from fastapi.testclient import TestClient

from api import ApiSettings, create_app
from intelligence.business_cycle import BusinessCycleEngine
from intelligence.engine_cycle import AnalyticalEngineCycleExecutor
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.global_liquidity import GlobalLiquidityEngine
from tests.test_business_cycle_engine import AS_OF, FakeBusinessCycleProvider
from tests.test_global_liquidity_engine import FakeLiquidityProvider


class _CanonicalExecutor:
    def __init__(self) -> None:
        self.calls = []

    def run(self, *, as_of):
        self.calls.append(as_of)
        return {"snapshot_identifier": "daily:1"}


def test_multi_engine_cycle_persists_results_without_changing_canonical_result(
    tmp_path,
) -> None:
    canonical = _CanonicalExecutor()
    store = SQLiteAnalyticalEngineStore(tmp_path / "engines.db")
    wrapper = AnalyticalEngineCycleExecutor(
        canonical,
        (
            GlobalLiquidityEngine(
                FakeLiquidityProvider(),
                clock=lambda: AS_OF,
            ),
            BusinessCycleEngine(
                FakeBusinessCycleProvider(),
                clock=lambda: AS_OF,
            ),
        ),
        store,
    )

    result = wrapper.run(as_of=AS_OF)

    assert result == {"snapshot_identifier": "daily:1"}
    assert canonical.calls == [AS_OF]
    assert store.latest("global_liquidity") is not None
    assert store.latest("business_cycle") is not None


def test_business_cycle_api_is_read_only_and_returns_latest_result(
    tmp_path,
) -> None:
    snapshot_database = tmp_path / "daily.db"
    analytical_database = tmp_path / "analytical_engines.db"
    store = SQLiteAnalyticalEngineStore(analytical_database)
    store.append(
        BusinessCycleEngine(
            FakeBusinessCycleProvider(),
            clock=lambda: AS_OF,
        ).run(as_of=AS_OF).result
    )
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

    latest = client.get("/v1/business-cycle/latest")
    history = client.get("/v1/business-cycle/history?limit=10")

    assert latest.status_code == 200
    assert latest.json()["engine"] == "business_cycle"
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert client.post("/v1/business-cycle/latest").status_code == 405
