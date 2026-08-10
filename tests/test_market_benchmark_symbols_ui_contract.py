from pathlib import Path


def test_market_benchmark_symbols_are_product_facing_and_fixed() -> None:
    comparison = Path("benchmark_portfolio_comparison.py").read_text(encoding="utf-8")
    for symbol in ("SPY", "QQQ", "VTI", "VT", "AGG", "SGOV"):
        assert f'("{symbol}",' in comparison
    portfolio = Path("portfolio_ui_refinement.py").read_text(encoding="utf-8")
    assert '"Performance vs benchmarks"' in portfolio
    assert "row.label" in portfolio
