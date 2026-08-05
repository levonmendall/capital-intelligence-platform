from __future__ import annotations

import json
from pathlib import Path

import publish_cio_diagnostic_audit as publisher


def test_publish_writes_only_redacted_audit_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "static" / "cio-diagnostic.json"
    values = {
        "CAPITAL_INTELLIGENCE_CIO_DIAGNOSTIC_PUBLIC_AUDIT_PATH": str(output),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-123",
    }
    settings = object()
    monkeypatch.setattr(
        publisher.ApiSettings,
        "from_env",
        lambda resolved: settings,
    )
    monkeypatch.setattr(
        publisher,
        "build_cio_diagnostic_audit",
        lambda **kwargs: {
            "ready": False,
            "state": "failed",
            "active_release": "release-123",
            "all_market_evaluation_complete": False,
            "market_lanes": [
                {
                    "asset_class": "crypto",
                    "scheduled": True,
                    "catalog_count": 5,
                    "deep_analyzed_count": 5,
                    "selected_count": 2,
                    "represented": True,
                }
            ],
            "paper_only": True,
            "real_money_authorized": False,
        },
    )

    payload = publisher.publish_cio_diagnostic_audit(values=values)
    persisted = json.loads(output.read_text(encoding="utf-8"))

    assert payload == persisted
    assert persisted["schema_version"] == "public-cio-diagnostic-audit.v1"
    assert persisted["credential_safe"] is True
    assert persisted["active_release"] == "release-123"
    assert persisted["market_lanes"][0]["asset_class"] == "crypto"
    assert persisted["paper_only"] is True
    assert persisted["real_money_authorized"] is False
    assert "holdings" not in persisted
    assert "target_weights" not in persisted
    assert "recommendations" not in persisted


def test_default_audit_path_is_streamlit_static_directory() -> None:
    assert publisher.audit_output_path({}) == Path("static/cio-diagnostic.json")
