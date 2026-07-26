"""Integration tests for weighted synthesis scheduling and API."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from api import ApiSettings, create_app
from intelligence.engine_cycle import AnalyticalEngineCycleExecutor
from intelligence.engine_store import SQLiteAnalyticalEngineStore
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


def test_cycle_persists_synthesis_without_changing_canonical_contract(
    tmp_path,
) -> None:
    path = tmp_path / "analytical_engines.db"
    synthesis_store = SQLiteSynthesisStore(path)
    executor = AnalyticalEngineCycleExecutor(
        _CanonicalExecutor(),
        tuple(_Engine(engine) for engine in EXPECTED_ENGINE_ORDER),
        SQLiteAnalyticalEngineStore(path),
        normalizer=MultiEngineNormalizer(),
        normalization_store=SQLiteNormalizationStore(path),
        synthesizer=MultiEngineSynthesizer(),
        synthesis_store=synthesis_store,
    )
    assert executor.run(as_of=AS_OF) == {"snapshot_identifier": "daily:1"}
    assert synthesis_store.latest() is not None
    assert synthesis_store.latest_policy() is not None


def test_synthesis_api_is_read_only(tmp_path) -> None:
    path = tmp_path / "analytical_engines.db"
    bundle = MultiEngineNormalizer().normalize(
        tuple(_result(engine) for engine in EXPECTED_ENGINE_ORDER),
        as_of=AS_OF,
    )
    synthesizer = MultiEngineSynthesizer()
    store = SQLiteSynthesisStore(path)
    store.append_policy(synthesizer.policy)
    store.append(synthesizer.synthesize(bundle))
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
    assert client.get("/v1/synthesis/latest").status_code == 200
    assert client.get("/v1/synthesis/history").json()["total"] == 1
    assert client.get("/v1/synthesis/policies/latest").status_code == 200
    assert client.get("/v1/synthesis/policies/history").json()["total"] == 1
    assert client.post("/v1/synthesis/latest").status_code == 405
