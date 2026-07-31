from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import paper_execution_runtime
from governance.paper_decision_approval import canonical_construction_sha256
from operations.paper_execution_leases import (
    PaperExecutionLeaseLost,
    SQLitePaperExecutionLeaseStore,
)
from tests.test_streamlit_paper_execution_worker import (
    _briefing,
    _configure,
    _construction,
)


UTC = timezone.utc


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 31, 18, tzinfo=UTC)

    def __call__(self):
        return self.value


def test_only_one_owner_and_expired_takeover_is_fenced(tmp_path) -> None:
    clock = MutableClock()
    store_a = SQLitePaperExecutionLeaseStore(tmp_path / "leases.db", clock=clock)
    store_b = SQLitePaperExecutionLeaseStore(tmp_path / "leases.db", clock=clock)
    first = store_a.acquire("a" * 64, owner_identifier="worker:a", lease_seconds=30)
    assert first is not None
    assert store_b.acquire(
        "a" * 64,
        owner_identifier="worker:b",
        lease_seconds=30,
    ) is None

    clock.value += timedelta(seconds=31)
    replacement = store_b.acquire(
        "a" * 64,
        owner_identifier="worker:b",
        lease_seconds=30,
    )
    assert replacement is not None
    assert replacement.fencing_token > first.fencing_token
    with pytest.raises(PaperExecutionLeaseLost):
        store_a.renew(first, lease_seconds=30)
    store_a.release(first)
    assert store_b.renew(replacement, lease_seconds=30).fencing_token == (
        replacement.fencing_token
    )


def test_runtime_rejects_overlapping_exact_construction(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PAPER_EXECUTION_LEASE_SECONDS", "30")
    with paper_execution_runtime._construction_lease("b" * 64) as first:
        assert first is not None
        with paper_execution_runtime._construction_lease("b" * 64) as second:
            assert second is None


def test_lost_fence_blocks_status_publication_after_runner_returns(
    monkeypatch,
    tmp_path,
) -> None:
    _configure(monkeypatch, tmp_path)
    construction = _construction()

    def lose_fence(_self) -> None:
        raise PaperExecutionLeaseLost("replacement worker owns the fence")

    monkeypatch.setattr(
        paper_execution_runtime._MaintainedExecutionLease,
        "assert_owned",
        lose_fence,
    )

    def runner(_arguments):
        print(json.dumps({"status": "completed", "execution_identifier": "execution:1"}))
        return 0

    attempt = paper_execution_runtime.attempt_paper_execution(
        construction=construction,
        briefing=_briefing(),
        now=datetime(2026, 7, 28, 19, 1, tzinfo=UTC),
        runner=runner,
    )

    assert attempt.state == "blocked"
    assert "reconciliation is required" in attempt.detail
    status = (
        tmp_path
        / "paper_execution_artifacts"
        / f"{canonical_construction_sha256(construction)}.status.json"
    )
    assert not status.exists()
