"""Consolidate duplicated production-context provider construction."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"{path}: replacement target count is {text.count(old)}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    canonical_old = '''def build_production_context_provider(
    *,
    screening_database: str | Path | None = None,
    portfolio_database: str | Path | None = None,
    context_database: str | Path | None = None,
    portfolio_code: str | None = None,
    code_version: str | None = None,
) -> RepositoryProductionCanonicalCIOContextProvider:
    """Build the repository-owned provider from explicit paths or environment."""

    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    return RepositoryProductionCanonicalCIOContextProvider(
        screening_store=SQLiteFullUniverseScreeningStore(
            screening_database
            or os.getenv(
                "CAPITAL_INTELLIGENCE_FULL_UNIVERSE_SCREENING_DATABASE"
            )
            or data_dir / "full_universe_screening.db"
        ),
        portfolio_store=SQLiteCanonicalPortfolioStore(
            portfolio_database
            or os.getenv(
                "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE"
            )
            or data_dir / "canonical_portfolio.db"
        ),
        context_store=SQLiteProductionContextStore(
            context_database
            or os.getenv(
                "CAPITAL_INTELLIGENCE_PRODUCTION_CONTEXT_DATABASE"
            )
            or data_dir / "production_context.db"
        ),
        portfolio_code=portfolio_code
        or os.getenv("CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_CODE")
        or "COMPOUNDING",
        code_version=code_version,
    )
'''
    canonical_new = '''def _build_production_context_provider(
    provider_type: type[RepositoryProductionCanonicalCIOContextProvider],
    *,
    screening_database: str | Path | None = None,
    portfolio_database: str | Path | None = None,
    context_database: str | Path | None = None,
    portfolio_code: str | None = None,
    code_version: str | None = None,
) -> RepositoryProductionCanonicalCIOContextProvider:
    """Build any repository provider from one canonical store/path policy."""

    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    return provider_type(
        screening_store=SQLiteFullUniverseScreeningStore(
            screening_database
            or os.getenv(
                "CAPITAL_INTELLIGENCE_FULL_UNIVERSE_SCREENING_DATABASE"
            )
            or data_dir / "full_universe_screening.db"
        ),
        portfolio_store=SQLiteCanonicalPortfolioStore(
            portfolio_database
            or os.getenv(
                "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE"
            )
            or data_dir / "canonical_portfolio.db"
        ),
        context_store=SQLiteProductionContextStore(
            context_database
            or os.getenv(
                "CAPITAL_INTELLIGENCE_PRODUCTION_CONTEXT_DATABASE"
            )
            or data_dir / "production_context.db"
        ),
        portfolio_code=portfolio_code
        or os.getenv("CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_CODE")
        or "COMPOUNDING",
        code_version=code_version,
    )


def build_production_context_provider(
    *,
    screening_database: str | Path | None = None,
    portfolio_database: str | Path | None = None,
    context_database: str | Path | None = None,
    portfolio_code: str | None = None,
    code_version: str | None = None,
) -> RepositoryProductionCanonicalCIOContextProvider:
    """Build the repository-owned provider from explicit paths or environment."""

    return _build_production_context_provider(
        RepositoryProductionCanonicalCIOContextProvider,
        screening_database=screening_database,
        portfolio_database=portfolio_database,
        context_database=context_database,
        portfolio_code=portfolio_code,
        code_version=code_version,
    )
'''
    replace_once("application/production_context.py", canonical_old, canonical_new)

    replace_once(
        "application/production_context_runtime.py",
        '''import os
from datetime import datetime
''',
        '''from datetime import datetime
''',
    )
    replace_once(
        "application/production_context_runtime.py",
        '''    SQLiteProductionContextStore,
    _aware,
    _text,
)''',
        '''    _aware,
    _build_production_context_provider,
    _text,
)''',
    )
    replace_once(
        "application/production_context_runtime.py",
        '''from portfolio.state import SQLiteCanonicalPortfolioStore
''',
        '''''',
    )
    replace_once(
        "application/production_context_runtime.py",
        '''    SQLiteFullUniverseScreeningStore,
    candidate_from_payload,
)''',
        '''    candidate_from_payload,
)''',
    )

    runtime_old = '''    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    return RepositoryProductionCanonicalCIOContextProvider(
        screening_store=SQLiteFullUniverseScreeningStore(
            screening_database
            or os.getenv(
                "CAPITAL_INTELLIGENCE_FULL_UNIVERSE_SCREENING_DATABASE"
            )
            or data_dir / "full_universe_screening.db"
        ),
        portfolio_store=SQLiteCanonicalPortfolioStore(
            portfolio_database
            or os.getenv(
                "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE"
            )
            or data_dir / "canonical_portfolio.db"
        ),
        context_store=SQLiteProductionContextStore(
            context_database
            or os.getenv("CAPITAL_INTELLIGENCE_PRODUCTION_CONTEXT_DATABASE")
            or data_dir / "production_context.db"
        ),
        portfolio_code=portfolio_code
        or os.getenv("CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_CODE")
        or "COMPOUNDING",
        code_version=code_version,
    )
'''
    runtime_new = '''    return _build_production_context_provider(
        RepositoryProductionCanonicalCIOContextProvider,
        screening_database=screening_database,
        portfolio_database=portfolio_database,
        context_database=context_database,
        portfolio_code=portfolio_code,
        code_version=code_version,
    )
'''
    replace_once("application/production_context_runtime.py", runtime_old, runtime_new)

    test_path = ROOT / "tests/test_production_context_factory.py"
    if test_path.exists():
        raise RuntimeError("factory consolidation test already exists")
    test_path.write_text(
        '''"""Production-context factories share one canonical path/store policy."""

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
''',
        encoding="utf-8",
    )

    manifest = ROOT / "docs/PRODUCTION_CONTEXT_FACTORY_CONSOLIDATION.md"
    if manifest.exists():
        raise RuntimeError("factory consolidation document already exists")
    manifest.write_text(
        '''# Production-context factory consolidation

The persisted-context and executable-context provider factories now use one canonical
store and environment-resolution helper. Provider behavior remains separate: the
runtime subclass still owns publication-timing semantics, while database paths,
portfolio code, code version, and store construction can no longer drift between the
two factories.

No decision, evidence, construction, execution, or portfolio authority changed.
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
