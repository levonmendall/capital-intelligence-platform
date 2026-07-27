"""Legacy trading is retained only as offline compatibility code."""

from pathlib import Path

import pytest

from core.trading import TradingError, normalize_symbol


def test_symbol_normalization_remains_available_for_migration_tools() -> None:
    assert normalize_symbol(" spy ") == "SPY"
    with pytest.raises(TradingError):
        normalize_symbol(" ")


def test_legacy_trading_is_not_an_active_product_authority() -> None:
    active = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in ("app.py", "secure_app.py", "api/repositories.py", "run_scheduler.py", "run_paper_execution.py")
    )
    assert "core.trading" not in active
    assert "place_trade" not in active
    assert "UPDATE mandates" not in active


def test_canonical_paper_execution_is_the_only_active_implementation_path() -> None:
    source = Path("run_paper_execution.py").read_text(encoding="utf-8")
    assert "PaperExecutionOrchestrator" in source
    assert "core.trading" not in source
