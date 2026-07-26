from __future__ import annotations

import json
import sys
import types
from datetime import timedelta

from cio.persistence import SQLiteCIOJournal
from run_thesis_monitoring import main
from tests.cio_test_fixtures import AS_OF, build_candidate, build_decision
from thesis import LivingThesis, ThesisEvidenceUpdate


class Provider:
    def update_for(self, thesis, *, as_of, opportunity_context):
        return ThesisEvidenceUpdate(
            thesis_identifier=thesis.identifier,
            as_of=as_of,
            expected_return=thesis.expected_return,
            expected_downside=thesis.expected_downside,
            confidence=thesis.current_confidence,
            evidence_identifiers=("evidence:cli",),
            strengthened_indicators=(),
            weakened_indicators=(),
            triggered_invalidation_conditions=(),
            data_current=True,
            performance_since_approval=0.0,
            best_replacement_expected_return=thesis.expected_return,
            next_review_at=as_of + timedelta(days=30),
        )


def _module(monkeypatch):
    module = types.ModuleType("thesis_monitoring_cli_fixtures")
    module.build_provider = lambda: Provider()
    monkeypatch.setitem(sys.modules, module.__name__, module)


def test_cli_runs_due_scheduled_review(tmp_path, monkeypatch, capsys):
    _module(monkeypatch)
    journal_path = tmp_path / "journal.db"
    journal = SQLiteCIOJournal(journal_path)
    candidate = build_candidate()
    thesis = LivingThesis.from_decision(candidate, build_decision(candidate))
    journal.append_thesis_snapshot(thesis)

    code = main(
        [
            "--evidence-provider",
            "thesis_monitoring_cli_fixtures:build_provider",
            "--as-of",
            (AS_OF + timedelta(days=31)).isoformat(),
            "--journal-database",
            str(journal_path),
            "--monitoring-database",
            str(tmp_path / "monitoring.db"),
            "--require-all-success",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["status"] == "completed"
    assert payload["results"][0]["required_cio_review"] is False


def test_cli_event_file_fails_missing_thesis_with_nonzero_required_status(tmp_path, monkeypatch, capsys):
    _module(monkeypatch)
    journal_path = tmp_path / "journal.db"
    SQLiteCIOJournal(journal_path)
    trigger_path = tmp_path / "triggers.json"
    trigger_path.write_text(
        json.dumps(
            [
                {
                    "identifier": "trigger:cli:missing",
                    "thesis_identifier": "thesis:missing",
                    "source": "event",
                    "as_of": (AS_OF + timedelta(days=1)).isoformat(),
                    "reason": "Test missing thesis",
                    "evidence_fingerprint": "missing",
                }
            ]
        ),
        encoding="utf-8",
    )
    code = main(
        [
            "--evidence-provider",
            "thesis_monitoring_cli_fixtures:build_provider",
            "--trigger-file",
            str(trigger_path),
            "--events-only",
            "--journal-database",
            str(journal_path),
            "--monitoring-database",
            str(tmp_path / "monitoring.db"),
            "--require-all-success",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 3
    assert payload["status"] == "completed_with_failures"


def test_cli_rejects_invalid_factory():
    try:
        main(["--evidence-provider", "invalid"])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("invalid factory syntax must terminate parsing")
