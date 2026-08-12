from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from provider_environment import normalize_provider_environment
from providers.cme_datamine_span import (
    CmeDataMineSpanClient,
    DOWNLOAD_URL,
    LIST_URL,
    TOKEN_URL,
)
from providers.free_derivative_risk import CmeSpanRiskProvider, FreeDerivativeRiskError


NOW = datetime(2026, 8, 11, 22, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, *, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self):
        return self._payload


def _catalog(tmp_path: Path) -> Path:
    path = tmp_path / "cme-span.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "cme-span-datamine-file-ids.v1",
                "dataset_name": "All CME Group Exchanges - SPAN Risk Parameter Files",
                "file_id_patterns": [
                    "{YYYYMMDD}-SPAN_CUSTPA2TCC_X_CME_0",
                    "{YYYYMMDD}-SPAN_CUSTPA2TCC_S_CME_0",
                    "{YYYYMMDD}-SPAN_CUSTSPNTCC_I_CME_0",
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_datamine_client_authenticates_lists_and_prefers_final_eod_pa2(tmp_path) -> None:
    calls: list[tuple[str, object]] = []
    final_id = "20260811-SPAN_CUSTPA2TCC_S_CME_0"
    x_id = "20260811-SPAN_CUSTPA2TCC_X_CME_0"

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        assert url == TOKEN_URL
        assert kwargs["auth"] == ("api-id", "api-password")
        assert kwargs["data"] == {"grant_type": "client_credentials"}
        return FakeResponse(payload={"access_token": "short-lived-token"})

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        assert kwargs["headers"]["Authorization"] == "Bearer short-lived-token"
        if url == LIST_URL:
            assert kwargs["params"]["period_date"] == "20260811"
            return FakeResponse(
                payload={
                    "data": [
                        {
                            "period_date": "20260811",
                            "files": [
                                {
                                    "file_id": x_id,
                                    "file_name": "cme.20260811.x.pa2.zip",
                                    "api_download_link": f"{DOWNLOAD_URL}?fid={x_id}",
                                    "size": 100,
                                },
                                {
                                    "file_id": final_id,
                                    "file_name": "cme.20260811.s.pa2.zip",
                                    "api_download_link": f"{DOWNLOAD_URL}?fid={final_id}",
                                    "size": 120,
                                },
                            ],
                        }
                    ],
                    "paging": {"next": "", "previous": ""},
                }
            )
        assert url == f"{DOWNLOAD_URL}?fid={final_id}"
        return FakeResponse(content=b"SPAN-FINAL-EOD-PARAMETERS" * 4)

    result = CmeDataMineSpanClient(
        "api-id",
        "api-password",
        catalog_path=_catalog(tmp_path),
        http_get=fake_get,
        http_post=fake_post,
    ).fetch_latest(as_of=NOW)

    assert result.file.file_id == final_id
    assert result.entitled_match_count == 2
    assert result.catalog_pattern_count == 3
    assert result.selection_policy == "final-eod-pa2-preferred.v1"
    assert result.content.startswith(b"SPAN-FINAL-EOD")
    assert calls[0][0] == TOKEN_URL


def test_list_api_5xx_uses_bounded_exact_file_api_fallback(tmp_path) -> None:
    final_id = "20260811-SPAN_CUSTPA2TCC_S_CME_0"
    direct_calls: list[str] = []

    def fake_post(url, **kwargs):
        assert url == TOKEN_URL
        return FakeResponse(payload={"access_token": "short-lived-token"})

    def fake_get(url, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer short-lived-token"
        if url == LIST_URL:
            return FakeResponse(status_code=502, payload={"error": "gateway"})
        assert url == DOWNLOAD_URL
        file_id = kwargs["params"]["fid"]
        direct_calls.append(file_id)
        if file_id == final_id:
            return FakeResponse(content=b"SPAN-DIRECT-FILE-API-PARAMETERS" * 4)
        return FakeResponse(status_code=404)

    result = CmeDataMineSpanClient(
        "api-id",
        "api-password",
        catalog_path=_catalog(tmp_path),
        maximum_direct_probes_per_date=2,
        http_get=fake_get,
        http_post=fake_post,
    ).fetch_latest(as_of=NOW)

    assert result.file.file_id == final_id
    assert result.entitled_match_count == 1
    assert result.catalog_pattern_count == 3
    assert result.selection_policy == "list-5xx-direct-file-fallback.v1"
    assert result.content.startswith(b"SPAN-DIRECT-FILE-API")
    assert direct_calls == [final_id]


def test_cme_span_provider_publishes_credential_safe_datamine_lineage(monkeypatch) -> None:
    final_id = "20260811-SPAN_CUSTPA2TCC_S_CME_0"

    def fake_post(url, **kwargs):
        return FakeResponse(payload={"access_token": "short-lived-token"})

    def fake_get(url, **kwargs):
        if url == LIST_URL:
            return FakeResponse(
                payload={
                    "data": [
                        {
                            "period_date": "20260811",
                            "files": [
                                {
                                    "file_id": final_id,
                                    "file_name": "cme.20260811.s.pa2.zip",
                                    "api_download_link": f"{DOWNLOAD_URL}?fid={final_id}",
                                    "size": 100,
                                }
                            ],
                        }
                    ],
                    "paging": {"next": "", "previous": ""},
                }
            )
        return FakeResponse(content=b"CME SPAN RISK PARAMETER DATA" * 4)

    provider = CmeSpanRiskProvider(
        api_id="api-id",
        api_password="api-password",
        http_get=fake_get,
        http_post=fake_post,
    )
    payload = provider.fetch(as_of=NOW).to_dict()

    assert payload["access_mode"] == "cme-datamine-api"
    assert payload["source_file_id"] == final_id
    assert payload["catalog_pattern_count"] == 30
    assert payload["individual_margin_requirement_inferred"] is False
    assert payload["decision_authority_granted"] is False
    assert payload["execution_authority_granted"] is False
    serialized = str(payload)
    assert "api-id" not in serialized
    assert "api-password" not in serialized
    assert "short-lived-token" not in serialized


def test_partial_datamine_credentials_fail_closed() -> None:
    provider = CmeSpanRiskProvider(api_id="only-id", api_password=None)
    with pytest.raises(FreeDerivativeRiskError, match="both API ID and API password"):
        provider.fetch(as_of=NOW)


def test_cme_datamine_aliases_and_render_slots_are_declared() -> None:
    normalized = normalize_provider_environment(
        {
            "CME_API_ID": "id",
            "CME_API_PASSWORD": "password",
        }
    )
    assert normalized["CAPITAL_INTELLIGENCE_CME_DATAMINE_API_ID"] == "id"
    assert normalized["CAPITAL_INTELLIGENCE_CME_DATAMINE_API_PASSWORD"] == "password"

    render_text = Path("render.yaml").read_text(encoding="utf-8")
    assert "- key: CAPITAL_INTELLIGENCE_CME_DATAMINE_API_ID" in render_text
    assert "- key: CAPITAL_INTELLIGENCE_CME_DATAMINE_API_PASSWORD" in render_text
    assert "value: config/cme_span_datamine_file_ids.json" in render_text
