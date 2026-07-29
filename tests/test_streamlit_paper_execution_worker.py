from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from governance.paper_decision_approval import (
    SQLitePaperDecisionApprovalStore,
    canonical_construction_sha256,
)
from streamlit_paper_execution_worker import attempt_approved_paper_execution


def _construction() -> dict:
    return {
        "request_identifier": "construction:test-vti",
        "as_of": "2026-07-28T19:00:00+00:00",
        "status": "feasible",
        "policy_version": "portfolio-construction.v1",
        "target_cash_weight": 0.9,
        "target_weights": [{"symbol": "VTI", "weight": 0.1}],
        "trades": [
            {
                "symbol": "VTI",
                "side": "buy",
                "from_weight": 0.0,
                "to_weight": 0.1,
                "trade_weight": 0.1,
                "estimated_cost_return": 0.0,
                "reason": "test governed paper execution",
                "funding_for": [],
            }
        ],
        "turnover": 0.1,
        "estimated_cost_return": 0.0,
        "expected_return_before": 0.0,
        "expected_return_after_cost": 0.01,
        "expected_return_improvement": 0.01,
        "constraints": [],
        "blocks": [],
        "eligible_universe_publication_identifier": "universe:test",
        "instrument_identifiers": [
            {
                "symbol": "VTI",
                "instrument_identifier": "instrument:us-etf:vti",
            }
        ],
    }


def _configure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_ENVIRONMENT", "paper")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_STREAMLIT_PAPER_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PAPER_EXECUTION_RETRY_SECONDS", "5")
    monkeypatch.setenv("APCA_API_KEY_ID", "paper-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "paper-secret")


def _approve(tmp_path: Path, construction: dict, now: datetime) -> None:
    store = SQLitePaperDecisionApprovalStore(tmp_path / "paper_test_governance.db")
    store.approve(
        decision_identifier="decision:test",
        construction_identifier=construction["request_identifier"],
        construction_sha256=canonical_construction_sha256(construction),
        actor_user_id="user:test",
        actor_session_id="session:test",
        occurred_at=now - timedelta(seconds=1),
        rationale="approve exact test construction",
    )


def test_worker_materializes_exact_trade_profiles_and_delegates(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    construction = _construction()
    now = datetime(2026, 7, 28, 19, 1, tzinfo=timezone.utc)
    _approve(tmp_path, construction, now)
    captured: list[str] = []

    def runner(arguments):
        captured.extend(arguments or ())
        print(
            json.dumps(
                {
                    "status": "completed",
                    "execution_identifier": "multi-asset-execution:construction:test-vti",
                    "real_money_authorized": False,
                }
            )
        )
        return 0

    attempt = attempt_approved_paper_execution(
        construction=construction,
        briefing={"decision_identifier": "decision:test"},
        now=now,
        runner=runner,
    )

    assert attempt.completed is True
    assert attempt.execution_identifier == "multi-asset-execution:construction:test-vti"
    assert "--development-bypass-launch-gate" not in captured
    profiles_path = Path(captured[captured.index("--profiles") + 1])
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    assert [item["symbol"] for item in profiles] == ["VTI"]
    construction_path = Path(captured[captured.index("--construction") + 1])
    assert json.loads(construction_path.read_text(encoding="utf-8")) == construction


def test_worker_does_not_run_without_exact_approval(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    called = False

    def runner(_arguments):
        nonlocal called
        called = True
        return 0

    attempt = attempt_approved_paper_execution(
        construction=_construction(),
        briefing={"decision_identifier": "decision:test"},
        now=datetime(2026, 7, 28, 19, 1, tzinfo=timezone.utc),
        runner=runner,
    )

    assert attempt.state == "idle"
    assert called is False


def test_worker_throttles_held_retries(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    construction = _construction()
    now = datetime(2026, 7, 28, 19, 1, tzinfo=timezone.utc)
    _approve(tmp_path, construction, now)
    calls = 0

    def runner(_arguments):
        nonlocal calls
        calls += 1
        print(json.dumps({"status": "held", "real_money_authorized": False}))
        return 3

    first = attempt_approved_paper_execution(
        construction=construction,
        briefing={"decision_identifier": "decision:test"},
        now=now,
        runner=runner,
    )
    second = attempt_approved_paper_execution(
        construction=construction,
        briefing={"decision_identifier": "decision:test"},
        now=now + timedelta(seconds=1),
        runner=runner,
    )

    assert first.state == "held"
    assert second.state == "held"
    assert calls == 1


def test_production_uses_same_immediate_paper_only_path(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_ENVIRONMENT", "production")
    construction = _construction()
    now = datetime(2026, 7, 28, 19, 1, tzinfo=timezone.utc)
    _approve(tmp_path, construction, now)
    captured: list[str] = []

    def runner(arguments):
        captured.extend(arguments or ())
        print(
            json.dumps(
                {
                    "status": "completed",
                    "execution_identifier": "multi-asset-execution:construction:test-vti",
                    "launch_clearance_required": False,
                    "real_money_authorized": False,
                }
            )
        )
        return 0

    attempt = attempt_approved_paper_execution(
        construction=construction,
        briefing={"decision_identifier": "decision:test"},
        now=now,
        runner=runner,
    )

    assert attempt.state == "completed"
    assert "--development-bypass-launch-gate" not in captured
