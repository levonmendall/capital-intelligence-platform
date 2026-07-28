"""Tests for exact authenticated consent before paper execution."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from governance.paper_decision_approval import (
    PaperDecisionApprovalError,
    PaperDecisionApprovalIntegrityError,
    PaperDecisionApprovalState,
    SQLitePaperDecisionApprovalStore,
    canonical_construction_sha256,
    require_user_approved_paper_decision,
)

UTC = timezone.utc
AS_OF = datetime(2026, 7, 28, 18, 0, tzinfo=UTC)


def _construction() -> dict:
    return {
        "request_identifier": "construction:decision-1",
        "status": "ready",
        "trades": [
            {
                "symbol": "SPY",
                "side": "buy",
                "trade_weight": 0.10,
            }
        ],
    }


def test_exact_approval_is_active_and_hash_bound(tmp_path) -> None:
    payload = _construction()
    digest = canonical_construction_sha256(payload)
    store = SQLitePaperDecisionApprovalStore(tmp_path / "governance.db")
    approval = store.approve(
        decision_identifier="decision:1",
        construction_identifier=payload["request_identifier"],
        construction_sha256=digest,
        actor_user_id="user:1",
        actor_session_id="session:1",
        occurred_at=AS_OF,
        rationale="Approve exact paper implementation.",
        ttl=timedelta(hours=2),
    )

    required = require_user_approved_paper_decision(
        store=store,
        decision_identifier="decision:1",
        construction_identifier=payload["request_identifier"],
        construction_sha256=digest,
        as_of=AS_OF + timedelta(minutes=1),
    )

    assert required == approval
    assert required.active_at(AS_OF + timedelta(minutes=1))
    assert required.to_dict()["real_money_authorized"] is False
    assert store.verify_integrity()

    altered = {**payload, "trades": [{**payload["trades"][0], "trade_weight": 0.11}]}
    with pytest.raises(PaperDecisionApprovalError, match="hash does not match"):
        require_user_approved_paper_decision(
            store=store,
            decision_identifier="decision:1",
            construction_identifier=payload["request_identifier"],
            construction_sha256=canonical_construction_sha256(altered),
            as_of=AS_OF + timedelta(minutes=1),
        )


def test_latest_decline_or_execution_prevents_reuse(tmp_path) -> None:
    payload = _construction()
    digest = canonical_construction_sha256(payload)
    store = SQLitePaperDecisionApprovalStore(tmp_path / "governance.db")
    store.approve(
        decision_identifier="decision:1",
        construction_identifier=payload["request_identifier"],
        construction_sha256=digest,
        actor_user_id="user:1",
        actor_session_id="session:1",
        occurred_at=AS_OF,
        rationale="Approve.",
    )
    store.conclude(
        state=PaperDecisionApprovalState.DECLINED,
        decision_identifier="decision:1",
        construction_identifier=payload["request_identifier"],
        construction_sha256=digest,
        actor_user_id="user:1",
        actor_session_id="session:1",
        occurred_at=AS_OF + timedelta(minutes=1),
        rationale="Changed decision.",
    )
    with pytest.raises(PaperDecisionApprovalError, match="declined"):
        require_user_approved_paper_decision(
            store=store,
            decision_identifier="decision:1",
            construction_identifier=payload["request_identifier"],
            construction_sha256=digest,
            as_of=AS_OF + timedelta(minutes=2),
        )

    store.approve(
        decision_identifier="decision:1",
        construction_identifier=payload["request_identifier"],
        construction_sha256=digest,
        actor_user_id="user:1",
        actor_session_id="session:2",
        occurred_at=AS_OF + timedelta(minutes=3),
        rationale="Approve after review.",
    )
    store.conclude(
        state=PaperDecisionApprovalState.EXECUTED,
        decision_identifier="decision:1",
        construction_identifier=payload["request_identifier"],
        construction_sha256=digest,
        actor_user_id="system:paper-execution",
        actor_session_id="worker:1",
        occurred_at=AS_OF + timedelta(minutes=4),
        rationale="Executed once.",
        execution_identifier="multi-asset-execution:construction:decision-1",
    )
    with pytest.raises(PaperDecisionApprovalError, match="executed"):
        require_user_approved_paper_decision(
            store=store,
            decision_identifier="decision:1",
            construction_identifier=payload["request_identifier"],
            construction_sha256=digest,
            as_of=AS_OF + timedelta(minutes=5),
        )


def test_approval_chain_detects_tampering(tmp_path) -> None:
    payload = _construction()
    store = SQLitePaperDecisionApprovalStore(tmp_path / "governance.db")
    store.approve(
        decision_identifier="decision:1",
        construction_identifier=payload["request_identifier"],
        construction_sha256=canonical_construction_sha256(payload),
        actor_user_id="user:1",
        actor_session_id="session:1",
        occurred_at=AS_OF,
        rationale="Approve.",
    )
    with sqlite3.connect(store.path) as connection:
        row = connection.execute(
            "SELECT sequence, payload_json FROM paper_decision_approval_events"
        ).fetchone()
        value = json.loads(row[1])
        value["rationale"] = "tampered"
        connection.execute(
            "UPDATE paper_decision_approval_events SET payload_json = ? WHERE sequence = ?",
            (json.dumps(value, sort_keys=True), row[0]),
        )

    with pytest.raises(PaperDecisionApprovalIntegrityError):
        store.verify_integrity()
