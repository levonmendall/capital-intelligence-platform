from __future__ import annotations

from pathlib import Path

from operations import CANONICAL_BACKUP_AUTHORITIES, build_canonical_backup_registry


def test_paper_launch_and_control_are_required_recovery_authorities(
    tmp_path: Path,
) -> None:
    registry = build_canonical_backup_registry(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path / "database")}
    )
    by_name = {item.logical_name: item for item in CANONICAL_BACKUP_AUTHORITIES}

    assert "paper_trading_launch" in registry.required_logical_names
    assert "paper_trading_control" in registry.required_logical_names
    assert "paper_trading_launch" in registry.decision_reproduction_logical_names
    assert "paper_trading_control" in registry.decision_reproduction_logical_names
    assert by_name["paper_trading_launch"].default_filename == (
        "paper_trading_launch.db"
    )
    assert by_name["paper_trading_control"].default_filename == (
        "paper_trading_control.db"
    )
