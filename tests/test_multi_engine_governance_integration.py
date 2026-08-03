"""Integration tests for evidence governance scheduling and read-only API."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from api import ApiSettings, create_app
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.governance import MultiEngineGovernor
from intelligence.governance_store import SQLiteGovernanceStore
from intelligence.normalization import EXPECTED_ENGINE_ORDER, MultiEngineNormalizer
from intelligence.normalization_store import SQLiteNormalizationStore
from intelligence.synthesis_store import SQLiteSynthesisStore
from intelligence.synthesis_weights import MultiEngineSynthesizer
from tests.test_multi_engine_normalization import AS_OF, _result


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
