"""Architecture tests protecting the canonical user and API surfaces."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOVERNING_RULE = (
    "Every recommendation is compared against all other available uses of "
    "capital, implemented at the portfolio level, continuously monitored "
    "against an explicit thesis, and evaluated afterward using the exact "
    "evidence available when the decision was made."
)


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_streamlit_has_only_four_canonical_primary_surfaces() -> None:
    source = _source("app.py")

    assert '["Today", "Environment", "Portfolio", "History"]' in source
    assert '"daily_cio_briefing"' in source
    assert '"portfolio_construction"' in source
    assert '"decision_evaluation"' in source
    assert '"thesis_snapshot"' in source
    assert "No governed CIO briefing is available" in source


def test_active_streamlit_surface_has_no_legacy_decision_authority() -> None:
    source = _source("app.py")
    secure_source = _source("secure_app.py")

    for prohibited in (
        "from personalization",
        "import personalization",
        "InvestorMemory",
        "conviction_trend",
        "run_intelligence",
        "legacy_decision",
        "daily_view.score",
        "Capital Intelligence Score",
        "committee.workflow",
    ):
        assert prohibited not in source
    assert "from personalization" not in secure_source
    assert "InvestorMemory" not in secure_source
    assert "AuthorizedMemoryStore" not in secure_source


def test_active_api_registers_cio_and_not_personal_authority() -> None:
    app_source = _source("api/app.py")
    routes_source = _source("api/routes/__init__.py")
    cio_source = _source("api/routes/cio.py")

    assert "app.include_router(cio_router" in app_source
    assert "personal_router" not in app_source
    assert "conviction_router" not in app_source
    assert "investor_memory_router" not in app_source
    assert "personal_router" not in routes_source
    assert 'prefix="/v1/cio"' in cio_source
    from api.routes.cio import process

    assert process()["governing_rule"] == GOVERNING_RULE


def test_canonical_cycle_enforces_all_four_governing_stages() -> None:
    source = _source("application/cio_cycle.py")

    assert "build_queue" in source
    assert "OpportunitySetContext" in source
    assert "_construct_final_portfolio" in source
    assert "_create_theses" in source
    assert "_capture_evaluation_snapshots" in source
    assert "append_construction" in source
    assert "append_evidence_snapshot" in source
    assert "DAILY_CIO_BRIEFING" in source or "daily_cio_briefing" in source


def test_active_entrypoints_do_not_import_weighted_committee_authority() -> None:
    for relative in (
        "app.py",
        "secure_app.py",
        "api/app.py",
        "api/routes/cio.py",
        "application/cio_cycle.py",
    ):
        source = _source(relative)
        assert "committee.workflow" not in source
        assert "WeightedVote" not in source
        assert "from committee.workflow" not in source
        assert "import committee.workflow" not in source


def test_public_contracts_repeat_the_governing_rule_and_boundaries() -> None:
    for relative in (
        "README.md",
        "ROADMAP.md",
        "ARCHITECTURE.md",
        "docs/PRODUCTION_API.md",
        "docs/DAILY_INTELLIGENCE_EXPERIENCE.md",
    ):
        source = " ".join(_source(relative).split())
        assert GOVERNING_RULE in source

    readme = _source("README.md")
    assert "does not execute live trades" in readme
    assert "does not claim proven alpha" in readme
