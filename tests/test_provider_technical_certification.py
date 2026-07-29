from __future__ import annotations

import json
from pathlib import Path

from run_provider_technical_certification import main


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_technical_certification_keeps_legal_authority_pending(tmp_path: Path) -> None:
    credential = tmp_path / "credential.json"
    runtime = tmp_path / "runtime.json"
    databento = tmp_path / "databento.json"
    output = tmp_path / "certification.json"
    _write(
        credential,
        {
            "configured_provider_count": 7,
            "passed_provider_count": 7,
            "blockers": [],
        },
    )
    provider_names = [
        "alpaca_paper",
        "fred",
        "databento",
        "eodhd",
        "openfigi",
        "alpha_vantage",
        "twelve_data",
        "coinbase_exchange",
        "kraken_spot",
    ]
    _write(
        runtime,
        {
            "providers": [
                {
                    "provider": name,
                    "runtime_ready": True,
                    "license_approval_input_present": False,
                    "certification_input_present": False,
                }
                for name in provider_names
            ]
        },
    )
    _write(
        databento,
        {
            "configured": True,
            "dataset_count": 29,
            "available_binding_count": 4,
            "state": "partial",
        },
    )
    result = main(
        [
            "--credential-report",
            str(credential),
            "--runtime-report",
            str(runtime),
            "--databento-report",
            str(databento),
            "--as-of",
            "2026-07-28T22:00:00+00:00",
            "--output",
            str(output),
            "--require-technical-ready",
        ]
    )
    assert result == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["state"] == "technical_ready_legal_pending"
    assert payload["technical_ready"] is True
    assert payload["provider_activation_granted"] is False
    assert "human_license_approval_inputs_missing" in payload["blockers"]
    assert len(payload["report_sha256"]) == 64
