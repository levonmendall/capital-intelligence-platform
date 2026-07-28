"""CLI tests for append-only asset-specific evidence operations."""

from __future__ import annotations

import json

from cio import CandidateAssetClass
from run_asset_specific_evidence import main
from tests.test_multi_asset_evidence import AS_OF, _packet


def test_asset_specific_evidence_cli_appends_and_reads_cycle(
    tmp_path, capsys
) -> None:
    database = tmp_path / "asset-evidence.db"
    packet = _packet(CandidateAssetClass.CRYPTO)
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps(packet.to_dict()), encoding="utf-8")

    assert main(
        [
            "--packet",
            str(packet_path),
            "--database",
            str(database),
        ]
    ) == 0
    appended = json.loads(capsys.readouterr().out)
    assert appended["identifier"] == packet.identifier
    assert appended["registry_sequence"] == 1

    assert main(
        [
            "--cycle",
            packet.screening_cycle_identifier,
            "--as-of",
            AS_OF.isoformat(),
            "--database",
            str(database),
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["packet_count"] == 1
    assert result["packets"][0]["identifier"] == packet.identifier
    assert result["real_money_authorized"] is False


def test_asset_specific_evidence_cli_requires_cycle_timestamp(
    tmp_path, capsys
) -> None:
    result = main(
        [
            "--cycle",
            "screening:missing-time",
            "--database",
            str(tmp_path / "asset-evidence.db"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 3
    assert payload["status"] == "blocked"
    assert "--as-of is required" in payload["error"]
