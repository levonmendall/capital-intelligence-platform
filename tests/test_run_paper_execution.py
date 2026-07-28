from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from evaluation.persistence import serialize_construction
from governance.commodity_readiness import (
    evaluate_commodity_readiness,
    load_commodity_scope,
    write_commodity_readiness_report,
)
from portfolio.execution import portfolio_to_dict
from run_paper_execution import main
from tests.test_commodity_paper_test_readiness import _evidence
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

    commodity_evidence = _evidence()
    commodity_evidence["as_of"] = AS_OF.isoformat()
    commodity_evidence["knowledge_cutoff"] = AS_OF.isoformat()
    commodity_evidence["expires_at"] = (AS_OF + timedelta(days=1)).isoformat()
    commodity_evidence["eligible_universe_publication_identifier"] = "eligible-universe:test"
    for benchmark in commodity_evidence["benchmarks"]:
        benchmark["observed_at"] = (AS_OF - timedelta(minutes=10)).isoformat()
        benchmark["available_at"] = (AS_OF - timedelta(minutes=9)).isoformat()
        benchmark["retrieved_at"] = (AS_OF - timedelta(minutes=8)).isoformat()
    for proxy in commodity_evidence["proxies"]:
        proxy["eligible_universe_publication_identifier"] = "eligible-universe:test"
    commodity_report = evaluate_commodity_readiness(
        scope=load_commodity_scope(),
        evidence=commodity_evidence,
    )
    commodity_path = tmp_path / "commodity-readiness.json"
    write_commodity_readiness_report(commodity_report, commodity_path)
    return construction_path, portfolio_path, universe_store.path, commodity_path


def test_cli_executes_complete_paper_batch(tmp_path, capsys) -> None:
    construction_path, portfolio_path, universe_path, commodity_path = _files(tmp_path)
    result = main([
        "--construction", str(construction_path),
        "--portfolio", str(portfolio_path),
        "--decision-identifier", "decision:1",
        "--session-provider", "tests.paper_execution_factories:session_provider",
        "--quote-provider", "tests.paper_execution_factories:quote_provider",
        "--as-of", AS_OF.isoformat(),
        "--commodity-readiness-report", str(commodity_path),
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
    construction_path, portfolio_path, universe_path, commodity_path = _files(tmp_path)
    result = main([
        "--construction", str(construction_path),
        "--portfolio", str(portfolio_path),
        "--decision-identifier", "decision:1",
        "--session-provider", "tests.paper_execution_factories:closed_session_provider",
        "--quote-provider", "tests.paper_execution_factories:quote_provider",
        "--as-of", AS_OF.isoformat(),
        "--commodity-readiness-report", str(commodity_path),
        "--store-db", str(tmp_path / "paper.db"),
        "--eligible-universe-db", str(universe_path),
        "--without-journal",
        "--require-complete",
    ])
    assert result == 3
    assert json.loads(capsys.readouterr().out)["status"] == "held"


def test_cli_rejects_missing_commodity_readiness(tmp_path, capsys) -> None:
    construction_path, portfolio_path, universe_path, _ = _files(tmp_path)
    result = main([
        "--construction", str(construction_path),
        "--portfolio", str(portfolio_path),
        "--decision-identifier", "decision:1",
        "--session-provider", "tests.paper_execution_factories:session_provider",
        "--quote-provider", "tests.paper_execution_factories:quote_provider",
        "--as-of", AS_OF.isoformat(),
        "--store-db", str(tmp_path / "paper.db"),
        "--eligible-universe-db", str(universe_path),
        "--without-journal",
    ])
    assert result == 4
    assert "commodity readiness report is required" in json.loads(
        capsys.readouterr().out
    )["error"]


def test_cli_rejects_naive_execution_timestamp(tmp_path, capsys) -> None:
    construction_path, portfolio_path, universe_path, commodity_path = _files(tmp_path)
    result = main([
        "--construction", str(construction_path),
        "--portfolio", str(portfolio_path),
        "--decision-identifier", "decision:1",
        "--session-provider", "tests.paper_execution_factories:session_provider",
        "--quote-provider", "tests.paper_execution_factories:quote_provider",
        "--as-of", "2026-07-27T15:00:00",
        "--commodity-readiness-report", str(commodity_path),
        "--store-db", str(tmp_path / "paper.db"),
        "--eligible-universe-db", str(universe_path),
        "--without-journal",
    ])
    assert result == 4
    assert "timezone-aware" in json.loads(capsys.readouterr().out)["error"]
