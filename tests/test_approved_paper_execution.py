"""Tests for the consent-gated paper execution entrypoint."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from delivery import AlertChannel, AlertTopic, DeliveryStatus, SQLiteAlertStore
from governance.paper_decision_approval import (
    PaperDecisionApprovalState,
    SQLitePaperDecisionApprovalStore,
    canonical_construction_sha256,
)
import run_approved_paper_execution

UTC = timezone.utc
AS_OF = datetime(2026, 7, 28, 18, 0, tzinfo=UTC)


def _write_construction(path) -> dict:
    payload = {
        "request_identifier": "construction:decision-1",
        "as_of": (AS_OF - timedelta(minutes=10)).isoformat(),
        "status": "ready",
        "trades": [{"symbol": "SPY", "side": "buy", "trade_weight": 0.10}],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_wrapper_blocks_without_exact_user_approval(tmp_path, monkeypatch, capsys) -> None:
    construction_path = tmp_path / "construction.json"
    _write_construction(construction_path)
    delegated = []
    monkeypatch.setattr(
        run_approved_paper_execution,
        "run_multi_asset_paper_execution",
        lambda argv: delegated.append(argv) or 0,
    )

    result = run_approved_paper_execution.main(
        [
            "--construction",
            str(construction_path),
            "--decision-identifier",
            "decision:1",
            "--as-of",
            AS_OF.isoformat(),
            "--approval-database",
            str(tmp_path / "governance.db"),
            "--alert-database",
            str(tmp_path / "alerts.db"),
            "--profiles",
            "profiles.json",
        ]
    )

    assert result == 4
    assert delegated == []
    output = json.loads(capsys.readouterr().out)
    assert output["user_approval_required"] is True
    assert output["real_money_authorized"] is False


def test_wrapper_delegates_marks_execution_and_notifies_approver(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    construction_path = tmp_path / "construction.json"
    payload = _write_construction(construction_path)
    database = tmp_path / "governance.db"
    alert_database = tmp_path / "alerts.db"
    store = SQLitePaperDecisionApprovalStore(database)
    store.approve(
        decision_identifier="decision:1",
        construction_identifier=payload["request_identifier"],
        construction_sha256=canonical_construction_sha256(payload),
        actor_user_id="user:1",
        actor_session_id="session:1",
        occurred_at=AS_OF - timedelta(minutes=1),
        rationale="Approve exact implementation.",
    )
    delegated = []
    monkeypatch.setattr(
        run_approved_paper_execution,
        "run_multi_asset_paper_execution",
        lambda argv: delegated.append(argv) or 0,
    )

    result = run_approved_paper_execution.main(
        [
            "--construction",
            str(construction_path),
            "--decision-identifier",
            "decision:1",
            "--as-of",
            AS_OF.isoformat(),
            "--approval-database",
            str(database),
            "--alert-database",
            str(alert_database),
            "--profiles",
            "profiles.json",
            "--session-provider",
            "provider:session",
            "--quote-provider",
            "provider:quote",
            "--development-bypass-launch-gate",
        ]
    )

    assert result == 0
    assert delegated
    assert "--profiles" in delegated[0]
    latest = store.latest("decision:1", payload["request_identifier"])
    assert latest is not None
    assert latest.state is PaperDecisionApprovalState.EXECUTED
    assert latest.execution_identifier == (
        "multi-asset-execution:construction:decision-1"
    )

    deliveries = SQLiteAlertStore(alert_database).list_deliveries("user:1")
    assert len(deliveries) == 1
    notification = deliveries[0]
    assert notification.channel is AlertChannel.IN_APP
    assert notification.status is DeliveryStatus.SENT
    assert notification.topics == (AlertTopic.IMPLEMENTATION,)
    assert notification.subject == "Paper transaction completed"
    assert "simulated paper transaction" in notification.body

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "completed"
    assert output["completion_notification_delivery_ids"] == [
        notification.delivery_id
    ]
    assert output["real_money_authorized"] is False


def test_incomplete_execution_does_not_notify_or_consume_approval(
    tmp_path,
    monkeypatch,
) -> None:
    construction_path = tmp_path / "construction.json"
    payload = _write_construction(construction_path)
    database = tmp_path / "governance.db"
    alert_database = tmp_path / "alerts.db"
    store = SQLitePaperDecisionApprovalStore(database)
    store.approve(
        decision_identifier="decision:1",
        construction_identifier=payload["request_identifier"],
        construction_sha256=canonical_construction_sha256(payload),
        actor_user_id="user:1",
        actor_session_id="session:1",
        occurred_at=AS_OF - timedelta(minutes=1),
        rationale="Approve exact implementation.",
    )
    monkeypatch.setattr(
        run_approved_paper_execution,
        "run_multi_asset_paper_execution",
        lambda argv: 3,
    )

    result = run_approved_paper_execution.main(
        [
            "--construction",
            str(construction_path),
            "--decision-identifier",
            "decision:1",
            "--as-of",
            AS_OF.isoformat(),
            "--approval-database",
            str(database),
            "--alert-database",
            str(alert_database),
            "--profiles",
            "profiles.json",
        ]
    )

    assert result == 3
    latest = store.latest("decision:1", payload["request_identifier"])
    assert latest is not None
    assert latest.state is PaperDecisionApprovalState.APPROVED
    assert SQLiteAlertStore(alert_database).list_deliveries("user:1") == ()
