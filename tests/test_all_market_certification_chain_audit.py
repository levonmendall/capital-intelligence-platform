from __future__ import annotations

import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import api.routes.cio_diagnostic as cio_route
import operations.all_market_certification_readonly as readonly
from operations.manual_cio_diagnostic import _PROGRESS_STAGES


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def test_readonly_resolver_does_not_require_certification_advancement_authority(
    tmp_path: Path, monkeypatch
) -> None:
    release = "abc123"
    cutoff = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    ledger_body = {
        "schema_version": "all-market-certification-input.v2",
        "record_id": "cert-1",
        "release": release,
        "snapshot_cutoff": cutoff.isoformat(),
    }
    ledger = {**ledger_body, "integrity_sha256": _digest(ledger_body)}
    path = (
        tmp_path
        / "all-market-certification-v2"
        / "ledger"
        / release
        / "latest-input.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(ledger), encoding="utf-8")

    sentinel = object()
    calls: list[datetime] = []

    def fake_resolve(value, *, values):
        calls.append(value)
        assert values["RENDER"] == "true"
        assert values["CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION"] == "true"
        return sentinel

    monkeypatch.setattr(readonly, "resolve_certification_for_cutoff", fake_resolve)
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": release,
        "RENDER": "true",
        "CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION": "true",
    }

    assert readonly.resolve_latest_certification_readonly(values=values) is sentinel
    assert calls == [cutoff]


def _certified_payload() -> dict[str, object]:
    return {
        "all_market_runtime_certified": True,
        "all_market_certification_integrity_valid": True,
        "all_market_certification_release_matches": True,
        "all_market_certification_v2_available": True,
        "all_market_certification_v2_input_integrity_valid": True,
        "all_market_certification_v2_state_integrity_valid": True,
        "all_market_certification_v2_release_matches": True,
        "all_market_evidence_certified": True,
        "all_market_screening_certified": True,
        "all_market_committee_certified": True,
        "all_market_cio_certified": True,
        "all_market_construction_certified": True,
        "all_market_paper_implementation_certified": False,
        "all_market_no_action_certified": True,
        "all_market_operational_certified": True,
        "all_market_comprehensive_discovery_complete": True,
        "all_market_scheduled_market_coverage_complete": True,
        "all_market_terminal_screening_complete": True,
        "all_market_certified_lanes": [
            {
                "asset_class": "us_equity",
                "scheduled": True,
                "catalog_count": 10,
                "deep_analyzed_count": 10,
                "selected_count": 1,
                "represented": True,
                "terminal_accounting_complete": True,
            }
        ],
    }


def test_capability_scoped_context_can_be_ready_only_with_independent_certification(
    monkeypatch, tmp_path: Path
) -> None:
    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    diagnostic = SimpleNamespace(
        state="completed",
        requested_by="render-release:abc123",
        request_id="diag-1",
        requested_at=now,
        started_at=now,
        completed_at=now,
        progress_stage="six_specialist_committee_cio_cycle",
        progress_metrics=(),
        progress_recorded_at=now,
        cycle_key="cycle-1",
        snapshot_identifier="snapshot-1",
        detail="complete",
    )
    context = {
        "cycle_key": "cycle-1",
        "decision_as_of": now.isoformat(),
        "comprehensive_discovery_required": True,
        "comprehensive_discovery_scope_state": "capability_scoped",
        "instrument_count": 3,
        "candidate_count": 1,
        "exclusion_count": 2,
        "qualified_candidate_count": 1,
    }
    monkeypatch.setattr(
        cio_route,
        "public_all_market_certification_readonly",
        lambda values: _certified_payload(),
    )
    monkeypatch.setattr(
        cio_route,
        "latest_manual_cio_diagnostic",
        lambda values: diagnostic,
    )
    monkeypatch.setattr(
        cio_route,
        "_state_path",
        lambda settings: tmp_path / "state.json",
    )
    monkeypatch.setattr(cio_route, "_load_json", lambda path: context)
    monkeypatch.setattr(
        cio_route,
        "_latest_context_attempt",
        lambda settings: {
            "state": "ready",
            "cycle_key": "cycle-1",
            "started_at": now.isoformat(),
        },
    )
    monkeypatch.setattr(
        cio_route,
        "_safe_public_requirement_progress",
        lambda values: None,
    )
    monkeypatch.setattr(
        cio_route,
        "_certification_context_matches",
        lambda *args, **kwargs: (True, True),
    )

    payload = cio_route.build_cio_diagnostic_audit(
        settings=SimpleNamespace(portfolio_database=tmp_path / "portfolio.db"),
        values={
            "CAPITAL_INTELLIGENCE_RELEASE": "abc123",
            "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true",
        },
    )

    assert payload["ready"] is True
    assert payload["production_context_discovery_scope_state"] == "capability_scoped"
    assert payload["comprehensive_discovery_complete"] is True
    assert payload["scheduled_market_coverage_complete"] is True
    assert payload["terminal_screening_complete"] is True
    assert payload["market_lanes"][0]["asset_class"] == "us_equity"


