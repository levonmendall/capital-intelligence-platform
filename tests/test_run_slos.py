"""Operational SLO command-line contract tests."""

from __future__ import annotations

import json

from operations import SQLiteOperationalSLOStore
from run_slos import main


def test_run_slos_reports_blocked_state_without_creating_authority(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    result = main([])
    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["ready"] is False
    assert {item["name"] for item in payload["components"]} == {
        "provider_freshness",
        "full_universe_cycle_completion",
        "thesis_review_latency",
        "decision_evaluation_latency",
    }
    assert main(["--require-ready"]) == 3


def test_run_slos_records_terminal_cycle_and_assessment(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    args = [
        "--record-assessment",
        "--cycle-status",
        "failed",
        "--cycle-id",
        "cycle:2026-07-27",
        "--scheduled-for",
        "2026-07-27T11:00:00+00:00",
        "--started-at",
        "2026-07-27T11:00:00+00:00",
        "--completed-at",
        "2026-07-27T11:30:00+00:00",
        "--error",
        "authoritative provider unavailable",
        "--evaluated-at",
        "2026-07-27T12:00:00+00:00",
    ]
    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["recorded_cycle"]["status"] == "failed"
    store = SQLiteOperationalSLOStore(tmp_path / "operational_slos.db", initialize=False)
    assert store.cycles()[0].identifier == "cycle:2026-07-27"
    assert store.latest_snapshot() is not None
