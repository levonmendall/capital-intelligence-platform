from __future__ import annotations

from pathlib import Path

from operations import CANONICAL_BACKUP_AUTHORITIES, build_canonical_backup_registry


def test_all_paper_execution_authorities_are_required_for_recovery(
    tmp_path: Path,
) -> None:
    registry = build_canonical_backup_registry(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path / "database")}
    )
    by_name = {item.logical_name: item for item in CANONICAL_BACKUP_AUTHORITIES}
    required = {
        "paper_test_governance",
        "paper_trading_launch",
        "paper_trading_control",
    }

    assert required <= set(registry.required_logical_names)
    assert required <= set(registry.decision_reproduction_logical_names)
    assert by_name["paper_test_governance"].default_filename == (
        "paper_test_governance.db"
    )
    assert by_name["paper_trading_launch"].default_filename == (
        "paper_trading_launch.db"
    )
    assert by_name["paper_trading_control"].default_filename == (
        "paper_trading_control.db"
    )
