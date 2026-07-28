from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.routes.governance import public_live_information


def test_public_live_route_returns_redacted_persisted_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = tmp_path / "public-live.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "public-live-information-report.v1",
                "catalog_identifier": "catalog:test",
                "successful_source_count": 8,
                "live_record_count": 120,
                "records": [{"should": "not be returned"}],
                "secret_values_disclosed": True,
                "full_article_text_stored": True,
                "real_money_authorized": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PUBLIC_LIVE_REPORT", str(report_path))

    payload = public_live_information()

    assert payload["catalog_identifier"] == "catalog:test"
    assert payload["successful_source_count"] == 8
    assert payload["live_record_count"] == 120
    assert "records" not in payload
    assert payload["secret_values_disclosed"] is False
    assert payload["full_article_text_stored"] is False
    assert payload["real_money_authorized"] is False


def test_public_live_route_returns_not_found_before_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_REPORT",
        str(tmp_path / "missing.json"),
    )

    with pytest.raises(HTTPException) as captured:
        public_live_information()

    assert captured.value.status_code == 404
