from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import publish_cio_diagnostic_audit as publisher


def _analytical_payload(*, operational: bool = False) -> dict[str, object]:
    return {
        "schema_version": "public-cio-diagnostic-audit.v2-end-to-end",
        "credential_safe": True,
        "ready": True,
        "state": "completed",
        "active_release": "release-test",
        "release_matches": True,
        "request_id": "request-test",
        "requested_at": "2026-08-15T05:00:00+00:00",
        "completed_at": "2026-08-15T05:01:00+00:00",
        "stage": "paper_implementation_boundary",
        "detail": "analytical certification complete; paper implementation pending",
        "context_cycle_matches": True,
        "comprehensive_discovery_complete": True,
        "scheduled_market_coverage_complete": True,
        "terminal_screening_complete": True,
        "all_market_evaluation_complete": True,
        "all_market_runtime_certified": True,
        "all_market_certification_context_matches": True,
        "all_market_certification_v2_context_matches": True,
        "all_market_certification_v2_state": (
            "CERTIFIED" if operational else "CONSTRUCTION_COMPLETE"
        ),
        "all_market_construction_certified": True,
        "all_market_paper_implementation_certified": False,
        "all_market_no_action_certified": operational,
        "all_market_operational_certified": operational,
        "market_lanes": [],
        "paper_only": True,
        "real_money_authorized": False,
    }


def _install_common(monkeypatch, payload: dict[str, object]) -> None:
    monkeypatch.setattr(
        publisher.ApiSettings,
        "from_env",
        lambda _values: SimpleNamespace(),
    )
    monkeypatch.setattr(
        publisher,
        "build_cio_diagnostic_audit",
        lambda **_: dict(payload),
    )
    monkeypatch.setattr(
        publisher,
        "load_reference_readiness_progress",
        lambda _values: None,
    )
    monkeypatch.setattr(
        publisher,
        "load_release_evidence_prequalification",
        lambda _values: None,
    )


def test_static_render_audit_does_not_require_terminal_paper_implementation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    payload = _analytical_payload(operational=False)
    _install_common(monkeypatch, payload)
    output = tmp_path / "static" / "cio-diagnostic.json"
    values = {
        "CAPITAL_INTELLIGENCE_CIO_DIAGNOSTIC_PUBLIC_AUDIT_PATH": str(output),
    }

    published = publisher.publish_cio_diagnostic_audit(values=values)

    assert published["ready"] is True
    assert published["all_market_evaluation_complete"] is True
    assert published["all_market_construction_certified"] is True
    assert published["all_market_operational_certified"] is False
    assert published["paper_implementation_complete"] is False
    assert json.loads(output.read_text(encoding="utf-8")) == published


def test_static_render_audit_reports_terminal_no_action_independently(
    monkeypatch,
    tmp_path: Path,
) -> None:
    payload = _analytical_payload(operational=True)
    _install_common(monkeypatch, payload)
    output = tmp_path / "static" / "cio-diagnostic.json"
    values = {
        "CAPITAL_INTELLIGENCE_CIO_DIAGNOSTIC_PUBLIC_AUDIT_PATH": str(output),
    }

    published = publisher.publish_cio_diagnostic_audit(values=values)

    assert published["ready"] is True
    assert published["all_market_evaluation_complete"] is True
    assert published["all_market_operational_certified"] is True
    assert published["all_market_no_action_certified"] is True
    assert published["paper_implementation_complete"] is True
