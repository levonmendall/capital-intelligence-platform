from pathlib import Path


def test_active_product_uses_canonical_portfolio_source_only() -> None:
    active = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in ("app.py", "secure_app.py", "api/repositories.py", "run_scheduler.py", "run_paper_execution.py")
    )
    assert "core.trading" not in active
    assert "seed_mandates" not in active
    assert "capital_intelligence.db" not in active
    assert "canonical_portfolio_events" in Path("api/repositories.py").read_text(encoding="utf-8")
    assert "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE" in Path("api/config.py").read_text(encoding="utf-8")
