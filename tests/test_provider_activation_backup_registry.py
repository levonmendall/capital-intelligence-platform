from __future__ import annotations

from pathlib import Path

from operations import CANONICAL_BACKUP_AUTHORITIES, build_canonical_backup_registry


def test_provider_activation_authorities_are_required_for_recovery(
    tmp_path: Path,
) -> None:
    registry = build_canonical_backup_registry(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path / "database")}
    )
    by_name = {item.logical_name: item for item in CANONICAL_BACKUP_AUTHORITIES}
    required = {
        "provider_activations",
        "decision_information_activations",
    }

    assert required <= set(registry.required_logical_names)
    assert required <= set(registry.decision_reproduction_logical_names)
    assert by_name["provider_activations"].default_filename == (
        "provider_activations.db"
    )
    assert by_name["decision_information_activations"].default_filename == (
        "decision_information_activations.db"
    )
