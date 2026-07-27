from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ALERT_TOPICS = (
    "cio_decision",
    "thesis",
    "opportunity",
    "implementation",
    "evidence",
    "daily_briefing",
)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8").lower()


def test_active_documentation_has_one_compounding_mandate() -> None:
    architecture = _read("ARCHITECTURE.md")
    roadmap = _read("ROADMAP.md")
    mandate = _read("docs/COMPOUNDING_MANDATE.md")
    portfolio = _read("docs/CANONICAL_PORTFOLIO_STATE.md")

    assert "one active investment mandate" in architecture
    assert "`compounding` is the sole active investment mandate" in roadmap
    assert "sole active investment mandate is `compounding`" in mandate
    assert "sole `compounding` investment mandate" in portfolio


def test_operational_constraints_are_not_competing_objectives() -> None:
    for path in (
        "ARCHITECTURE.md",
        "ROADMAP.md",
        "docs/COMPOUNDING_MANDATE.md",
        "docs/CANONICAL_PORTFOLIO_STATE.md",
    ):
        text = _read(path)
        assert "operational constraint" in text or "implementation constraint" in text

    assert "cannot create competing objectives" in _read("ARCHITECTURE.md")
    assert "do not create competing portfolio objectives" in _read(
        "docs/COMPOUNDING_MANDATE.md"
    )


def test_active_alert_docs_use_only_canonical_topics() -> None:
    for path in (
        "docs/CANONICAL_ALERTS.md",
        "docs/PRODUCTION_API.md",
        "docs/DAILY_INTELLIGENCE_EXPERIENCE.md",
        "docs/LEGACY_AUTHORITY_ISOLATION.md",
    ):
        text = _read(path)
        for topic in CANONICAL_ALERT_TOPICS:
            assert topic in text

    api_text = _read("docs/PRODUCTION_API.md")
    daily_text = _read("docs/DAILY_INTELLIGENCE_EXPERIENCE.md")
    assert "confidence thresholds" in api_text
    assert "not active alert controls" in api_text
    assert "not independent alert authorities" in daily_text


def test_retired_database_is_migration_only() -> None:
    architecture = _read("ARCHITECTURE.md")
    portfolio = _read("docs/CANONICAL_PORTFOLIO_STATE.md")
    legacy = _read("docs/LEGACY_AUTHORITY_ISOLATION.md")

    assert "query-only migration source" in architecture
    assert "query-only mode" in portfolio
    assert "retired mandate/trading database" in legacy
    assert "own active cash, holdings, valuations, or implementation lineage" in legacy


def test_documentation_preserves_truthful_readiness_boundary() -> None:
    roadmap = _read("ROADMAP.md")
    mandate = _read("docs/COMPOUNDING_MANDATE.md")

    assert "not yet proven as a production investment manager" in roadmap
    assert "licensed point-in-time provider coverage" in mandate
    assert "must remain explicitly blocked or insufficient" in mandate
