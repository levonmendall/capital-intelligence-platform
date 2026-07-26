"""Offline operational runner tests for security-master status."""

from __future__ import annotations

import json

from run_security_master import main


def test_status_command_reports_non_ready_empty_store(tmp_path, capsys) -> None:
    path = tmp_path / "security-master.db"

    result = main(["--database", str(path), "--status"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["screening_ready"] is False
    assert payload["catalog_integrity_verified"] is True
    assert payload["operation_integrity_verified"] is True
    assert payload["active_catalog_identifier"] is None
    assert payload["latest_ingestion"] is None
    assert payload["latest_activation"] is None
    assert payload["reasons"] == [
        "no authoritative security-master catalog is activated"
    ]
