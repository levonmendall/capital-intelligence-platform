"""Operational configured dataset retrieval tests."""

from __future__ import annotations

import json

from run_configured_dataset_provider import main


def test_configured_dataset_cli_reads_file_binding(tmp_path, capsys) -> None:
    response = tmp_path / "response.json"
    response.write_text(
        json.dumps(
            {
                "data": [{"symbol": "ACME", "price": 10.0}],
                "meta": {
                    "observed_at": "2026-07-28T01:00:00+00:00",
                    "available_at": "2026-07-28T01:01:00+00:00",
                    "request_id": "request:1",
                },
            }
        ),
        encoding="utf-8",
    )
    binding = tmp_path / "binding.json"
    binding.write_text(
        json.dumps(
            {
                "schema_version": "configured-dataset-provider.v1",
                "provider_identifier": "fixture-provider",
                "source_version": "fixture.v1",
                "base_url": tmp_path.as_uri() + "/",
                "bindings": [
                    {
                        "dataset_type": "market_prices",
                        "path": response.name,
                        "payload_path": "data",
                        "observed_at_path": "meta.observed_at",
                        "available_at_path": "meta.available_at",
                        "provider_record_id_path": "meta.request_id",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = main(
        [
            "--binding",
            str(binding),
            "--type",
            "market_prices",
            "--provider-symbol",
            "ACME",
            "--as-of",
            "2026-07-28T01:05:00+00:00",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["provider"] == "fixture-provider"
    assert payload["payload"][0]["symbol"] == "ACME"
    assert payload["provider_record_id"] == "request:1"
    assert payload["secret_values_disclosed"] is False
    assert payload["real_money_authorized"] is False
