"""Integration tests for liquidity persistence, API, and Personal CIO context."""

from fastapi.testclient import TestClient

from api import ApiSettings, create_app
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.global_liquidity import GlobalLiquidityEngine
from intelligence.liquidity_cycle import LiquidityAwareCycleExecutor
from personal_cio import ActionStatus, build_personal_cio_brief
from tests.test_global_liquidity_engine import AS_OF, FakeLiquidityProvider
from tests.test_personal_cio_brief import NOW, _goal, _profile, _snapshot


class _CanonicalExecutor:
    def __init__(self) -> None:
        self.calls = []

    def run(self, *, as_of):
        self.calls.append(as_of)
        return {"snapshot_identifier": "daily:1"}


def test_cycle_wrapper_persists_liquidity_without_changing_canonical_result(
    tmp_path,
) -> None:
    canonical = _CanonicalExecutor()
    store = SQLiteAnalyticalEngineStore(tmp_path / "engines.db")
    wrapper = LiquidityAwareCycleExecutor(
        canonical,
        GlobalLiquidityEngine(
            FakeLiquidityProvider(),
            clock=lambda: AS_OF,
        ),
        store,
    )

    result = wrapper.run(as_of=AS_OF)

    assert result == {"snapshot_identifier": "daily:1"}
    assert canonical.calls == [AS_OF]
    assert store.latest("global_liquidity") is not None


def test_personal_cio_adds_liquidity_context_without_changing_action() -> None:
    liquidity = GlobalLiquidityEngine(
        FakeLiquidityProvider(),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result
    brief = build_personal_cio_brief(
        "investor:1",
        daily_snapshot=_snapshot(),
        profile=_profile(),
        goals=(_goal(),),
        portfolios=(
            {
                "code": "GROWTH",
                "risk": "moderate",
                "nav": 500_000,
                "cash": 100_000,
            },
        ),
        generated_at=NOW,
        analytical_results=(liquidity,),
    )

    assert brief.action_status is ActionStatus.NO_ACTION
    assert "Global liquidity" in brief.why_it_matters
    assert "Liquidity transmission" in brief.portfolio_effect
    assert liquidity.identifier in brief.evidence_identifiers


def test_liquidity_api_is_read_only_and_returns_latest_result(
    tmp_path,
) -> None:
    snapshot_database = tmp_path / "daily.db"
    analytical_database = tmp_path / "analytical_engines.db"
    store = SQLiteAnalyticalEngineStore(analytical_database)
    store.append(
        GlobalLiquidityEngine(
            FakeLiquidityProvider(),
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

    latest = client.get("/v1/liquidity/latest")
    history = client.get("/v1/liquidity/history?limit=10")

    assert latest.status_code == 200
    assert latest.json()["engine"] == "global_liquidity"
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert client.post("/v1/liquidity/latest").status_code == 405
