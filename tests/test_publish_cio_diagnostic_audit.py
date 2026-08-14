from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import publish_cio_diagnostic_audit as publisher


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(portfolio_database=tmp_path / "canonical_portfolio.db")


def test_publish_writes_only_redacted_audit_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "static" / "cio-diagnostic.json"
    values = {
        "CAPITAL_INTELLIGENCE_CIO_DIAGNOSTIC_PUBLIC_AUDIT_PATH": str(output),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-123",
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
    }
    settings = _settings(tmp_path)
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
            "stage": "terminal_screening:crypto",
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
    assert persisted["schema_version"] == "public-cio-diagnostic-audit.v2-end-to-end"
    assert persisted["credential_safe"] is True
    assert persisted["active_release"] == "release-123"
    assert persisted["market_lanes"][0]["asset_class"] == "crypto"
    assert persisted["paper_only"] is True
    assert persisted["real_money_authorized"] is False
    assert persisted["stage"] == "terminal_screening:crypto"
    assert "holdings" not in persisted
    assert "target_weights" not in persisted
    assert "recommendations" not in persisted


def test_publish_surfaces_pre_cio_reference_progress_when_canonical_stage_is_absent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "static" / "cio-diagnostic.json"
    values = {
        "CAPITAL_INTELLIGENCE_CIO_DIAGNOSTIC_PUBLIC_AUDIT_PATH": str(output),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-reference",
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
    }
    progress_dir = tmp_path / "reference_readiness"
    progress_dir.mkdir(parents=True)
    material = {
        "schema_version": "governed-reference-progress.v1",
        "release": "release-reference",
        "stage": "reference_futures_contracts",
        "progress_metrics": {"configured_futures_roots": 6, "reused": 0},
        "updated_at": "2026-08-13T23:16:00+00:00",
        "paper_only": True,
        "real_money_authorized": False,
        "credential_safe": True,
    }
    progress = dict(material)
    progress["progress_id"] = publisher.load_reference_readiness_progress.__globals__[
        "_fingerprint"
    ](material)
    (progress_dir / "progress-release-reference.json").write_text(
        json.dumps(progress), encoding="utf-8"
    )
    monkeypatch.setattr(
        publisher.ApiSettings,
        "from_env",
        lambda _resolved: _settings(tmp_path),
    )
    monkeypatch.setattr(
        publisher,
        "build_cio_diagnostic_audit",
        lambda **_kwargs: {
            "ready": False,
            "state": "pending",
            "stage": None,
            "progress_metrics": {},
            "active_release": "release-reference",
            "all_market_evaluation_complete": False,
            "market_lanes": [],
            "paper_only": True,
            "real_money_authorized": False,
        },
    )

    payload = publisher.publish_cio_diagnostic_audit(values=values)

    assert payload["stage"] == "reference_futures_contracts"
    assert payload["progress_metrics"] == {
        "configured_futures_roots": 6,
        "reused": 0,
    }
    assert payload["reference_progress"] is True


def test_default_audit_path_is_streamlit_static_directory() -> None:
    assert publisher.audit_output_path({}) == Path("static/cio-diagnostic.json")
