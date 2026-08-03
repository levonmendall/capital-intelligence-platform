"""Integration tests for credit-cycle scheduling, API, and CIO context."""

from fastapi.testclient import TestClient

from api import ApiSettings, create_app
from intelligence.business_cycle import BusinessCycleEngine
from intelligence.credit_cycle import CreditCycleEngine
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.global_liquidity import GlobalLiquidityEngine
from tests.test_business_cycle_engine import FakeBusinessCycleProvider
from tests.test_credit_cycle_engine import AS_OF, FakeCreditCycleProvider
from tests.test_global_liquidity_engine import FakeLiquidityProvider


def test_credit_cycle_api_is_read_only_and_returns_latest_result(
    tmp_path,
) -> None:
    snapshot_database = tmp_path / "daily.db"
    analytical_database = tmp_path / "analytical_engines.db"
    store = SQLiteAnalyticalEngineStore(analytical_database)
    store.append(
        CreditCycleEngine(
            FakeCreditCycleProvider(),
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

    latest = client.get("/v1/credit-cycle/latest")
    history = client.get("/v1/credit-cycle/history?limit=10")

    assert latest.status_code == 200
    assert latest.json()["engine"] == "credit_cycle"
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert client.post("/v1/credit-cycle/latest").status_code == 405
