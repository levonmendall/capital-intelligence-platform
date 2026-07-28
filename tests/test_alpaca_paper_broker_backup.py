from __future__ import annotations

from pathlib import Path

from operations import CANONICAL_BACKUP_AUTHORITIES, build_canonical_backup_registry


def test_alpaca_paper_broker_is_required_recovery_authority(tmp_path: Path) -> None:
    registry = build_canonical_backup_registry(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path / "database")}
    )
    by_name = {item.logical_name: item for item in CANONICAL_BACKUP_AUTHORITIES}

    assert "alpaca_paper_broker" in registry.required_logical_names
    assert "alpaca_paper_broker" in registry.decision_reproduction_logical_names
    authority = by_name["alpaca_paper_broker"]
    assert authority.environment_variable == (
        "CAPITAL_INTELLIGENCE_ALPACA_PAPER_BROKER_DATABASE"
    )
    assert authority.default_filename == "alpaca_paper_broker.db"
    assert authority.category == "execution"
