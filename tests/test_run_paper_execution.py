from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from evaluation.persistence import serialize_construction
from portfolio.constants import CANONICAL_PORTFOLIO_CODE
from portfolio.execution import portfolio_to_dict
from portfolio.state import SQLiteCanonicalPortfolioStore
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
    canonical_path = tmp_path / "canonical_portfolio.db"
    return construction_path, portfolio_path, universe_store.path, canonical_path


def test_cli_executes_complete_paper_batch_without_mutating_canonical_portfolio(tmp_path, capsys) -> None:
    construction_path, portfolio_path, universe_path, canonical_path = _files(tmp_path)
    result = main([
        "--construction", str(construction_path),
        "--portfolio", str(portfolio_path),
        "--decision-identifier", "decision:1",
        "--session-provider", "tests.paper_execution_factories:session_provider",
        "--quote-provider", "tests.paper_execution_factories:quote_provider",
        "--as-of", AS_OF.isoformat(),
        "--store-db", str(tmp_path / "paper.db"),
        "--portfolio-db", str(canonical_path),
        "--eligible-universe-db", str(universe_path),
        "--journal-db", str(tmp_path / "journal.db"),
        "--require-complete",
    ])
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert len(payload["fills"]) == 2
    assert payload["canonical_portfolio_mutated"] is False
    assert payload["canonical_execution_authority"] == "run_multi_asset_paper_execution"

    canonical = SQLiteCanonicalPortfolioStore(canonical_path)
    canonical.verify_integrity()
    history = canonical.history(CANONICAL_PORTFOLIO_CODE)
    assert len(history) == 1
    latest = canonical.latest(CANONICAL_PORTFOLIO_CODE)
    assert latest is not None
    assert latest.starting_capital == 250000
    assert latest.cash_amount == 250000
    assert latest.positions == ()
    assert latest.accounting_residual == 0


def test_cli_require_complete_fails_for_closed_market(tmp_path, capsys) -> None:
    construction_path, portfolio_path, universe_path, canonical_path = _files(tmp_path)
    result = main([
        "--construction", str(construction_path),
        "--portfolio", str(portfolio_path),
        "--decision-identifier", "decision:1",
        "--session-provider", "tests.paper_execution_factories:closed_session_provider",
        "--quote-provider", "tests.paper_execution_factories:quote_provider",
        "--as-of", AS_OF.isoformat(),
        "--store-db", str(tmp_path / "paper.db"),
        "--portfolio-db", str(canonical_path),
        "--eligible-universe-db", str(universe_path),
        "--without-journal",
        "--require-complete",
    ])
    assert result == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "held"
    assert payload["canonical_portfolio_mutated"] is False


def test_cli_rejects_naive_execution_timestamp(tmp_path, capsys) -> None:
    construction_path, portfolio_path, universe_path, canonical_path = _files(tmp_path)
    result = main([
        "--construction", str(construction_path),
        "--portfolio", str(portfolio_path),
        "--decision-identifier", "decision:1",
        "--session-provider", "tests.paper_execution_factories:session_provider",
        "--quote-provider", "tests.paper_execution_factories:quote_provider",
        "--as-of", "2026-07-27T15:00:00",
        "--store-db", str(tmp_path / "paper.db"),
        "--portfolio-db", str(canonical_path),
        "--eligible-universe-db", str(universe_path),
        "--without-journal",
    ])
    assert result == 4
    assert "timezone-aware" in json.loads(capsys.readouterr().out)["error"]
