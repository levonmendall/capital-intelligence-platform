"""Integration tests for evidence governance scheduling and read-only API."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from api import ApiSettings, create_app
from intelligence.engine_cycle import AnalyticalEngineCycleExecutor
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.governance import MultiEngineGovernor
from intelligence.governance_store import SQLiteGovernanceStore
from intelligence.normalization import EXPECTED_ENGINE_ORDER, MultiEngineNormalizer
from intelligence.normalization_store import SQLiteNormalizationStore
from intelligence.synthesis_store import SQLiteSynthesisStore
from intelligence.synthesis_weights import MultiEngineSynthesizer
from tests.test_multi_engine_normalization import AS_OF, _result


class _CanonicalExecutor:
    def run(self, *, as_of):
        return {"snapshot_identifier": "daily:1"}


class _Engine:
    def __init__(self, engine_name: str) -> None:
        self.engine_name = engine_name

    def run(self, *, as_of):
        return SimpleNamespace(result=_result(self.engine_name, as_of=as_of))


def test_cycle_persists_governance_without_changing_canonical_contract(
    tmp_path,
) -> None:
    path = tmp_path / "analytical_engines.db"
    governance_store = SQLiteGovernanceStore(path)
    executor = AnalyticalEngineCycleExecutor(
        _CanonicalExecutor(),
        tuple(_Engine(engine) for engine in EXPECTED_ENGINE_ORDER),
        SQLiteAnalyticalEngineStore(path),
        normalizer=MultiEngineNormalizer(),
        normalization_store=SQLiteNormalizationStore(path),
        synthesizer=MultiEngineSynthesizer(),
        synthesis_store=SQLiteSynthesisStore(path),
        governor=MultiEngineGovernor(),
        governance_store=governance_store,
    )
    assert executor.run(as_of=AS_OF) == {"snapshot_identifier": "daily:1"}
    result = governance_store.latest()
    assert result is not None
    assert governance_store.latest_policy() is not None
    assert result.to_dict()["committee_submitted"] is False
    assert result.to_dict()["personal_cio_action_affected"] is False


def test_governance_requires_synthesis_dependencies(tmp_path) -> None:
    path = tmp_path / "analytical_engines.db"
    try:
        AnalyticalEngineCycleExecutor(
            _CanonicalExecutor(),
            (_Engine("global_liquidity"),),
            SQLiteAnalyticalEngineStore(path),
            governor=MultiEngineGovernor(),
            governance_store=SQLiteGovernanceStore(path),
        )
    except ValueError as error:
        assert "governance requires weighted synthesis" in str(error)
    else:
        raise AssertionError("governance without synthesis dependencies must fail")


def test_governance_api_is_read_only(tmp_path) -> None:
    path = tmp_path / "analytical_engines.db"
    bundle = MultiEngineNormalizer().normalize(
        tuple(_result(engine) for engine in EXPECTED_ENGINE_ORDER),
        as_of=AS_OF,
    )
    synthesis = MultiEngineSynthesizer().synthesize(bundle)
    governor = MultiEngineGovernor()
    store = SQLiteGovernanceStore(path)
    store.append_policy(governor.policy)
    store.append(governor.evaluate(bundle, synthesis))
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
    assert client.get("/v1/governance/latest").status_code == 200
    assert client.get("/v1/governance/history").json()["total"] == 1
    assert client.get("/v1/governance/policies/latest").status_code == 200
    assert client.get("/v1/governance/policies/history").json()["total"] == 1
    assert client.post("/v1/governance/latest").status_code == 405
