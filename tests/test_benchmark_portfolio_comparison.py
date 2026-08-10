from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import benchmark_portfolio_comparison as comparison


def _report() -> SimpleNamespace:
    return SimpleNamespace(
        compounded_portfolio_return=0.12,
        maximum_drawdown=-0.035,
        observation_count=7,
        period_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 8, 8, tzinfo=timezone.utc),
        evaluated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        status=SimpleNamespace(value="insufficient_evidence"),
    )


class FakeStore:
    def __init__(self, path: Path, *, initialize: bool) -> None:
        assert initialize is False

    def verify_integrity(self) -> bool:
        return True

    def latest_report(self):
        return _report()


class FakeMarketClient:
    def historical_bars(self, symbols, *, start, end, timeframe):
        assert tuple(symbols) == ("SPY", "QQQ", "VTI", "VT", "AGG", "SGOV")
        assert start == _report().period_start
        assert end > _report().period_end
        assert timeframe == "1Day"
        returns = {
            "SPY": 0.08,
            "QQQ": 0.14,
            "VTI": 0.07,
            "VT": 0.05,
            "AGG": 0.02,
            "SGOV": 0.01,
        }
        return {
            symbol: ({"c": 100.0}, {"c": 100.0 * (1.0 + value)})
            for symbol, value in returns.items()
        }


def test_market_benchmark_set_is_explicit_and_nonoverlapping_in_purpose() -> None:
    assert comparison.MARKET_BENCHMARK_SYMBOLS == ("SPY", "QQQ", "VTI", "VT", "AGG", "SGOV")
    assert [item[1] for item in comparison.MARKET_BENCHMARKS] == [
        "S&P 500",
        "Nasdaq-100",
        "Total U.S. stock market",
        "Total world equities",
        "U.S. aggregate bonds",
        "0–3 month U.S. Treasuries",
    ]


def test_missing_store_is_truthfully_unavailable(tmp_path: Path) -> None:
    result = comparison.load_benchmark_portfolio_comparison(tmp_path / "missing.db")
    assert result.state == "unavailable"
    assert result.rows == ()
    assert result.evaluation_only is True
    assert result.investment_authority_changed is False
    assert result.real_money_authorized is False


def test_comparison_uses_same_window_market_benchmarks(monkeypatch, tmp_path: Path) -> None:
    database = tmp_path / "paper_operation_evidence.db"
    database.touch()
    monkeypatch.setattr(comparison, "SQLitePaperOperationEvidenceStore", FakeStore)

    result = comparison.load_benchmark_portfolio_comparison(
        database,
        market_client=FakeMarketClient(),
    )

    assert result.state == "available"
    assert result.observation_count == 7
    assert [row.symbol for row in result.rows] == [None, "SPY", "QQQ", "VTI", "VT", "AGG", "SGOV"]
    assert [row.compounded_return for row in result.rows] == [0.12, 0.08, 0.14, 0.07, 0.05, 0.02, 0.01]
    assert result.rows[1].system_excess_return == 0.04
    assert result.rows[2].system_excess_return == -0.02
    assert result.system_maximum_drawdown == -0.035
    assert result.market_data_source == "Alpaca/IEX adjusted daily bars"
    assert result.evaluation_only is True
    assert result.investment_authority_changed is False
    assert result.real_money_authorized is False


def test_missing_market_data_is_withheld_not_estimated(monkeypatch, tmp_path: Path) -> None:
    database = tmp_path / "paper_operation_evidence.db"
    database.touch()
    monkeypatch.setattr(comparison, "SQLitePaperOperationEvidenceStore", FakeStore)

    class MissingMarketClient:
        def historical_bars(self, symbols, *, start, end, timeframe):
            return {symbol: () for symbol in symbols}

    result = comparison.load_benchmark_portfolio_comparison(
        database,
        market_client=MissingMarketClient(),
    )
    assert result.state == "partial"
    assert result.rows[0].compounded_return == 0.12
    assert all(row.compounded_return is None for row in result.rows[1:])
    assert "No benchmark return is estimated" in result.detail


def test_integrity_failure_withholds_comparison(monkeypatch, tmp_path: Path) -> None:
    database = tmp_path / "paper_operation_evidence.db"
    database.touch()

    class BrokenStore:
        def __init__(self, path: Path, *, initialize: bool) -> None:
            pass

        def verify_integrity(self) -> bool:
            raise RuntimeError("tampered")

    monkeypatch.setattr(comparison, "SQLitePaperOperationEvidenceStore", BrokenStore)
    result = comparison.load_benchmark_portfolio_comparison(database)
    assert result.state == "unavailable"
    assert "withheld" in result.detail


def test_portfolio_surface_exposes_comparison_without_authority() -> None:
    source = Path("portfolio_ui_refinement.py").read_text(encoding="utf-8")
    assert '"Performance vs benchmarks"' in source
    assert "80% VTI / 20% SGOV" not in source
    assert "Benchmark results are evaluation-only." in source
    assert "load_benchmark_portfolio_comparison" in source
