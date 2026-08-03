"""Production-context factories share one canonical path/store policy."""

from pathlib import Path

from application.production_context import (
    RepositoryProductionCanonicalCIOContextProvider as StoredProvider,
    build_production_context_provider as build_stored_provider,
)
from application.production_context_runtime import (
    RepositoryProductionCanonicalCIOContextProvider as RuntimeProvider,
    build_production_context_provider as build_runtime_provider,
)


def test_factories_share_explicit_database_wiring(tmp_path: Path) -> None:
    screening = tmp_path / "screening.db"
    portfolio = tmp_path / "portfolio.db"
    context = tmp_path / "context.db"

    stored = build_stored_provider(
        screening_database=screening,
        portfolio_database=portfolio,
        context_database=context,
        portfolio_code="compounding",
        code_version="factory-test",
    )
    runtime = build_runtime_provider(
        screening_database=screening,
        portfolio_database=portfolio,
        context_database=context,
        portfolio_code="compounding",
        code_version="factory-test",
    )

    assert type(stored) is StoredProvider
    assert type(runtime) is RuntimeProvider
    for provider in (stored, runtime):
        assert provider.screening_store.path == screening
        assert provider.portfolio_store.path == portfolio
        assert provider.context_store.path == context
        assert provider.portfolio_code == "COMPOUNDING"
        assert provider.code_version == "factory-test"


def test_factories_share_environment_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_CODE", "COMPOUNDING")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_CODE_VERSION", "environment-test")

    stored = build_stored_provider()
    runtime = build_runtime_provider()

    for provider in (stored, runtime):
        assert provider.screening_store.path == tmp_path / "full_universe_screening.db"
        assert provider.portfolio_store.path == tmp_path / "canonical_portfolio.db"
        assert provider.context_store.path == tmp_path / "production_context.db"
        assert provider.portfolio_code == "COMPOUNDING"
        assert provider.code_version == "environment-test"
