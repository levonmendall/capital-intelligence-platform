from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import benchmark_portfolio_comparison as comparison


def _report() -> SimpleNamespace:
    return SimpleNamespace(
        compounded_portfolio_return=0.12,
        compounded_benchmark_return=0.08,
        compounded_cash_return=0.01,
        compounded_passive_return=0.06,
        maximum_drawdown=-0.035,
        observation_count=7,
        period_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 8, 8, tzinfo=timezone.utc),
        evaluated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        status=SimpleNamespace(value="insufficient_evidence"),
    )


def test_missing_store_is_truthfully_unavailable(tmp_path: Path) -> None:
    result = comparison.load_benchmark_portfolio_comparison(tmp_path / "missing.db")
    assert result.state == "unavailable"
    assert result.rows == ()
    assert result.evaluation_only is True
    assert result.investment_authority_changed is False
    assert result.real_money_authorized is False


def test_comparison_uses_existing_recorded_reference_returns(monkeypatch, tmp_path: Path) -> None:
    database = tmp_path / "paper_operation_evidence.db"
    database.touch()

    class FakeStore:
        def __init__(self, path: Path, *, initialize: bool) -> None:
            assert path == database
            assert initialize is False

        def verify_integrity(self) -> bool:
            return True

        def latest_report(self):
            return _report()

    monkeypatch.setattr(comparison, "SQLitePaperOperationEvidenceStore", FakeStore)
    result = comparison.load_benchmark_portfolio_comparison(database)

    assert result.state == "available"
    assert result.observation_count == 7
    assert [row.label for row in result.rows] == [
        "System paper portfolio",
        "80% VTI / 20% SGOV",
        "Passive reference portfolio",
        "Cash reference",
    ]
    assert [row.compounded_return for row in result.rows] == [0.12, 0.08, 0.06, 0.01]
    assert result.rows[1].excess_vs_system == -0.04
    assert result.system_maximum_drawdown == -0.035
    assert result.evaluation_only is True
    assert result.investment_authority_changed is False
    assert result.real_money_authorized is False


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


def test_portfolio_surface_exposes_benchmark_comparison_without_authority() -> None:
    source = Path("portfolio_ui_refinement.py").read_text(encoding="utf-8")
    assert '"Benchmark comparison"' in source
    assert "80% VTI / 20% SGOV" not in source  # definition remains centralized
    assert "Benchmark results cannot authorize a portfolio change." in source
    assert "load_benchmark_portfolio_comparison" in source
