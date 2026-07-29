from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from operations import CANONICAL_BACKUP_AUTHORITIES
from run_backup import build_manager


def _database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS activation_probe (identifier TEXT PRIMARY KEY)"
        )
        connection.execute(
            "INSERT OR IGNORE INTO activation_probe (identifier) VALUES ('ready')"
        )


def _environment(tmp_path: Path, *, activation_aware: bool = True) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_ENVIRONMENT": "test",
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_BACKUP_DIRECTORY": str(tmp_path / "backups"),
        "CAPITAL_INTELLIGENCE_BACKUP_ACTIVATION_AWARE": (
            "true" if activation_aware else "false"
        ),
        "CAPITAL_INTELLIGENCE_REQUIRE_ENCRYPTED_BACKUPS": "false",
        "CAPITAL_INTELLIGENCE_REQUIRE_OPERATIONAL_SLOS": "false",
        "CAPITAL_INTELLIGENCE_ENFORCE_HTTPS": "false",
    }


def test_activation_aware_backup_accepts_fresh_disk_and_persists_authority_set(
    tmp_path: Path,
) -> None:
    _database(tmp_path / "canonical_portfolio.db")
    _database(tmp_path / "identity.db")

    manager = build_manager(_environment(tmp_path))

    assert manager.required_sources == ("canonical_portfolio", "identity")
    assert manager.validate_sources()["status"] == "valid"
    result = manager.create_backup()
    assert result.manifest["required_logical_names"] == [
        "canonical_portfolio",
        "identity",
    ]
    assert {item["logical_name"] for item in result.manifest["files"]} == {
        "canonical_portfolio",
        "identity",
    }

    state = json.loads(
        (tmp_path / "backup-authority-activation.json").read_text(encoding="utf-8")
    )
    assert state["schema_version"] == "canonical-backup-authority-activation.v1"
    assert state["activated_logical_names"] == [
        "canonical_portfolio",
        "identity",
    ]
    assert state["real_money_authorized"] is False


def test_activated_authority_remains_required_after_database_disappears(
    tmp_path: Path,
) -> None:
    database = tmp_path / "canonical_portfolio.db"
    _database(database)
    environment = _environment(tmp_path)

    first = build_manager(environment)
    assert first.validate_sources()["status"] == "valid"
    database.unlink()

    second = build_manager(environment)
    report = second.validate_sources()

    assert second.required_sources == ("canonical_portfolio",)
    assert report["status"] == "blocked"
    assert "canonical_portfolio" in report["missing_required"]


def test_strict_backup_policy_remains_default_outside_activation_aware_host(
    tmp_path: Path,
) -> None:
    manager = build_manager(_environment(tmp_path, activation_aware=False))

    assert manager.required_sources == tuple(
        authority.logical_name
        for authority in CANONICAL_BACKUP_AUTHORITIES
        if authority.required_for_platform_recovery
    )
    assert manager.validate_sources()["status"] == "blocked"


def test_unknown_persisted_activation_fails_closed(tmp_path: Path) -> None:
    state_path = tmp_path / "backup-authority-activation.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": "canonical-backup-authority-activation.v1",
                "activated_logical_names": ["unknown-authority"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown authorities"):
        build_manager(_environment(tmp_path))


def test_render_blueprint_enables_activation_aware_backup_policy() -> None:
    source = Path("render.yaml").read_text(encoding="utf-8")

    assert (
        "- key: CAPITAL_INTELLIGENCE_BACKUP_ACTIVATION_AWARE\n"
        "        value: \"true\""
    ) in source
