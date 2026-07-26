"""CLI boundary tests for complete-universe screening."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from run_full_universe_screening import main


class MetricsProvider:
    name = "CLI_METRICS"

    def fetch_metrics(self, snapshot):
        return ()


class CandidateProvider:
    name = "CLI_CANDIDATES"

    def screen(self, constituent, *, as_of, opportunity_cost_return):
        raise AssertionError("candidate screening must not run without an active catalog")


def test_cli_fails_closed_without_certified_active_catalog(tmp_path, monkeypatch, capsys) -> None:
    module = types.ModuleType("screening_cli_fixtures")
    module.build_metrics = lambda: MetricsProvider()
    module.build_candidates = lambda: CandidateProvider()
    monkeypatch.setitem(sys.modules, module.__name__, module)
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps(
            {
                "identifier": "context:cli",
                "as_of": "2026-07-26T12:00:00+00:00",
                "alternatives": [
                    {
                        "identifier": "cash",
                        "kind": "cash",
                        "expected_return": 0.04,
                        "implementation_cost_return": 0.0,
                        "evidence_quality": 1.0,
                        "liquidity_score": 1.0,
                        "current_weight": 1.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    security_master = tmp_path / "security-master.db"
    screening = tmp_path / "screening.db"
    slo = tmp_path / "slo.db"
    journal = tmp_path / "journal.db"

    result = main(
        [
            "--cycle-id",
            "cycle:cli",
            "--scheduled-for",
            "2026-07-26T11:00:00+00:00",
            "--as-of",
            "2026-07-26T12:00:00+00:00",
            "--knowledge-cutoff",
            "2026-07-26T12:00:00+00:00",
            "--started-at",
            "2026-07-26T12:00:01+00:00",
            "--context",
            str(context),
            "--metrics-provider",
            "screening_cli_fixtures:build_metrics",
            "--candidate-provider",
            "screening_cli_fixtures:build_candidates",
            "--security-master-database",
            str(security_master),
            "--screening-database",
            str(screening),
            "--slo-database",
            str(slo),
            "--journal-database",
            str(journal),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 3
    assert payload["status"] == "failed"
    assert "no security-master catalog has been activated" in payload["error"]
    assert screening.exists()
    assert slo.exists()
    assert journal.exists()


def test_cli_rejects_invalid_factory_syntax(tmp_path) -> None:
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps(
            {
                "identifier": "context:invalid",
                "as_of": "2026-07-26T12:00:00+00:00",
                "alternatives": [
                    {
                        "identifier": "cash",
                        "kind": "cash",
                        "expected_return": 0.04,
                        "implementation_cost_return": 0.0,
                        "evidence_quality": 1.0,
                        "liquidity_score": 1.0,
                        "current_weight": 1.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    try:
        main(
            [
                "--cycle-id",
                "cycle:cli",
                "--scheduled-for",
                "2026-07-26T11:00:00+00:00",
                "--as-of",
                "2026-07-26T12:00:00+00:00",
                "--knowledge-cutoff",
                "2026-07-26T12:00:00+00:00",
                "--context",
                str(context),
                "--metrics-provider",
                "invalid",
                "--candidate-provider",
                "invalid",
            ]
        )
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("invalid provider factory must terminate argument parsing")
