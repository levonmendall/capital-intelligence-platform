"""Operational resilience CLI tests."""

from __future__ import annotations

import json

from operations import ResilienceExerciseKind
from run_resilience_exercises import main


def _suite(path, *, complete: bool = True):
    kinds = tuple(ResilienceExerciseKind)
    if not complete:
        kinds = kinds[:-1]
    path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "identifier": f"scenario:{kind.value}",
                        "kind": kind.value,
                        "description": kind.value,
                        "expected_invariants": ["journal_hash", "portfolio_state"],
                    }
                    for kind in kinds
                ]
            }
        ),
        encoding="utf-8",
    )


def test_cli_records_passing_campaign(tmp_path, capsys) -> None:
    suite = tmp_path / "suite.json"
    _suite(suite)
    database = tmp_path / "resilience.db"
    code = main(
        [
            "--suite", str(suite),
            "--provider", "tests.resilience_factories:build_passing_provider",
            "--database", str(database),
            "--evaluated-at", "2026-07-27T13:00:00+00:00",
            "--record",
            "--require-passed",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["release_gate_passed"] is True
    assert payload["real_money_authorized"] is False
    assert database.exists()


def test_cli_fails_closed_for_incomplete_suite(tmp_path, capsys) -> None:
    suite = tmp_path / "suite.json"
    _suite(suite, complete=False)
    code = main(
        [
            "--suite", str(suite),
            "--provider", "tests.resilience_factories:build_passing_provider",
            "--evaluated-at", "2026-07-27T13:00:00+00:00",
            "--require-passed",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 3
    assert payload["release_gate_passed"] is False
