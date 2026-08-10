from pathlib import Path


def test_market_benchmark_feature_stays_out_of_investment_authority_modules() -> None:
    forbidden = (
        Path("cio"),
        Path("committee"),
        Path("construction"),
        Path("execution"),
        Path("portfolio") / "construction.py",
    )
    references = []
    for root in forbidden:
        if root.is_file():
            paths = (root,)
        elif root.is_dir():
            paths = tuple(root.rglob("*.py"))
        else:
            continue
        for path in paths:
            text = path.read_text(encoding="utf-8")
            if "MARKET_BENCHMARKS" in text or "benchmark_portfolio_comparison" in text:
                references.append(str(path))
    assert references == []


def test_formal_experiment_benchmark_is_not_redefined_by_market_comparison() -> None:
    source = Path("benchmark_portfolio_comparison.py").read_text(encoding="utf-8")
    assert "80% VTI / 20% SGOV" not in source
    assert "SPY" in source
    assert "QQQ" in source
    assert "real_money_authorized: bool = False" in source
    assert "investment_authority_changed: bool = False" in source
