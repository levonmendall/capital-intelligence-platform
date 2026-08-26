"""Regressions for raw file-cache reclamation before reference retries."""

from __future__ import annotations

import run_stage_isolated_evidence_pipeline as coordinator


def test_reference_boundary_uses_bounded_broad_clean_cache_reclaimer(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_reclamation(values, **kwargs) -> None:
        captured["values"] = dict(values)
        captured.update(kwargs)

    monkeypatch.setattr(
        coordinator,
        "_run_completed_evidence_cache_reclamation",
        fake_reclamation,
    )

    coordinator._run_reference_cache_reclamation(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/capital-intelligence"}
    )

    assert captured["stage"] == "reference"
    assert captured["event"] == coordinator._REFERENCE_CACHE_RECLAMATION_EVENT
    assert captured["code"] == coordinator._COMPREHENSIVE_DISCOVERY_CACHE_RECLAMATION_CODE
    assert captured["capture_report"] is True


def test_reference_reclamation_remains_advisory(monkeypatch, capsys) -> None:
    class Completed:
        returncode = 9
        stdout = ""

    monkeypatch.setattr(coordinator.subprocess, "run", lambda *args, **kwargs: Completed())

    coordinator._run_reference_cache_reclamation(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/capital-intelligence"}
    )

    output = capsys.readouterr().out
    assert '"status": "failed"' in output
    assert '"advisory_only": true' in output
    assert '"evidence_certified": false' in output
    assert '"stage": "reference"' in output
