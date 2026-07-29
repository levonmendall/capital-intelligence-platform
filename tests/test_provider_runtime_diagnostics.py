from __future__ import annotations

import json
from pathlib import Path

from provider_runtime_diagnostics import (
    build_provider_runtime_report,
    merge_runtime_reports,
)


def test_runtime_report_identifies_aliases_and_bindings_without_values(tmp_path: Path) -> None:
    databento = tmp_path / "databento.json"
    eodhd = tmp_path / "eodhd.json"
    databento.write_text("{}", encoding="utf-8")
    eodhd.write_text("{}", encoding="utf-8")
    environment = {
        "GITHUB_ACTIONS": "true",
        "APCA_API_KEY_ID": "alpaca-key",
        "APCA_API_SECRET_KEY": "alpaca-secret",
        "FRED_API_KEY": "fred-secret",
        "SEC_USER_AGENT": "Capital Intelligence test@example.com",
        "DATABENTO_API_KEY": "db-secret",
        "EODHD_API_KEY": "eodhd-secret",
        "OPEN_FIGI_API_KEY": "figi-secret",
        "ALPHAVANTAGE_API_KEY": "alpha-secret",
        "TWELVE_API_KEY": "twelve-secret",
        "CAPITAL_INTELLIGENCE_DATABENTO_INSTRUMENT_BINDINGS": str(databento),
        "CAPITAL_INTELLIGENCE_EODHD_BINDINGS": str(eodhd),
    }
    report = build_provider_runtime_report(environment=environment)
    assert report["environment_name"] == "github_actions"
    assert report["state"] == "ready"
    databento_row = next(
        item for item in report["providers"] if item["provider"] == "databento"
    )
    assert databento_row["runtime_ready"] is True
    assert databento_row["selected_credential_names"] == [
        "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY"
    ]
    encoded = json.dumps(report)
    assert "db-secret" not in encoded
    assert "alpaca-secret" not in encoded


def test_runtime_reports_merge_into_environment_matrix() -> None:
    github = {
        "environment_name": "github_actions",
        "providers": [
            {
                "provider": "databento",
                "pipeline_role": "market_data",
                "runtime_ready": True,
                "credential_state": "configured",
                "binding_state": "configured",
                "blockers": [],
            }
        ],
    }
    streamlit = {
        "environment_name": "streamlit_runtime",
        "providers": [
            {
                "provider": "databento",
                "pipeline_role": "market_data",
                "runtime_ready": False,
                "credential_state": "missing",
                "binding_state": "configured",
                "blockers": ["credential_missing"],
            }
        ],
    }
    matrix = merge_runtime_reports((github, streamlit))
    availability = matrix["providers"][0]["availability_by_environment"]
    assert availability["github_actions"]["runtime_ready"] is True
    assert availability["streamlit_runtime"]["runtime_ready"] is False
