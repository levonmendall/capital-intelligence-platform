"""Integration tests for market-breadth scheduling, API, and CIO context."""

from fastapi.testclient import TestClient

from api import ApiSettings, create_app
from intelligence.business_cycle import BusinessCycleEngine
from intelligence.credit_cycle import CreditCycleEngine
from intelligence.engine_cycle import AnalyticalEngineCycleExecutor
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.global_liquidity import GlobalLiquidityEngine
from intelligence.market_breadth import MarketBreadthEngine
from tests.test_business_cycle_engine import FakeBusinessCycleProvider
from tests.test_credit_cycle_engine import FakeCreditCycleProvider
from tests.test_global_liquidity_engine import FakeLiquidityProvider
from tests.test_market_breadth_engine import AS_OF, FakeMarketBreadthProvider


class _CanonicalExecutor:
    def __init__(self) -> None:
        self.calls = []

    def run(self, *, as_of):
        self.calls.append(as_of)
        return {"snapshot_identifier": "daily:1"}


def test_multi_engine_cycle_persists_four_results_without_changing_contract(
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
            CreditCycleEngine(
                FakeCreditCycleProvider(),
                clock=lambda: AS_OF,
            ),
            MarketBreadthEngine(
                FakeMarketBreadthProvider(),
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
    assert store.latest("credit_cycle") is not None
    assert store.latest("market_breadth") is not None


def test_market_breadth_api_is_read_only_and_returns_latest_result(
    tmp_path,
) -> None:
    snapshot_database = tmp_path / "daily.db"
    analytical_database = tmp_path / "analytical_engines.db"
    store = SQLiteAnalyticalEngineStore(analytical_database)
    store.append(
        MarketBreadthEngine(
            FakeMarketBreadthProvider(),
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

    latest = client.get("/v1/market-breadth/latest")
    history = client.get("/v1/market-breadth/history?limit=10")

    assert latest.status_code == 200
    assert latest.json()["engine"] == "market_breadth"
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert client.post("/v1/market-breadth/latest").status_code == 405
