from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from evaluation.persistence import serialize_construction
from portfolio.execution import portfolio_to_dict
from run_paper_execution import main
from tests.test_paper_execution_orchestration import (
    AS_OF,
    _universe_store,
    construction,
    portfolio,
)


def _files(tmp_path):
    construction_path = tmp_path / "construction.json"
    portfolio_path = tmp_path / "portfolio.json"
    construction_path.write_text(json.dumps(serialize_construction(construction(), code_version="test")), encoding="utf-8")
    portfolio_path.write_text(json.dumps(portfolio_to_dict(portfolio())), encoding="utf-8")
    universe_store = _universe_store(tmp_path)
    return construction_path, portfolio_path, universe_store.path


def test_cli_executes_complete_paper_batch(tmp_path, capsys) -> None:
    construction_path, portfolio_path, universe_path = _files(tmp_path)
    result = main([
        "--construction", str(construction_path),
        "--portfolio", str(portfolio_path),
        "--decision-identifier", "decision:1",
        "--session-provider", "tests.paper_execution_factories:session_provider",
        "--quote-provider", "tests.paper_execution_factories:quote_provider",
        "--as-of", AS_OF.isoformat(),
        "--store-db", str(tmp_path / "paper.db"),
        "--eligible-universe-db", str(universe_path),
        "--journal-db", str(tmp_path / "journal.db"),
        "--require-complete",
    ])
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert len(payload["fills"]) == 2


def test_cli_require_complete_fails_for_closed_market(tmp_path, capsys) -> None:
    construction_path, portfolio_path, universe_path = _files(tmp_path)
    result = main([
        "--construction", str(construction_path),
        "--portfolio", str(portfolio_path),
        "--decision-identifier", "decision:1",
        "--session-provider", "tests.paper_execution_factories:closed_session_provider",
        "--quote-provider", "tests.paper_execution_factories:quote_provider",
        "--as-of", AS_OF.isoformat(),
        "--store-db", str(tmp_path / "paper.db"),
        "--eligible-universe-db", str(universe_path),
        "--without-journal",
        "--require-complete",
    ])
    assert result == 3
    assert json.loads(capsys.readouterr().out)["status"] == "held"


def test_cli_rejects_naive_execution_timestamp(tmp_path, capsys) -> None:
    construction_path, portfolio_path, universe_path = _files(tmp_path)
    result = main([
        "--construction", str(construction_path),
        "--portfolio", str(portfolio_path),
        "--decision-identifier", "decision:1",
        "--session-provider", "tests.paper_execution_factories:session_provider",
        "--quote-provider", "tests.paper_execution_factories:quote_provider",
        "--as-of", "2026-07-27T15:00:00",
        "--store-db", str(tmp_path / "paper.db"),
        "--eligible-universe-db", str(universe_path),
        "--without-journal",
    ])
    assert result == 4
    assert "timezone-aware" in json.loads(capsys.readouterr().out)["error"]