def test_all_market_ready_requires_terminal_certified_outcome(
    monkeypatch, tmp_path: Path
) -> None:
    payload = _certified_payload()
    payload["all_market_no_action_certified"] = False
    payload["all_market_paper_implementation_certified"] = False
    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    diagnostic = SimpleNamespace(
        state="completed",
        requested_by="render-release:abc123",
        request_id="diag-1",
        requested_at=now,
        started_at=now,
        completed_at=now,
        progress_stage="six_specialist_committee_cio_cycle",
        progress_metrics=(),
        progress_recorded_at=now,
        cycle_key="cycle-1",
        snapshot_identifier="snapshot-1",
        detail="complete",
    )
    monkeypatch.setattr(
        cio_route,
        "public_all_market_certification_readonly",
        lambda values: payload,
    )
    monkeypatch.setattr(
        cio_route,
        "latest_manual_cio_diagnostic",
        lambda values: diagnostic,
    )
    monkeypatch.setattr(
        cio_route,
        "_state_path",
        lambda settings: tmp_path / "state.json",
    )
    monkeypatch.setattr(
        cio_route,
        "_load_json",
        lambda path: {
            "cycle_key": "cycle-1",
            "decision_as_of": now.isoformat(),
            "comprehensive_discovery_required": True,
            "comprehensive_discovery_scope_state": "capability_scoped",
        },
    )
    monkeypatch.setattr(cio_route, "_latest_context_attempt", lambda settings: {})
    monkeypatch.setattr(
        cio_route,
        "_safe_public_requirement_progress",
        lambda values: None,
    )
    monkeypatch.setattr(
        cio_route,
        "_certification_context_matches",
        lambda *args, **kwargs: (True, True),
    )

    result = cio_route.build_cio_diagnostic_audit(
        settings=SimpleNamespace(portfolio_database=tmp_path / "portfolio.db"),
        values={
            "CAPITAL_INTELLIGENCE_RELEASE": "abc123",
            "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true",
        },
    )
    assert result["ready"] is False


def test_every_production_context_progress_literal_is_registered() -> None:
    root = Path(__file__).resolve().parents[1]
    producers = (
        root / "production_context_publication_runtime.py",
        root / "production_context_publication_governed.py",
        root / "_manual_cio_diagnostic_core.py",
        root / "run_bounded_manual_cio_diagnostic.py",
        root / "run_bounded_manual_cio_diagnostic_core.py",
    )
    emitted: set[str] = set()
    for path in producers:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            else:
                func_name = ""
            if "progress" not in func_name:
                continue
            candidates = list(node.args) + [
                kw.value
                for kw in node.keywords
                if kw.arg == "progress_stage"
            ]
            for candidate in candidates:
                if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
                    if candidate.value.startswith("production_context_"):
                        emitted.add(candidate.value)
    assert emitted
    assert emitted <= _PROGRESS_STAGES, (
        f"unregistered progress stages: {sorted(emitted - _PROGRESS_STAGES)}"
    )
